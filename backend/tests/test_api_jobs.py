from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import attributes

from app.db.session import get_session
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus
from app.main import app

NOW = datetime(2026, 7, 12, 8, 30, tzinfo=UTC)


async def test_job_list_applies_repeated_status_type_error_and_limit_filters():
    job = _job(status=JobStatus.FAILED, error_class=JobErrorClass.PERMANENT)
    session = FakeJobApiSession(jobs=[job])

    response = await _request(
        "GET",
        "/jobs?status=queued&status=failed&job_type=ingest.collect&error_class=permanent&limit=17",
        session,
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(job.id)
    assert session.list_filters == {
        "statuses": {"queued", "failed"},
        "job_type": "ingest.collect",
        "error_class": "permanent",
        "limit": 17,
    }


async def test_job_list_redacts_legacy_progress_and_error_fields_at_emission():
    job = _job(status=JobStatus.FAILED, error_class=JobErrorClass.PERMANENT)
    job.progress_message = 'progress {"authorization":"Bearer job-progress-canary"}'
    job.error_code = "failure_api_key=job-code-canary"
    job.error_message = 'failure {"password":"job-message-canary"}'

    response = await _request("GET", "/jobs", FakeJobApiSession(jobs=[job]))

    assert response.status_code == 200
    emitted = response.json()["items"][0]
    serialized = str(emitted)
    assert "job-progress-canary" not in serialized
    assert "job-code-canary" not in serialized
    assert "job-message-canary" not in serialized
    assert "[REDACTED]" in emitted["progress_message"]
    assert emitted["error_code"] == "failure_api_key=[REDACTED]"
    assert "[REDACTED]" in emitted["error_message"]


async def test_job_summary_returns_operational_counts():
    session = FakeJobApiSession(summary_counts=[7, 2, 3, 11])

    response = await _request("GET", "/jobs/summary", session)

    assert response.status_code == 200
    assert response.json() == {
        "queued": 7,
        "running": 2,
        "attention": 3,
        "succeeded_today": 11,
    }
    sql = "\n".join(session.summary_sql)
    assert "workflow_jobs.status" in sql
    assert "workflow_jobs.finished_at" in sql


async def test_job_detail_sanitizes_payload_result_and_newest_first_events():
    job = _job(
        payload={"platforms": ["rss"], "nested": {"api-key": "payload-secret"}},
        result={
            "items": 4,
            "Authorization": "result-secret",
            "_regeneration_fence": {
                "variant_id": str(uuid4()),
                "lease_owner": "worker-private",
            },
        },
        lease_owner="worker-private",
    )
    older = _event(job.id, "job.enqueued", NOW - timedelta(minutes=2), {"token": "older-secret"})
    newer = _event(job.id, "job.failed", NOW - timedelta(minutes=1), {"error": {"password": "newer-secret"}})
    session = FakeJobApiSession(item=job, events=[newer, older])

    response = await _request("GET", f"/jobs/{job.id}", session)

    assert response.status_code == 200
    payload = response.json()
    assert "lease_owner" not in payload
    assert "lease_expires_at" not in payload
    assert "heartbeat_at" not in payload
    assert payload["payload"]["nested"]["api-key"] == "[REDACTED]"
    assert payload["result"]["Authorization"] == "[REDACTED]"
    assert "_regeneration_fence" not in payload["result"]
    assert [event["event_type"] for event in payload["events"]] == ["job.failed", "job.enqueued"]
    assert payload["events"][0]["event_data"]["error"]["password"] == "[REDACTED]"
    assert payload["events"][1]["event_data"]["token"] == "[REDACTED]"
    assert "ORDER BY workflow_events.created_at DESC" in session.event_sql


async def test_job_detail_returns_404_for_missing_job():
    response = await _request("GET", f"/jobs/{uuid4()}", FakeJobApiSession())

    assert response.status_code == 404
    assert response.json() == {"detail": "job not found"}


async def test_retry_failed_job_returns_updated_job_and_commits():
    job = _job(status=JobStatus.FAILED, error_class=JobErrorClass.PERMANENT)
    session = TransitionResponseSession(item=job)

    response = await _request("POST", f"/jobs/{job.id}/retry", session)

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    # Retry keeps the job's provenance: rewriting a pause-exempt manual job to
    # origin "retry" made it unclaimable under a global pause.
    assert response.json()["origin"] == "manual"
    assert session.committed is True
    assert session.trace == ["flush", "refresh", "commit"]


async def test_retry_queued_job_returns_409_without_commit():
    job = _job(status=JobStatus.QUEUED)
    session = FakeJobApiSession(item=job)

    response = await _request("POST", f"/jobs/{job.id}/retry", session)

    assert response.status_code == 409
    assert response.json()["detail"] == f"Job {job.id} cannot retry from status queued"
    assert session.committed is False


async def test_cancel_queued_job_returns_updated_job_and_commits():
    job = _job(status=JobStatus.QUEUED)
    session = TransitionResponseSession(item=job)

    response = await _request("POST", f"/jobs/{job.id}/cancel", session)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert session.committed is True
    assert session.trace == ["flush", "refresh", "commit"]


@pytest.mark.parametrize("status", [JobStatus.RUNNING, JobStatus.SUCCEEDED])
async def test_cancel_running_or_completed_job_returns_409_without_commit(status):
    job = _job(status=status)
    session = FakeJobApiSession(item=job)

    response = await _request("POST", f"/jobs/{job.id}/cancel", session)

    assert response.status_code == 409
    assert response.json()["detail"] == f"Job {job.id} cannot cancel from status {status.value}"
    assert session.committed is False


class FakeJobApiSession:
    def __init__(self, *, jobs=None, item=None, events=None, summary_counts=None):
        self.jobs = list(jobs or [])
        self.item = item
        self.events = list(events or [])
        self.summary_counts = list(summary_counts or [])
        self.summary_sql = []
        self.event_sql = ""
        self.list_filters = None
        self.committed = False
        self.flushed = False

    async def scalars(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if "FROM workflow_events" in sql:
            self.event_sql = sql
            return self.events

        self.list_filters = {
            "statuses": {status.value for status in JobStatus if f"'{status.value}'" in sql},
            "job_type": "ingest.collect" if "'ingest.collect'" in sql else None,
            "error_class": "permanent" if "'permanent'" in sql else None,
            "limit": 17 if "LIMIT 17" in sql else None,
        }
        return self.jobs

    async def scalar(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if "count(" in sql:
            self.summary_sql.append(sql)
            return self.summary_counts.pop(0)
        return self.item

    async def get(self, model, item_id):
        assert model is WorkflowJob
        return self.item if self.item and self.item.id == item_id else None

    def add(self, value):
        if isinstance(value, WorkflowEvent):
            self.events.append(value)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True


class TransitionResponseSession(FakeJobApiSession):
    def __init__(self, *, item):
        super().__init__(item=item)
        self.trace = []

    async def flush(self):
        self.flushed = True
        self.trace.append("flush")
        attributes.instance_state(self.item)._expire_attributes(self.item.__dict__, ["updated_at"])

    async def refresh(self, instance):
        assert instance is self.item
        instance.updated_at = NOW + timedelta(seconds=1)
        self.trace.append("refresh")

    async def commit(self):
        assert self.trace == ["flush", "refresh"], "transition response fields must be refreshed before commit"
        self.committed = True
        self.trace.append("commit")


def _job(
    *,
    status=JobStatus.QUEUED,
    error_class=None,
    payload=None,
    result=None,
    lease_owner=None,
):
    return WorkflowJob(
        id=uuid4(),
        job_type="ingest.collect",
        status=status,
        payload=payload or {},
        result=result or {},
        priority=5,
        idempotency_key=f"test:{uuid4()}",
        origin=JobOrigin.MANUAL,
        pause_sensitive=False,
        scheduled_for=NOW,
        attempt_count=1,
        max_attempts=3,
        lease_owner=lease_owner,
        lease_expires_at=NOW + timedelta(minutes=5) if lease_owner else None,
        heartbeat_at=NOW if lease_owner else None,
        progress=25,
        progress_message="collecting",
        error_class=error_class,
        error_code="source_failed" if error_class else None,
        error_message="A source failed" if error_class else None,
        started_at=NOW - timedelta(minutes=4),
        finished_at=NOW if status in {JobStatus.SUCCEEDED, JobStatus.FAILED} else None,
        created_at=NOW - timedelta(minutes=10),
        updated_at=NOW,
    )


def _event(job_id, event_type, created_at, event_data):
    return WorkflowEvent(
        id=uuid4(),
        workflow_job_id=job_id,
        event_type=event_type,
        actor="worker",
        event_data=event_data,
        created_at=created_at,
    )


async def _request(method, path, session):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path)
    finally:
        app.dependency_overrides.clear()
