from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.faults import FaultInjector
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin, JobStatus
from app.retention.contracts import (
    RETENTION_CONFIRMATION,
    RETENTION_PREVIEW_TTL,
    RetentionCandidate,
    RetentionCategory,
    RetentionConfirmationError,
    RetentionConflict,
    RetentionCountSnapshot,
    RetentionEnqueueResult,
    RetentionExecutionPlan,
    RetentionNotFound,
    RetentionOperation,
    RetentionPolicyInput,
    RetentionPreview,
    RetentionRecordType,
    build_preview_token,
    policy_input,
    preview_from_run,
    snapshot_candidates,
    summarize_candidates,
)
from app.retention.database import RetentionDatabaseExecutor
from app.retention.filesystem import (
    finish_filesystem_phase as execute_filesystem_cleanup,
)
from app.retention.models import (
    RETENTION_POLICY_ID,
    RETENTION_SCHEMA_REVISION,
    RetentionPolicy,
    RetentionRun,
)
from app.retention.planning import RetentionPlanner

_TERMINAL_JOB_STATUSES = frozenset(
    {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.NEEDS_REVIEW,
    }
)

__all__ = [
    "RETENTION_CONFIRMATION",
    "RetentionCandidate",
    "RetentionCategory",
    "RetentionConfirmationError",
    "RetentionConflict",
    "RetentionNotFound",
    "RetentionOperation",
    "RetentionPolicyInput",
    "RetentionRecordType",
    "RetentionService",
    "build_preview_token",
    "summarize_candidates",
]


class RetentionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] | None = None,
        media_root: Path | None = None,
    ) -> None:
        self.session = session
        self.clock = clock or (lambda: datetime.now(UTC))
        if media_root is None:
            from app.core.config import settings

            media_root = Path(settings.media_root)
        self.media_root = Path(media_root)
        self.planner = RetentionPlanner(session, self.media_root)
        self.database = RetentionDatabaseExecutor(
            session,
            media_root=self.media_root,
            now=self._now,
            collect_candidates=lambda *args, **kwargs: self._collect_candidates(*args, **kwargs),
        )

    def _now(self) -> datetime:
        observed_at = self.clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("retention clock must return a timezone-aware timestamp")
        return observed_at

    async def get_policy(self) -> RetentionPolicy:
        policy = await self.session.get(RetentionPolicy, RETENTION_POLICY_ID)
        if policy is not None:
            return policy
        defaults = RetentionPolicyInput()
        await self.session.execute(
            insert(RetentionPolicy)
            .values(id=RETENTION_POLICY_ID, **defaults.model_dump())
            .on_conflict_do_nothing(index_elements=["id"])
        )
        policy = await self.session.get(RetentionPolicy, RETENTION_POLICY_ID)
        if policy is None:  # pragma: no cover - the singleton insert is authoritative
            raise RuntimeError("retention policy could not be initialized")
        return policy

    async def update_policy(self, value: RetentionPolicyInput) -> RetentionPolicy:
        policy = await self.session.scalar(
            select(RetentionPolicy).where(RetentionPolicy.id == RETENTION_POLICY_ID).with_for_update()
        )
        if policy is None:
            policy = RetentionPolicy(id=RETENTION_POLICY_ID)
            self.session.add(policy)
        for field, field_value in value.model_dump().items():
            setattr(policy, field, field_value)
        await self.session.flush()
        return policy

    async def list_runs(self, limit: int = 50) -> list[RetentionRun]:
        if not 1 <= limit <= 250:
            raise ValueError("retention run limit must be between 1 and 250")
        return list(
            await self.session.scalars(
                select(RetentionRun).order_by(RetentionRun.created_at.desc(), RetentionRun.id.desc()).limit(limit)
            )
        )

    async def get_run(self, run_id: UUID) -> RetentionRun:
        run = await self.session.get(RetentionRun, run_id)
        if run is None:
            raise RetentionNotFound(f"retention run {run_id} was not found")
        return run

    async def _referenced_media_ids(self) -> set[UUID]:
        return await self.planner.referenced_media_ids()

    async def _collect_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None = None,
        lock: bool = False,
        media_root: Path | None = None,
    ) -> list[RetentionCandidate]:
        return await self.planner.collect_candidates(
            policy,
            now=now,
            only=only,
            lock=lock,
            media_root=media_root,
        )

    async def preview(self, policy: RetentionPolicyInput | None = None) -> RetentionPreview:
        observed_at = self._now()
        effective_policy = policy or policy_input(await self.get_policy())
        candidates = await self._collect_candidates(effective_policy, now=observed_at)
        token = build_preview_token(
            effective_policy,
            candidates,
            schema_revision=RETENTION_SCHEMA_REVISION,
        )
        snapshot = [candidate.model_dump(mode="json") for candidate in candidates]
        counts = {
            category: summary.model_dump(mode="json") for category, summary in summarize_candidates(candidates).items()
        }
        run_id = uuid4()
        inserted_id = (
            await self.session.execute(
                insert(RetentionRun)
                .values(
                    id=run_id,
                    status="previewed",
                    preview_token=token,
                    schema_revision=RETENTION_SCHEMA_REVISION,
                    policy_snapshot=effective_policy.model_dump(mode="json"),
                    candidate_snapshot=snapshot,
                    cleanup_intent_snapshot=[],
                    count_snapshot=counts,
                    error_snapshot=[],
                    previewed_at=observed_at,
                    preview_expires_at=observed_at + RETENTION_PREVIEW_TTL,
                )
                .on_conflict_do_nothing(index_elements=["preview_token"])
                .returning(RetentionRun.id)
            )
        ).scalar_one_or_none()
        if inserted_id is not None:
            run = await self.session.get(RetentionRun, inserted_id)
            if run is None:  # pragma: no cover - RETURNING guarantees the row
                raise RuntimeError("retention preview could not be loaded")
            return preview_from_run(run)
        existing = await self.session.scalar(
            select(RetentionRun).where(RetentionRun.preview_token == token).with_for_update()
        )
        if existing is None:  # pragma: no cover - conflict target guarantees a row
            raise RuntimeError("idempotent retention preview could not be loaded")
        if existing.status in {"previewed", "expired"} and existing.workflow_job_id is None:
            existing.status = "previewed"
            existing.policy_snapshot = effective_policy.model_dump(mode="json")
            existing.candidate_snapshot = snapshot
            existing.count_snapshot = counts
            existing.error_snapshot = []
            existing.previewed_at = observed_at
            existing.preview_expires_at = observed_at + RETENTION_PREVIEW_TTL
            await self.session.flush()
        return preview_from_run(existing)

    async def enqueue(
        self,
        *,
        preview_token: str,
        confirmation: str,
    ) -> RetentionEnqueueResult:
        if confirmation != RETENTION_CONFIRMATION:
            raise RetentionConfirmationError(f"confirmation must exactly match {RETENTION_CONFIRMATION!r}")
        run = await self.session.scalar(
            select(RetentionRun).where(RetentionRun.preview_token == preview_token).with_for_update()
        )
        if run is None:
            raise RetentionConflict("preview token does not match a persisted preview")
        if run.schema_revision != RETENTION_SCHEMA_REVISION:
            raise RetentionConflict("preview schema revision is no longer executable")
        candidates = snapshot_candidates(run)
        policy = RetentionPolicyInput.model_validate(run.policy_snapshot)
        expected_token = build_preview_token(
            policy,
            candidates,
            schema_revision=run.schema_revision,
        )
        if expected_token != preview_token:
            raise RetentionConflict("preview token does not match its server snapshot")
        if run.workflow_job_id is not None:
            job = await self.session.scalar(
                select(WorkflowJob).where(WorkflowJob.id == run.workflow_job_id).with_for_update()
            )
            if job is None:  # pragma: no cover - protected by the retention FK
                raise RetentionConflict("retention workflow job is unavailable")
            if str(job.status) in {
                JobStatus.QUEUED,
                JobStatus.FAILED,
                JobStatus.NEEDS_REVIEW,
                JobStatus.CANCELLED,
                JobStatus.SUCCEEDED,
            } and await self._reset_all_skipped_database_run(run):
                observed_at = self._now()
                job.status = JobStatus.QUEUED
                job.scheduled_for = observed_at
                job.attempt_count = 0
                job.started_at = None
                job.finished_at = None
                job.lease_owner = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.progress = 0
                job.progress_message = None
                job.error_class = None
                job.error_code = None
                job.error_message = None
                job.result = {}
                self.session.add(
                    WorkflowEvent(
                        workflow_job_id=job.id,
                        event_type="job.requeued",
                        actor=JobOrigin.MANUAL,
                        event_data={"reason": "retention_all_database_candidates_reconfirmed"},
                    )
                )
                run.status = "queued"
                run.started_at = None
                run.finished_at = None
                run.queued_at = observed_at
                run.cleanup_intent_snapshot = []
                run.count_snapshot = {
                    category: summary.model_dump(mode="json")
                    for category, summary in summarize_candidates(candidates).items()
                }
                run.error_snapshot = []
                await self.session.flush()
                return RetentionEnqueueResult(run=run, job=job, created=False)
            revivable_before_database = run.started_at is None and run.status in {
                "queued",
                "failed",
            }
            revivable_cleanup = run.started_at is not None and run.status in {
                "running",
                "partial",
            }
            if str(job.status) == JobStatus.CANCELLED and (revivable_before_database or revivable_cleanup):
                observed_at = self._now()
                job.status = JobStatus.QUEUED
                job.scheduled_for = observed_at
                job.finished_at = None
                job.lease_owner = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.progress = 0
                job.progress_message = None
                job.error_class = None
                job.error_code = None
                job.error_message = None
                self.session.add(
                    WorkflowEvent(
                        workflow_job_id=job.id,
                        event_type="job.requeued",
                        actor=JobOrigin.MANUAL,
                        event_data={"reason": "retention_reconfirmed"},
                    )
                )
                if revivable_before_database:
                    run.status = "queued"
                    run.finished_at = None
                run.queued_at = observed_at
                run.error_snapshot = [
                    error
                    for error in run.error_snapshot
                    if error.get("phase") != "workflow" and error.get("code") != "retention_job_terminal"
                ]
                await self.session.flush()
                return RetentionEnqueueResult(run=run, job=job, created=False)
            if str(job.status) in {JobStatus.FAILED, JobStatus.CANCELLED} and run.status in {
                "queued",
                "running",
            }:
                observed_at = self._now()
                run.status = "failed"
                run.finished_at = observed_at
                run.error_snapshot = [
                    *run.error_snapshot,
                    {
                        "phase": "queue",
                        "code": "retention_job_terminal",
                        "message": "The linked retention workflow job became terminal before completion",
                    },
                ]
                await self.session.flush()
                return RetentionEnqueueResult(run=run, job=job, created=False)
            if str(job.status) in _TERMINAL_JOB_STATUSES and run.status != "succeeded":
                # No branch above could requeue anything and the linked job will
                # never run again: answering 202 + deduplicated here would promise
                # work that nothing is going to perform.
                raise RetentionConflict(
                    f"retention run cannot be re-enqueued from status {run.status!r} "
                    f"with a terminal workflow job in status {str(job.status)!r}"
                )
            return RetentionEnqueueResult(run=run, job=job, created=False)
        observed_at = self._now()
        if run.status != "previewed":
            raise RetentionConflict(f"retention preview cannot be queued from status {run.status!r}")
        if run.preview_expires_at <= observed_at:
            run.status = "expired"
            await self.session.flush()
            raise RetentionConflict("retention preview has expired; create a new preview")
        result = await JobRepository(self.session).enqueue_job(
            job_type="execute_retention",
            payload={"run_id": str(run.id), "preview_token": preview_token},
            idempotency_key=f"retention:{preview_token}",
            origin=JobOrigin.MANUAL,
            pause_sensitive=True,
        )
        run.workflow_job_id = result.job.id
        run.status = "queued"
        run.queued_at = observed_at
        await self.session.flush()
        return RetentionEnqueueResult(run=run, job=result.job, created=result.created)

    async def _reset_all_skipped_database_run(self, run: RetentionRun) -> bool:
        return await self.database.reset_all_skipped_database_run(run)

    @staticmethod
    def _execution_counts(run: RetentionRun) -> RetentionCountSnapshot:
        return RetentionDatabaseExecutor.execution_counts(run)

    async def execute_db_phase(
        self,
        run_id: UUID,
        preview_token: str,
        *,
        export_root: Path,
        media_root: Path,
    ) -> RetentionExecutionPlan:
        return await self.database.execute_db_phase(
            run_id,
            preview_token,
            export_root=export_root,
            media_root=media_root,
        )

    async def finish_filesystem_phase(
        self,
        run_id: UUID,
        *,
        export_root: Path,
        media_root: Path,
        fault_injector: FaultInjector | None = None,
    ) -> RetentionRun:
        return await execute_filesystem_cleanup(
            self.session,
            run_id,
            export_root=export_root,
            media_root=media_root,
            now=self._now,
            execution_counts=self._execution_counts,
            referenced_media_ids=self._referenced_media_ids,
            fault_injector=fault_injector,
        )
