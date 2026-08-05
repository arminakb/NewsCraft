from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact_secrets
from app.jobs.capability_gate import api_capability_gate_enabled, require_available_job_type
from app.jobs.errors import InvalidJobTransition
from app.jobs.events import redact_event_data
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus
from app.retention.models import RetentionRun

_RETENTION_PREVIEW_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class EnqueueJobResult:
    job: WorkflowJob
    created: bool


@dataclass(frozen=True, slots=True)
class _ExpiredLeaseDependents:
    retention_run: RetentionRun | None
    research_runs: tuple[Any, ...]
    research_attempts: tuple[Any, ...]
    automation_dispatches: tuple[Any, ...]
    generation_runs: tuple[Any, ...]
    generation_attempts: tuple[Any, ...]
    publish_jobs: tuple[Any, ...]
    publish_receipts: tuple[Any, ...]
    publish_attempts: tuple[Any, ...]


def _now(value: datetime | None) -> datetime:
    return value if value is not None else datetime.now(UTC)


def _enum_value(value: str | JobStatus | JobErrorClass | JobOrigin) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _redact_job_payload(job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = redact_secrets(payload)
    if not isinstance(sanitized, dict):  # pragma: no cover - dict input contract
        return {}

    if job_type == "execute_retention":
        preview_token = payload.get("preview_token")
        if isinstance(preview_token, str) and _RETENTION_PREVIEW_TOKEN_PATTERN.fullmatch(preview_token):
            # This opaque, server-generated capability is required by the retention
            # handler. Keep the exemption local to its validated job contract so the
            # same key remains secret everywhere else.
            sanitized["preview_token"] = preview_token
    return sanitized


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _append_event(
        self,
        *,
        job_id: UUID,
        event_type: str,
        actor: str,
        event_data: dict[str, Any],
    ) -> None:
        self.session.add(
            WorkflowEvent(
                workflow_job_id=job_id,
                event_type=event_type,
                actor=actor,
                event_data=redact_event_data(event_data),
            )
        )

    async def _locked_job(self, job_id: UUID) -> WorkflowJob | None:
        return await self.session.scalar(select(WorkflowJob).where(WorkflowJob.id == job_id).with_for_update())

    async def _locked_expired_job(self, job_id: UUID) -> WorkflowJob | None:
        return await self.session.scalar(
            select(WorkflowJob)
            .where(WorkflowJob.id == job_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )

    async def _locked_retention_run(self, job_id: UUID) -> RetentionRun | None:
        run = await self.session.scalar(
            select(RetentionRun).where(RetentionRun.workflow_job_id == job_id).with_for_update()
        )
        return run if isinstance(run, RetentionRun) else None

    async def _lock_expired_lease_dependents(
        self,
        *,
        job_id: UUID,
        payload: dict[str, Any],
    ) -> _ExpiredLeaseDependents:
        # Handlers lock their domain run before the workflow job. Preserve that
        # order here so lease recovery cannot deadlock an in-flight final commit.
        from app.automations.models import AutomationDispatch
        from app.generation.models import GenerationAttempt, GenerationRun
        from app.publishing.models import PublishAttempt, PublishJob, PublishOperationReceipt
        from app.research.continuations import TelegramResearchContinuation
        from app.research.models import ResearchAttempt, ResearchRun

        retention_run = await self._locked_retention_run(job_id)

        research_runs: list[ResearchRun] = []
        raw_run_id = payload.get("run_id")
        try:
            research_run_id = UUID(str(raw_run_id)) if raw_run_id is not None else None
        except ValueError:
            research_run_id = None
        if research_run_id is not None:
            research_runs = list(
                await self.session.scalars(
                    select(ResearchRun)
                    .where(ResearchRun.id == research_run_id)
                    .order_by(ResearchRun.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
        research_attempts = (
            list(
                await self.session.scalars(
                    select(ResearchAttempt)
                    .where(ResearchAttempt.research_run_id.in_([run.id for run in research_runs]))
                    .order_by(ResearchAttempt.research_run_id, ResearchAttempt.attempt_number)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if research_runs
            else []
        )

        dispatch_ids: set[UUID] = set()
        raw_dispatch_id = payload.get("dispatch_id")
        try:
            dispatch_id = UUID(str(raw_dispatch_id)) if raw_dispatch_id is not None else None
        except ValueError:
            dispatch_id = None
        if dispatch_id is not None:
            dispatch_ids.add(dispatch_id)
        descriptors: list[Any] = []
        plural_descriptors = payload.get("continuations")
        if isinstance(plural_descriptors, list):
            descriptors.extend(plural_descriptors)
        for descriptor in descriptors:
            try:
                continuation = TelegramResearchContinuation.model_validate(descriptor).validate_identity()
            except TypeError, ValueError:
                continue
            dispatch_ids.add(continuation.payload.dispatch_id)
        automation_dispatches: list[AutomationDispatch] = []
        if dispatch_ids:
            automation_dispatches = list(
                await self.session.scalars(
                    select(AutomationDispatch)
                    .where(AutomationDispatch.id.in_(dispatch_ids))
                    .order_by(AutomationDispatch.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )

        generation_runs = list(
            await self.session.scalars(
                select(GenerationRun)
                .where(
                    or_(
                        GenerationRun.request_payload["execution"]["workflow_job_id"].as_string() == str(job_id),
                        GenerationRun.request_payload["execution"]["active_workflow_job_id"].as_string() == str(job_id),
                    )
                )
                .order_by(GenerationRun.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        generation_attempts = (
            list(
                await self.session.scalars(
                    select(GenerationAttempt)
                    .where(GenerationAttempt.generation_run_id.in_([run.id for run in generation_runs]))
                    .order_by(GenerationAttempt.generation_run_id, GenerationAttempt.attempt_number)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if generation_runs
            else []
        )

        publish_jobs = list(
            await self.session.scalars(
                select(PublishJob)
                .where(PublishJob.workflow_job_id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        publish_receipts = (
            list(
                await self.session.scalars(
                    select(PublishOperationReceipt)
                    .where(PublishOperationReceipt.publish_job_id.in_([job.id for job in publish_jobs]))
                    .order_by(
                        PublishOperationReceipt.publish_job_id,
                        PublishOperationReceipt.operation_index,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if publish_jobs
            else []
        )
        publish_attempts = (
            list(
                await self.session.scalars(
                    select(PublishAttempt)
                    .where(PublishAttempt.publish_job_id.in_([job.id for job in publish_jobs]))
                    .order_by(PublishAttempt.publish_job_id, PublishAttempt.attempt_number)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if publish_jobs
            else []
        )
        return _ExpiredLeaseDependents(
            retention_run=retention_run,
            research_runs=tuple(research_runs),
            research_attempts=tuple(research_attempts),
            automation_dispatches=tuple(automation_dispatches),
            generation_runs=tuple(generation_runs),
            generation_attempts=tuple(generation_attempts),
            publish_jobs=tuple(publish_jobs),
            publish_receipts=tuple(publish_receipts),
            publish_attempts=tuple(publish_attempts),
        )

    @staticmethod
    def _sync_expired_publish_ambiguity(
        dependents: _ExpiredLeaseDependents,
        *,
        observed_at: datetime,
    ) -> bool:
        requires_review = False
        for publish_job in dependents.publish_jobs:
            receipts = [receipt for receipt in dependents.publish_receipts if receipt.publish_job_id == publish_job.id]
            attempts = [attempt for attempt in dependents.publish_attempts if attempt.publish_job_id == publish_job.id]
            dispatching = [receipt for receipt in receipts if receipt.status == "dispatching"]
            if not dispatching:
                continue
            requires_review = True
            for receipt in dispatching:
                receipt.status = "ambiguous"
                receipt.ambiguous_at = observed_at
            publish_job.status = "reconciliation_required"
            for attempt in attempts:
                if attempt.status == "running":
                    attempt.status = "needs_review"
                    attempt.error_class = "needs_review"
                    attempt.error_code = "telegram_publish_ambiguous"
                    attempt.error_message = "Telegram publish outcome is ambiguous after worker interruption"
                    attempt.finished_at = observed_at
        return requires_review

    @staticmethod
    def _sync_terminal_expired_lease_dependents(
        dependents: _ExpiredLeaseDependents,
        *,
        observed_at: datetime,
    ) -> None:
        code = "worker_lease_expired"
        message = "Worker lease expired after the final configured attempt"
        for run in dependents.research_runs:
            if run.status in {"queued", "running"}:
                run.status = "failed"
                run.finished_at = observed_at
        for attempt in dependents.research_attempts:
            if attempt.status == "running":
                attempt.status = "failed"
                attempt.error_class = "retryable"
                attempt.error_code = code
                attempt.error_message = message
                attempt.finished_at = observed_at
        for run in dependents.generation_runs:
            if run.status == "running":
                run.status = "failed"
                run.error_class = "retryable"
                run.error_code = code
                run.error_message = message
                run.finished_at = observed_at
        for attempt in dependents.generation_attempts:
            if attempt.status == "running":
                attempt.status = "failed"
                attempt.error_class = "retryable"
                attempt.error_code = code
                attempt.error_message = message
                attempt.finished_at = observed_at
        for dispatch in dependents.automation_dispatches:
            if dispatch.status in {"captured", "retryable", "generating"}:
                dispatch.status = "failed"
                dispatch.error_code = code
                dispatch.error_message = message
            elif dispatch.status == "researching":
                dispatch.status = "needs_review"
                dispatch.error_code = code
                dispatch.error_message = message
        for publish_job in dependents.publish_jobs:
            attempts = [attempt for attempt in dependents.publish_attempts if attempt.publish_job_id == publish_job.id]
            for attempt in attempts:
                if attempt.status == "running":
                    attempt.status = "failed"
                    attempt.error_class = "retryable"
                    attempt.error_code = "telegram_publish_attempt_interrupted"
                    attempt.error_message = "Telegram publish attempt ended when its worker lease expired"
                    attempt.finished_at = observed_at
            if publish_job.status in {"queued", "scheduled", "dispatching"}:
                publish_job.status = "attention"

    @staticmethod
    def _sync_retention_terminal(
        run: RetentionRun | None,
        *,
        job_status: JobStatus,
        observed_at: datetime,
    ) -> None:
        if run is None or run.status in {"succeeded", "expired"}:
            return
        if job_status == JobStatus.CANCELLED:
            code = "retention_job_cancelled"
            message = "Retention workflow job was cancelled before completion"
        elif job_status == JobStatus.NEEDS_REVIEW:
            code = "retention_job_needs_review"
            message = "Retention workflow job requires operator review"
        else:
            code = "retention_job_failed"
            message = "Retention workflow job failed before completion"
        if run.status == "running":
            run.status = "partial"
        elif run.status in {"previewed", "queued"}:
            run.status = "failed"
        run.finished_at = observed_at
        run.error_snapshot = [error for error in run.error_snapshot if error.get("phase") != "workflow"] + [
            {"phase": "workflow", "code": code, "message": message}
        ]

    @staticmethod
    def _sync_retention_retry(
        run: RetentionRun | None,
        *,
        observed_at: datetime,
    ) -> None:
        if run is None:
            return
        run.error_snapshot = [error for error in run.error_snapshot if error.get("phase") != "workflow"]
        if run.status == "failed" and run.started_at is None:
            run.status = "queued"
            run.finished_at = None
            run.queued_at = observed_at

    @staticmethod
    def _invalid(job_id: UUID, *, action: str, job: WorkflowJob | None) -> InvalidJobTransition:
        status = "missing" if job is None else str(job.status)
        return InvalidJobTransition(job_id, action=action, status=status)

    async def enqueue_job(
        self,
        *,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        origin: JobOrigin,
        priority: int = 0,
        scheduled_for: datetime | None = None,
        max_attempts: int = 3,
        pause_sensitive: bool = True,
        automation_run_id: UUID | None = None,
        automation_node_run_id: UUID | None = None,
    ) -> EnqueueJobResult:
        effective_scheduled_for = _now(scheduled_for)
        safe_payload = _redact_job_payload(job_type, payload)
        if api_capability_gate_enabled(self.session):
            existing = await self.session.scalar(
                select(WorkflowJob).where(WorkflowJob.idempotency_key == idempotency_key)
            )
            if existing is not None:
                if existing.scheduled_for is None:
                    existing.scheduled_for = effective_scheduled_for
                    await self.session.flush()
                return EnqueueJobResult(job=existing, created=False)
            await require_available_job_type(self.session, job_type)
        statement = (
            insert(WorkflowJob)
            .values(
                job_type=job_type,
                payload=safe_payload,
                idempotency_key=idempotency_key,
                origin=_enum_value(origin),
                priority=priority,
                scheduled_for=effective_scheduled_for,
                max_attempts=max_attempts,
                pause_sensitive=pause_sensitive,
                automation_run_id=automation_run_id,
                automation_node_run_id=automation_node_run_id,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(WorkflowJob.id)
        )
        job_id = (await self.session.execute(statement)).scalar_one_or_none()
        created = job_id is not None
        if created:
            job = await self.session.get(WorkflowJob, job_id)
            if job is None:  # pragma: no cover - defensive against a broken RETURNING contract
                raise RuntimeError("Enqueued workflow job could not be loaded")
            await self._append_event(
                job_id=job.id,
                event_type="job.enqueued",
                actor=_enum_value(origin),
                event_data={"job_type": job_type, "origin": _enum_value(origin)},
            )
            await self.session.flush()
            return EnqueueJobResult(job=job, created=True)

        job = await self.session.scalar(select(WorkflowJob).where(WorkflowJob.idempotency_key == idempotency_key))
        if job is None:  # pragma: no cover - conflict target guarantees a matching row
            raise RuntimeError("Idempotent workflow job could not be loaded")
        if job.scheduled_for is None:
            job.scheduled_for = effective_scheduled_for
            await self.session.flush()
        return EnqueueJobResult(job=job, created=False)

    def _claim_statement(
        self,
        *,
        allowed_job_types: tuple[str, ...] | None,
        global_pause: bool,
        now: datetime,
    ) -> Select[tuple[WorkflowJob]]:
        predicates = [
            WorkflowJob.status == JobStatus.QUEUED,
            or_(WorkflowJob.scheduled_for.is_(None), WorkflowJob.scheduled_for <= now),
        ]
        if allowed_job_types is not None:
            predicates.append(WorkflowJob.job_type.in_(allowed_job_types))
        if global_pause:
            predicates.extend(
                [
                    WorkflowJob.origin == JobOrigin.MANUAL,
                    WorkflowJob.pause_sensitive.is_(False),
                ]
            )
        return (
            select(WorkflowJob)
            .where(*predicates)
            .order_by(
                WorkflowJob.priority.desc(),
                WorkflowJob.scheduled_for.asc().nulls_first(),
                WorkflowJob.created_at.asc(),
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    async def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        allowed_job_types: tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> WorkflowJob | None:
        if allowed_job_types == ():
            return None

        observed_at = _now(now)
        global_pause = bool(
            await self.session.scalar(select(AutomationControl.global_pause).where(AutomationControl.id == "global"))
        )
        statement = self._claim_statement(
            allowed_job_types=allowed_job_types,
            global_pause=global_pause,
            now=observed_at,
        )
        job = await self.session.scalar(statement)
        if job is None:
            return None

        job.status = JobStatus.RUNNING
        job.attempt_count += 1
        job.lease_owner = worker_id
        job.lease_expires_at = observed_at + timedelta(seconds=lease_seconds)
        job.heartbeat_at = observed_at
        job.started_at = observed_at
        job.finished_at = None
        job.progress = 0
        job.progress_message = None
        job.error_class = None
        job.error_code = None
        job.error_message = None
        await self._append_event(
            job_id=job.id,
            event_type="job.claimed",
            actor=worker_id,
            event_data={
                "worker_id": worker_id,
                "attempt_count": job.attempt_count,
                "lease_expires_at": job.lease_expires_at.isoformat(),
            },
        )
        await self.session.flush()
        return job

    async def heartbeat_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        lease_seconds: int,
        progress: int | None = None,
        progress_message: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        observed_at = _now(now)
        job = await self._locked_job(job_id)
        if job is None or not self._has_active_lease(job, worker_id=worker_id, now=observed_at):
            return False

        job.heartbeat_at = observed_at
        job.lease_expires_at = observed_at + timedelta(seconds=lease_seconds)
        if progress is not None:
            job.progress = progress
        if progress_message is not None:
            job.progress_message = str(redact_secrets(progress_message))
        await self._append_event(
            job_id=job.id,
            event_type="job.heartbeat",
            actor=worker_id,
            event_data={
                "worker_id": worker_id,
                "progress": job.progress,
                "progress_message": job.progress_message,
            },
        )
        await self.session.flush()
        return True

    async def checkpoint_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None:
        """Persist handler checkpoints without exposing a WorkflowJob instance."""

        if payload is None and result is None:
            raise ValueError("a job checkpoint requires payload or result")
        observed_at = _now(now)
        job = await self._locked_job(job_id)
        if job is None or not self._has_active_lease(job, worker_id=worker_id, now=observed_at):
            raise self._invalid(job_id, action="checkpoint", job=job)
        if payload is not None:
            safe_payload = _redact_job_payload(job.job_type, payload)
            if safe_payload != payload:
                raise ValueError("job checkpoint payload contains a secret value")
            job.payload = safe_payload
        if result is not None:
            safe_result = redact_secrets(result)
            if not isinstance(safe_result, dict):  # pragma: no cover - dict input contract
                raise TypeError("job checkpoint result must be a mapping")
            job.result = safe_result
        await self.session.flush()

    async def finish_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        result: dict[str, Any],
        now: datetime | None = None,
    ) -> WorkflowJob:
        observed_at = _now(now)
        job = await self._locked_job(job_id)
        if job is None or not self._has_active_lease(job, worker_id=worker_id, now=observed_at):
            raise self._invalid(job_id, action="finish", job=job)

        job.status = JobStatus.SUCCEEDED
        safe_result = redact_secrets(result)
        if not isinstance(safe_result, dict):  # pragma: no cover - dict input contract
            raise TypeError("job result must remain a dictionary")
        job.result = safe_result
        job.progress = 100
        job.finished_at = observed_at
        self._clear_lease(job)
        await self._append_event(
            job_id=job.id,
            event_type="job.succeeded",
            actor=worker_id,
            event_data={"result": safe_result},
        )
        await self.session.flush()
        return job

    async def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_class: JobErrorClass,
        error_code: str,
        error_message: str,
        retry_at: datetime | None = None,
        now: datetime | None = None,
    ) -> WorkflowJob:
        observed_at = _now(now)
        retention_run = await self._locked_retention_run(job_id)
        job = await self._locked_job(job_id)
        if job is None or not self._has_active_lease(job, worker_id=worker_id, now=observed_at):
            raise self._invalid(job_id, action="fail", job=job)

        error_class_value = _enum_value(error_class)
        job.error_class = error_class_value
        safe_error_code = str(redact_secrets(error_code))
        safe_error_message = str(redact_secrets(error_message))
        job.error_code = safe_error_code
        job.error_message = safe_error_message
        self._clear_lease(job)
        event_data = {
            "error_class": error_class_value,
            "error_code": safe_error_code,
            "error_message": safe_error_message,
        }

        if error_class == JobErrorClass.RETRYABLE and job.attempt_count < job.max_attempts:
            effective_retry_at = retry_at if retry_at is not None else observed_at
            job.status = JobStatus.QUEUED
            job.scheduled_for = effective_retry_at
            job.finished_at = None
            event_type = "job.retry_scheduled"
            event_data["retry_at"] = effective_retry_at.isoformat()
        elif error_class == JobErrorClass.NEEDS_REVIEW:
            job.status = JobStatus.NEEDS_REVIEW
            job.finished_at = observed_at
            event_type = "job.needs_review"
        else:
            job.status = JobStatus.FAILED
            job.finished_at = observed_at
            event_type = "job.failed"

        if job.status in {JobStatus.FAILED, JobStatus.NEEDS_REVIEW}:
            self._sync_retention_terminal(
                retention_run,
                job_status=JobStatus(job.status),
                observed_at=observed_at,
            )

        await self._append_event(
            job_id=job.id,
            event_type=event_type,
            actor=worker_id,
            event_data=event_data,
        )
        await self.session.flush()
        return job

    async def retry_job(self, *, job_id: UUID, now: datetime | None = None) -> WorkflowJob:
        retention_run = await self._locked_retention_run(job_id)
        job = await self._locked_job(job_id)
        if job is None or job.status not in (JobStatus.FAILED, JobStatus.NEEDS_REVIEW):
            raise self._invalid(job_id, action="retry", job=job)

        await require_available_job_type(self.session, str(job.job_type))

        previous_status = str(job.status)
        observed_at = _now(now)
        job.status = JobStatus.QUEUED
        job.origin = JobOrigin.RETRY
        job.scheduled_for = observed_at
        job.finished_at = None
        job.started_at = None
        job.progress = 0
        job.progress_message = None
        job.error_class = None
        job.error_code = None
        job.error_message = None
        self._clear_lease(job)
        self._sync_retention_retry(retention_run, observed_at=observed_at)
        await self._append_event(
            job_id=job.id,
            event_type="job.retried",
            actor="operator",
            event_data={"previous_status": previous_status},
        )
        await self.session.flush()
        return job

    async def cancel_job(self, *, job_id: UUID, now: datetime | None = None) -> WorkflowJob:
        retention_run = await self._locked_retention_run(job_id)
        job = await self._locked_job(job_id)
        if job is None or job.status != JobStatus.QUEUED:
            raise self._invalid(job_id, action="cancel", job=job)

        job.status = JobStatus.CANCELLED
        observed_at = _now(now)
        job.finished_at = observed_at
        self._sync_retention_terminal(
            retention_run,
            job_status=JobStatus.CANCELLED,
            observed_at=observed_at,
        )
        await self._append_event(
            job_id=job.id,
            event_type="job.cancelled",
            actor="operator",
            event_data={},
        )
        await self.session.flush()
        return job

    async def requeue_expired_leases(self, *, now: datetime | None = None) -> int:
        observed_at = _now(now)
        candidates = await self.session.execute(
            select(
                WorkflowJob.id,
                WorkflowJob.payload,
                WorkflowJob.attempt_count,
                WorkflowJob.max_attempts,
            )
            .where(
                WorkflowJob.status == JobStatus.RUNNING,
                WorkflowJob.lease_expires_at.is_not(None),
                WorkflowJob.lease_expires_at <= observed_at,
            )
            .order_by(WorkflowJob.lease_expires_at, WorkflowJob.created_at)
        )
        processed = 0
        for candidate in candidates:
            dependents = await self._lock_expired_lease_dependents(
                job_id=candidate.id,
                payload=dict(candidate.payload or {}),
            )
            job = await self._locked_expired_job(candidate.id)
            if (
                job is None
                or job.status != JobStatus.RUNNING
                or job.lease_expires_at is None
                or job.lease_expires_at > observed_at
            ):
                continue
            previous_owner = job.lease_owner
            expired_at = job.lease_expires_at
            exhausted = job.attempt_count >= job.max_attempts
            requires_review = self._sync_expired_publish_ambiguity(
                dependents,
                observed_at=observed_at,
            )
            terminal_event_type = "job.failed"
            if requires_review:
                job.finished_at = observed_at
                job.status = JobStatus.NEEDS_REVIEW
                job.error_class = JobErrorClass.NEEDS_REVIEW
                job.error_code = "telegram_publish_ambiguous"
                job.error_message = "Telegram publish outcome is ambiguous after worker interruption"
                terminal_event_type = "job.needs_review"
                self._sync_retention_terminal(
                    dependents.retention_run,
                    job_status=JobStatus(job.status),
                    observed_at=observed_at,
                )
            elif exhausted:
                self._sync_terminal_expired_lease_dependents(
                    dependents,
                    observed_at=observed_at,
                )
                job.finished_at = observed_at
                job.status = JobStatus.FAILED
                job.error_class = JobErrorClass.RETRYABLE
                job.error_code = "worker_lease_expired"
                job.error_message = "Worker lease expired after the final configured attempt"
                self._sync_retention_terminal(
                    dependents.retention_run,
                    job_status=JobStatus.FAILED,
                    observed_at=observed_at,
                )
            else:
                job.status = JobStatus.QUEUED
                job.scheduled_for = observed_at
            self._clear_lease(job)
            await self._append_event(
                job_id=job.id,
                event_type="job.lease_expired",
                actor="system",
                event_data={
                    "lease_owner": previous_owner,
                    "lease_expired_at": expired_at.isoformat() if expired_at is not None else None,
                },
            )
            if exhausted or requires_review:
                await self._append_event(
                    job_id=job.id,
                    event_type=terminal_event_type,
                    actor="system",
                    event_data={
                        "error_class": job.error_class,
                        "error_code": job.error_code,
                        "error_message": job.error_message,
                        "attempt_count": job.attempt_count,
                        "max_attempts": job.max_attempts,
                    },
                )
            processed += 1
        await self.session.flush()
        return processed

    async def get_job(self, job_id: UUID) -> WorkflowJob | None:
        return await self.session.get(WorkflowJob, job_id)

    async def list_jobs(
        self,
        *,
        statuses: tuple[JobStatus, ...] = (),
        job_type: str | None = None,
        error_class: JobErrorClass | None = None,
        limit: int = 100,
    ) -> list[WorkflowJob]:
        statement = select(WorkflowJob)
        if statuses:
            statement = statement.where(WorkflowJob.status.in_(statuses))
        if job_type is not None:
            statement = statement.where(WorkflowJob.job_type == job_type)
        if error_class is not None:
            statement = statement.where(WorkflowJob.error_class == error_class)
        statement = statement.order_by(WorkflowJob.updated_at.desc(), WorkflowJob.created_at.desc()).limit(limit)
        return list(await self.session.scalars(statement))

    @staticmethod
    def _clear_lease(job: WorkflowJob) -> None:
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None

    @staticmethod
    def _has_active_lease(job: WorkflowJob, *, worker_id: str, now: datetime) -> bool:
        return (
            job.status == JobStatus.RUNNING
            and job.lease_owner == worker_id
            and job.lease_expires_at is not None
            and job.lease_expires_at > now
        )
