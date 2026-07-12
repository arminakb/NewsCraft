from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact_secrets
from app.jobs.errors import InvalidJobTransition
from app.jobs.events import redact_event_data
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus


@dataclass(frozen=True, slots=True)
class EnqueueJobResult:
    job: WorkflowJob
    created: bool


def _now(value: datetime | None) -> datetime:
    return value if value is not None else datetime.now(UTC)


def _enum_value(value: str | JobStatus | JobErrorClass | JobOrigin) -> str:
    return value.value if hasattr(value, "value") else str(value)


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
        return await self.session.scalar(
            select(WorkflowJob).where(WorkflowJob.id == job_id).with_for_update()
        )

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
    ) -> EnqueueJobResult:
        effective_scheduled_for = _now(scheduled_for)
        statement = (
            insert(WorkflowJob)
            .values(
                job_type=job_type,
                payload=payload,
                idempotency_key=idempotency_key,
                origin=_enum_value(origin),
                priority=priority,
                scheduled_for=effective_scheduled_for,
                max_attempts=max_attempts,
                pause_sensitive=pause_sensitive,
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

        job = await self.session.scalar(
            select(WorkflowJob).where(WorkflowJob.idempotency_key == idempotency_key)
        )
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
            await self.session.scalar(
                select(AutomationControl.global_pause).where(AutomationControl.id == "global")
            )
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
            job.progress_message = progress_message
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

        await self._append_event(
            job_id=job.id,
            event_type=event_type,
            actor=worker_id,
            event_data=event_data,
        )
        await self.session.flush()
        return job

    async def retry_job(self, *, job_id: UUID, now: datetime | None = None) -> WorkflowJob:
        job = await self._locked_job(job_id)
        if job is None or job.status not in (JobStatus.FAILED, JobStatus.NEEDS_REVIEW):
            raise self._invalid(job_id, action="retry", job=job)

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
        await self._append_event(
            job_id=job.id,
            event_type="job.retried",
            actor="operator",
            event_data={"previous_status": previous_status},
        )
        await self.session.flush()
        return job

    async def cancel_job(self, *, job_id: UUID, now: datetime | None = None) -> WorkflowJob:
        job = await self._locked_job(job_id)
        if job is None or job.status != JobStatus.QUEUED:
            raise self._invalid(job_id, action="cancel", job=job)

        job.status = JobStatus.CANCELLED
        job.finished_at = _now(now)
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
        jobs = list(
            await self.session.scalars(
                select(WorkflowJob)
                .where(
                    WorkflowJob.status == JobStatus.RUNNING,
                    WorkflowJob.lease_expires_at.is_not(None),
                    WorkflowJob.lease_expires_at <= observed_at,
                )
                .order_by(WorkflowJob.lease_expires_at, WorkflowJob.created_at)
                .with_for_update(skip_locked=True)
            )
        )
        for job in jobs:
            previous_owner = job.lease_owner
            expired_at = job.lease_expires_at
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
        await self.session.flush()
        return len(jobs)

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
