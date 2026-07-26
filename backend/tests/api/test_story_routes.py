from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.jobs.models import WorkflowEvent
from app.jobs.types import JobStatus
from app.main import app
from app.stories.models import Story


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


class _PageSession:
    def __init__(self, pages):
        self.pages = iter(pages)

    async def scalars(self, _statement):
        return iter(next(self.pages, []))


def _story(story_id, *, updated_at, complete):
    return Story(
        id=story_id,
        title="complete" if complete else "incomplete",
        status="inbox",
        primary_language="en",
        superseded_by_id=None,
        created_at=updated_at,
        updated_at=updated_at,
    )


async def test_completeness_filter_scans_past_nonmatching_db_pages_with_stable_cursor(monkeypatch):
    from app.api import stories as routes

    now = datetime.now(UTC)
    first_page = [_story(uuid4(), updated_at=now - timedelta(seconds=index), complete=False) for index in range(25)]
    matches = [_story(uuid4(), updated_at=now - timedelta(seconds=30 + index), complete=True) for index in range(3)]

    async def summaries(_session, stories):
        return {
            story.id: {
                "id": story.id,
                "completeness": {"complete": story.title == "complete"},
            }
            for story in stories
        }

    monkeypatch.setattr(routes, "_story_summaries", summaries)
    first = await routes.list_stories(
        search=None,
        editorial_state=None,
        completeness="complete",
        include_superseded=False,
        limit=2,
        cursor=None,
        session=_PageSession([first_page, matches]),
    )
    assert [item["id"] for item in first["items"]] == [matches[0].id, matches[1].id]
    assert first["next_cursor"] is not None

    second = await routes.list_stories(
        search=None,
        editorial_state=None,
        completeness="complete",
        include_superseded=False,
        limit=2,
        cursor=first["next_cursor"],
        session=_PageSession([[matches[2]]]),
    )
    assert [item["id"] for item in second["items"]] == [matches[2].id]
    assert second["next_cursor"] is None
    assert not ({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _BatchQuerySession:
    def __init__(self, pages, evidence):
        self.pages = iter(pages)
        self.evidence = evidence
        self.current_story_ids = set()
        self.query_count = 0

    async def scalars(self, _statement):
        self.query_count += 1
        page = list(next(self.pages, []))
        self.current_story_ids = {story.id for story in page}
        return iter(page)

    async def execute(self, _statement):
        self.query_count += 1
        rows = [row for story_id in self.current_story_ids for row in self.evidence.get(story_id, [])]
        rows.sort(key=lambda row: (row.story_id, row.captured_at, row.id))
        return _RowsResult(rows)


async def test_story_list_batch_loads_evidence_with_bounded_queries_and_deterministic_hash():
    from app.api import stories as routes
    from app.research.service import evidence_set_hash

    now = datetime.now(UTC)
    first_page = [_story(uuid4(), updated_at=now - timedelta(seconds=index), complete=False) for index in range(25)]
    later = [_story(uuid4(), updated_at=now - timedelta(seconds=30 + index), complete=True) for index in range(3)]
    evidence = {}
    for story in first_page:
        evidence[story.id] = [
            SimpleNamespace(
                id=uuid4(),
                story_id=story.id,
                evidence_key="operator-text:" + "0" * 64,
                content_sha256="0" * 64,
                content_text="short",
                source_url=None,
                snapshot_metadata={},
                captured_at=now,
            )
        ]
    for story in later:
        rows = []
        for index, host in enumerate(("one.example", "two.example"), start=1):
            text = str(index) * 500
            digest = hashlib.sha256(text.encode()).hexdigest()
            rows.append(
                SimpleNamespace(
                    id=uuid4(),
                    story_id=story.id,
                    evidence_key=f"url:https://{host}/item:{digest}",
                    content_sha256=digest,
                    content_text=text,
                    source_url=f"https://{host}/item",
                    snapshot_metadata={"is_primary": index == 1},
                    captured_at=now,
                )
            )
        evidence[story.id] = rows
    session = _BatchQuerySession([first_page, later], evidence)
    page = await routes.list_stories(
        search=None,
        editorial_state=None,
        completeness="complete",
        include_superseded=False,
        limit=2,
        cursor=None,
        session=session,
    )
    assert session.query_count == 4
    assert [item["id"] for item in page["items"]] == [later[0].id, later[1].id]
    assert page["next_cursor"] is not None
    expected_rows = sorted(evidence[later[0].id], key=lambda row: (row.captured_at, row.id))
    assert page["items"][0]["evidence_set_hash"] == evidence_set_hash(expected_rows)


class _StateSession:
    def __init__(self, stories):
        self.stories = stories
        self.added = []

    async def scalars(self, _statement):
        return iter(self.stories)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        return None


async def test_bulk_editorial_transition_is_atomic_and_appends_sanitized_events(monkeypatch):
    from app.api import stories as routes

    now = datetime.now(UTC)
    rows = [_story(uuid4(), updated_at=now - timedelta(seconds=index), complete=False) for index in range(2)]

    async def summary(_session, story):
        return {"id": story.id, "status": story.status}

    monkeypatch.setattr(routes, "_story_summary", summary)
    session = _StateSession(rows)
    result = await routes._change_states(session, [row.id for row in rows], "shortlisted")
    assert [item["status"] for item in result] == ["shortlisted", "shortlisted"]
    events = [item for item in session.added if isinstance(item, WorkflowEvent)]
    assert len(events) == 2
    assert all(item.event_type == "story.editorial_state_changed" for item in events)
    assert all(item.event_data["new_state"] == "shortlisted" for item in events)


async def test_bulk_editorial_transition_rejects_missing_or_superseded_without_changes(monkeypatch):
    from app.api import stories as routes

    now = datetime.now(UTC)
    active = _story(uuid4(), updated_at=now, complete=False)
    superseded = _story(uuid4(), updated_at=now - timedelta(seconds=1), complete=False)
    superseded.superseded_by_id = uuid4()
    session = _StateSession([active, superseded])
    with pytest.raises(HTTPException) as error:
        await routes._change_states(session, [active.id, superseded.id], "rejected")
    assert error.value.status_code == 409
    assert active.status == "inbox"
    assert superseded.status == "inbox"
    assert session.added == []


async def test_bulk_editorial_http_409_is_atomic_for_superseded_story(monkeypatch):
    from app.api import stories as routes

    now = datetime.now(UTC)
    active = _story(uuid4(), updated_at=now, complete=False)
    superseded = _story(uuid4(), updated_at=now - timedelta(seconds=1), complete=False)
    superseded.superseded_by_id = uuid4()
    session = _StateSession([active, superseded])

    async def summary(_session, story):
        return {"id": story.id, "status": story.status}

    async def override_session():
        yield session

    monkeypatch.setattr(routes, "_story_summary", summary)
    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/stories/bulk-editorial-state",
                json={
                    "story_ids": [str(active.id), str(superseded.id)],
                    "state": "rejected",
                },
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409
    assert active.status == superseded.status == "inbox"
    assert session.added == []


async def test_group_pending_endpoint_returns_202_without_grouping_inline(monkeypatch):
    from app.api import stories as routes

    candidate_ids = [uuid4(), uuid4()]
    job = SimpleNamespace(id=uuid4(), status=JobStatus.QUEUED)
    calls = []

    class Session:
        async def scalars(self, _statement):
            return iter(candidate_ids)

        async def commit(self):
            return None

    class FakeJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(job=job, created=True)

    session = Session()

    async def override_session():
        yield session

    monkeypatch.setattr(routes, "JobRepository", FakeJobs)
    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/stories/group-pending", json={"limit": 50})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 202
    assert response.json()["job_id"] == str(job.id)
    assert len(calls) == 1
    assert calls[0]["job_type"] == "story.group_pending"
    assert calls[0]["payload"] == {"limit": 50, "cursor": None, "root_ingest_job_id": None}
    assert calls[0]["idempotency_key"].startswith("story-group-pending:")


async def test_single_and_bulk_editorial_http_contracts(monkeypatch):
    from app.api import stories as routes

    first_id, second_id = uuid4(), uuid4()
    calls = []

    class Session:
        async def commit(self):
            return None

    async def change(_session, story_ids, state):
        calls.append((story_ids, state))
        return [{"id": value, "status": state} for value in story_ids]

    session = Session()

    async def override_session():
        yield session

    monkeypatch.setattr(routes, "_change_states", change)
    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            single = await client.patch(f"/stories/{first_id}/editorial-state", json={"state": "shortlisted"})
            bulk = await client.post(
                "/stories/bulk-editorial-state",
                json={"story_ids": [str(first_id), str(second_id)], "state": "rejected"},
            )
            invalid = await client.patch(f"/stories/{first_id}/editorial-state", json={"state": "published"})
    finally:
        app.dependency_overrides.clear()
    assert single.status_code == bulk.status_code == 200
    assert single.json() == {"id": str(first_id), "status": "shortlisted"}
    assert [item["id"] for item in bulk.json()["items"]] == [str(first_id), str(second_id)]
    assert invalid.status_code == 422
    assert calls == [([first_id], "shortlisted"), ([first_id, second_id], "rejected")]


async def test_story_research_endpoints_return_202_and_sanitized_full_projection(monkeypatch):
    from app.api import stories as routes
    from app.research.schemas import CompletenessReport
    from app.research.service import ResearchDisposition

    story_id = uuid4()
    run_id = uuid4()
    job_id = uuid4()
    profile_id = uuid4()
    attempt_id = uuid4()
    source_id = uuid4()
    revision_id = uuid4()
    now = datetime.now(UTC)
    calls = []

    class Session:
        committed = False

        async def commit(self):
            self.committed = True

    projection = {
        "id": run_id,
        "story_id": story_id,
        "requested_mode": "manual",
        "status": "succeeded",
        "provider": {"id": profile_id, "name": "Safe profile", "provider_type": "fake"},
        "requested_model": "fake-v1",
        "resolved_model": "fake-v1",
        "evidence_set_hash": "a" * 64,
        "completeness": {"complete": False, "score": 25, "reasons": ["insufficient_body_text"]},
        "budget": {"max_queries": 4, "max_pages": 8, "max_elapsed_seconds": 120},
        "attempts": [{"id": attempt_id, "status": "succeeded", "usage": {"pages": 1}}],
        "events": [{"id": uuid4(), "event_type": "research.succeeded", "event_data": {}}],
        "sources": [{"id": source_id, "url": "https://example.com/report", "title": "Report"}],
        "result_revision_id": revision_id,
        "job_status": "succeeded",
        "created_at": now,
        "started_at": now,
        "finished_at": now,
    }

    class FakeResearchService:
        def __init__(self, _session):
            pass

        async def request(self, **kwargs):
            calls.append(kwargs)
            return ResearchDisposition(
                disposition="enqueued",
                run_id=run_id,
                job_id=job_id,
                completeness=CompletenessReport(
                    complete=False,
                    score=25,
                    reasons=[
                        "fewer_than_two_independent_sources",
                        "insufficient_body_text",
                        "missing_primary_evidence",
                    ],
                    independent_source_count=1,
                    body_character_count=20,
                    has_primary_evidence=False,
                ),
            )

        async def list_runs(self, value):
            assert value == story_id
            return [projection]

        async def get_run(self, value):
            assert value == run_id
            return projection

    session = Session()

    async def override_session():
        yield session

    monkeypatch.setattr(routes, "ResearchService", FakeResearchService)
    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                f"/stories/{story_id}/research-runs",
                json={"mode": "manual", "depth": "deep", "provider_profile_id": str(profile_id)},
            )
            listed = await client.get(f"/stories/{story_id}/research-runs")
            detail = await client.get(f"/research-runs/{run_id}")
    finally:
        app.dependency_overrides.clear()
    assert created.status_code == 202
    assert created.json()["job_id"] == str(job_id)
    assert calls == [
        {
            "story_id": story_id,
            "mode": "manual",
            "depth": "deep",
            "provider_profile_id": profile_id,
            "query_hint": None,
        }
    ]
    assert listed.status_code == detail.status_code == 200
    assert listed.json()["items"][0] == detail.json()
    value = detail.json()
    assert {
        "provider",
        "requested_model",
        "resolved_model",
        "budget",
        "attempts",
        "events",
        "sources",
        "result_revision_id",
        "job_status",
    }.issubset(value)

    def keys(item):
        if isinstance(item, dict):
            return {str(key).lower() for key in item} | set().union(*(keys(v) for v in item.values()))
        if isinstance(item, list):
            return set().union(*(keys(v) for v in item)) if item else set()
        return set()

    assert keys(value).isdisjoint(
        {
            "secret_ref",
            "settings",
            "authorization",
            "environment",
            "env",
            "openai_api_key",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        }
    )
