from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus
from app.operations.diagnostics import _job_attention
from app.research.schemas import ResearchBudget
from app.retention.handlers import RetentionJobPayload

NOW = datetime(2026, 7, 13, 9, 0, tzinfo=UTC)


class _InsertResult:
    def __init__(self, job_id: UUID) -> None:
        self.job_id = job_id

    def scalar_one_or_none(self) -> UUID:
        return self.job_id


class _JobSession:
    def __init__(self, job: WorkflowJob | None = None) -> None:
        self.job = job
        self.added: list[object] = []
        self.insert_values: dict[str, object] | None = None

    async def execute(self, statement):
        values = dict(statement.compile().params)
        self.insert_values = values
        job_id = uuid4()
        self.job = WorkflowJob(
            id=job_id,
            job_type=values["job_type"],
            status=JobStatus.QUEUED,
            payload=values["payload"],
            result={},
            priority=values["priority"],
            idempotency_key=values["idempotency_key"],
            origin=values["origin"],
            pause_sensitive=values["pause_sensitive"],
            attempt_count=0,
            max_attempts=values["max_attempts"],
            scheduled_for=values["scheduled_for"],
            progress=0,
        )
        return _InsertResult(job_id)

    async def get(self, _model, _identity):
        return self.job

    async def scalar(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if "FROM retention_runs" in sql:
            return None
        return self.job

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


def _running_job() -> WorkflowJob:
    return WorkflowJob(
        id=uuid4(),
        job_type="secret-boundary",
        status=JobStatus.RUNNING,
        payload={},
        result={},
        priority=0,
        idempotency_key=str(uuid4()),
        origin=JobOrigin.AUTOMATION,
        pause_sensitive=True,
        attempt_count=1,
        max_attempts=3,
        lease_owner="worker",
        lease_expires_at=NOW + timedelta(minutes=1),
        progress=0,
    )


def _events(session: _JobSession) -> list[WorkflowEvent]:
    return [item for item in session.added if isinstance(item, WorkflowEvent)]


async def test_enqueue_redacts_nested_payload_without_mutating_caller_input():
    payload = {
        "safe": "visible",
        "metadata": {"api_key": "payload-canary"},
    }
    session = _JobSession()

    result = await JobRepository(session).enqueue_job(
        job_type="secret-boundary",
        payload=payload,
        idempotency_key="secret-boundary-enqueue",
        origin=JobOrigin.MANUAL,
        scheduled_for=NOW,
    )

    assert result.job.payload == {
        "safe": "visible",
        "metadata": {"api_key": "[REDACTED]"},
    }
    assert session.insert_values is not None
    assert session.insert_values["payload"] == result.job.payload
    assert payload["metadata"]["api_key"] == "payload-canary"


async def test_enqueue_preserves_validated_retention_preview_token_for_handler():
    preview_token = "a" * 64
    run_id = uuid4()
    payload = {
        "run_id": str(run_id),
        "preview_token": preview_token,
        "metadata": {"api_key": "retention-payload-canary"},
    }
    session = _JobSession()

    result = await JobRepository(session).enqueue_job(
        job_type="execute_retention",
        payload=payload,
        idempotency_key="retention-payload-boundary",
        origin=JobOrigin.MANUAL,
        scheduled_for=NOW,
    )

    validated = RetentionJobPayload.model_validate(
        {
            "run_id": result.job.payload["run_id"],
            "preview_token": result.job.payload["preview_token"],
        }
    )
    assert validated.run_id == run_id
    assert validated.preview_token == preview_token
    assert result.job.payload["metadata"] == {"api_key": "[REDACTED]"}


async def test_enqueue_does_not_exempt_unvalidated_retention_preview_token():
    session = _JobSession()

    result = await JobRepository(session).enqueue_job(
        job_type="execute_retention",
        payload={"run_id": str(uuid4()), "preview_token": "Bearer malformed-preview-canary"},
        idempotency_key="malformed-retention-payload-boundary",
        origin=JobOrigin.MANUAL,
        scheduled_for=NOW,
    )

    assert result.job.payload["preview_token"] == "[REDACTED]"


async def test_enqueue_preserves_research_token_counts_for_handler_validation():
    budget = ResearchBudget(max_input_tokens=75_000, max_output_tokens=15_000)
    payload = {
        "budget": budget.model_dump(mode="json"),
        "metadata": {"access_token": "research-payload-canary"},
    }
    session = _JobSession()

    result = await JobRepository(session).enqueue_job(
        job_type="research_story",
        payload=payload,
        idempotency_key="research-payload-boundary",
        origin=JobOrigin.MANUAL,
        scheduled_for=NOW,
    )

    assert ResearchBudget.model_validate(result.job.payload["budget"]) == budget
    assert result.job.payload["metadata"] == {"access_token": "[REDACTED]"}


async def test_heartbeat_redacts_progress_message_in_job_and_event():
    job = _running_job()
    session = _JobSession(job)

    updated = await JobRepository(session).heartbeat_job(
        job_id=job.id,
        worker_id="worker",
        lease_seconds=60,
        progress=25,
        progress_message="Authorization: Bearer progress-canary",
        now=NOW,
    )

    assert updated is True
    assert "progress-canary" not in job.progress_message
    assert "progress-canary" not in str(_events(session)[0].event_data)
    assert "[REDACTED]" in job.progress_message


async def test_result_errors_and_event_data_are_redacted_without_mutating_inputs():
    result = {"safe": "visible", "metadata": {"api_key": "result-canary"}}
    succeeded = _running_job()
    success_session = _JobSession(succeeded)

    await JobRepository(success_session).finish_job(
        job_id=succeeded.id,
        worker_id="worker",
        result=result,
        now=NOW,
    )

    assert succeeded.result["metadata"]["api_key"] == "[REDACTED]"
    assert "result-canary" not in str(_events(success_session)[0].event_data)
    assert result["metadata"]["api_key"] == "result-canary"

    failed = _running_job()
    failure_session = _JobSession(failed)
    await JobRepository(failure_session).fail_job(
        job_id=failed.id,
        worker_id="worker",
        error_class=JobErrorClass.PERMANENT,
        error_code="token=error-code-canary",
        error_message="Bearer error-message-canary",
        now=NOW,
    )

    persisted = f"{failed.error_code} {failed.error_message} {_events(failure_session)[0].event_data}"
    assert "error-code-canary" not in persisted
    assert "error-message-canary" not in persisted
    assert "[REDACTED]" in persisted


def test_diagnostics_redacts_structured_metadata_before_rendering_attention_title():
    job = SimpleNamespace(
        id=uuid4(),
        job_type="generation",
        status=JobStatus.FAILED,
        error_message={
            "provider": "openrouter",
            "metadata": {"api_key": "diagnostics-canary"},
        },
        error_code=None,
        updated_at=NOW,
    )

    attention = _job_attention(job)

    assert "diagnostics-canary" not in attention.title
    assert "[REDACTED]" in attention.title
    assert "openrouter" in attention.title
