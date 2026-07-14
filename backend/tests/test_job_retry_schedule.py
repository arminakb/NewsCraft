from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.jobs.models import WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus

NOW = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)


async def test_retryable_failure_without_explicit_retry_time_uses_observed_time():
    job = WorkflowJob(
        id=uuid4(),
        job_type="ingest.collect",
        status=JobStatus.RUNNING,
        payload={},
        result={},
        priority=0,
        idempotency_key="retry-without-explicit-time",
        origin=JobOrigin.AUTOMATION,
        pause_sensitive=True,
        scheduled_for=NOW,
        attempt_count=1,
        max_attempts=3,
        lease_owner="worker-1",
        lease_expires_at=NOW + timedelta(minutes=2),
        heartbeat_at=NOW,
        progress=10,
        created_at=NOW - timedelta(minutes=1),
        updated_at=NOW,
    )
    observed_at = NOW + timedelta(minutes=1)
    repository = LockedJobRepository(FakeSession(), job)

    failed = await repository.fail_job(
        job_id=job.id,
        worker_id="worker-1",
        error_class=JobErrorClass.RETRYABLE,
        error_code="temporary_failure",
        error_message="try again",
        now=observed_at,
    )

    assert failed.status == JobStatus.QUEUED
    assert failed.scheduled_for == observed_at
    assert repository.events[0]["event_data"]["retry_at"] == observed_at.isoformat()


class FakeSession:
    def __init__(self):
        self.flushed = False

    async def flush(self):
        self.flushed = True


class LockedJobRepository(JobRepository):
    def __init__(self, session, job):
        super().__init__(session)
        self.job = job
        self.events = []

    async def _locked_job(self, job_id):
        return self.job if self.job.id == job_id else None

    async def _locked_retention_run(self, job_id):
        return None

    async def _append_event(self, **event):
        self.events.append(event)
