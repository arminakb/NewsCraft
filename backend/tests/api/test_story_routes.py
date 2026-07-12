from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.jobs.types import JobStatus
from app.main import app


class FakeSession:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


async def test_manual_url_endpoint_enqueues_without_fetching_and_deduplicates(monkeypatch):
    fetch_called = False
    calls: list[dict] = []
    job = SimpleNamespace(id=uuid4(), status=JobStatus.QUEUED)

    async def forbidden_fetch(*args, **kwargs):
        nonlocal fetch_called
        fetch_called = True
        raise AssertionError("API route performed network I/O")

    class FakeJobs:
        def __init__(self, session):
            self.session = session

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(job=job, created=len(calls) == 1)

    session = FakeSession()

    async def override_session():
        yield session

    monkeypatch.setattr("app.stories.manual_intake.extract_article", forbidden_fetch)
    monkeypatch.setattr("app.api.stories.JobRepository", FakeJobs)
    app.dependency_overrides[get_session] = override_session
    payload = {
        "kind": "url",
        "url": "https://example.com/report",
        "title": "Optional title",
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/stories/manual", json=payload)
            second = await client.post("/stories/manual", json=payload)
    finally:
        app.dependency_overrides.clear()

    expected_payload = payload
    expected_hash = hashlib.sha256(
        json.dumps(expected_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert first.status_code == second.status_code == 202
    assert first.json() == {
        "job_id": str(job.id),
        "status": "queued",
        "deduplicated": False,
    }
    assert second.json()["deduplicated"] is True
    assert calls[0] == {
        "job_type": "manual_intake",
        "payload": expected_payload,
        "idempotency_key": f"manual_intake:{expected_hash}",
        "origin": "manual",
    }
    assert session.committed is True
    assert fetch_called is False


async def test_manual_story_route_rejects_extra_fields():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/stories/manual",
            json={
                "kind": "text",
                "title": "Operator note",
                "text": "Confirmed source material supplied by the operator.",
                "source_label": "Interview",
                "unexpected": "field",
            },
        )

    assert response.status_code == 422
