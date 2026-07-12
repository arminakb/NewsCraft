from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.providers.registry import build_default_provider_registry
from app.jobs.handlers import handle_ingest_collect
from app.jobs.registry import JobContext
from app.jobs.types import JobOrigin
from app.stories.handlers import group_pending_content


def pending_item(title: str, url: str, *, hours: int = 0):
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        canonical_url=url,
        published_at=datetime(2026, 7, 11, 8 + hours, tzinfo=UTC),
        sort_at=datetime(2026, 7, 11, 8 + hours, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_group_pending_handler_is_deterministic_and_replay_safe(monkeypatch):
    first = pending_item("OpenAI releases coding agent", "https://example.com/agent")
    second = pending_item(
        "OpenAI releases coding agent for developers",
        "https://example.com/agent?utm_source=rss",
        hours=1,
    )

    class FakeRepository:
        def __init__(self):
            self.group_calls = []
            self.story = SimpleNamespace(id=uuid4())

        async def list_pending_content_items(self, *, limit, cursor):
            assert limit == 100
            assert cursor is None
            return [first, second]

        async def group_content_items(self, content_item_ids):
            self.group_calls.append(tuple(content_item_ids))
            return self.story

        async def list_evidence(self, story_id):
            assert story_id == self.story.id
            return [SimpleNamespace(evidence_snapshot_id=first.id), SimpleNamespace(evidence_snapshot_id=second.id)]

    repository = FakeRepository()
    monkeypatch.setattr("app.stories.handlers.StoryRepository", lambda session: repository)
    job = SimpleNamespace(id=uuid4(), payload={"limit": 100})
    context = JobContext(session=object(), providers=build_default_provider_registry())

    first_result = await group_pending_content(job, context)
    second_result = await group_pending_content(job, context)

    assert first_result == second_result
    assert first_result == {
        "selected_count": 2,
        "grouped_story_count": 1,
        "evidence_snapshot_count": 2,
        "next_cursor": None,
    }
    assert repository.group_calls == [(first.id, second.id), (first.id, second.id)]


@pytest.mark.asyncio
async def test_successful_ingestion_enqueues_one_grouping_followup(monkeypatch):
    class FakeWorkflow:
        async def run(self, **kwargs):
            return {"failed": 0, "fetched": 2}

    class FakeJobs:
        def __init__(self):
            self.by_key = {}

        async def enqueue_job(self, **kwargs):
            self.by_key.setdefault(kwargs["idempotency_key"], kwargs)
            return SimpleNamespace(job=SimpleNamespace(id=uuid4()), created=len(self.by_key) == 1)

    jobs = FakeJobs()
    monkeypatch.setattr("app.jobs.handlers._build_workflow", FakeWorkflow)
    monkeypatch.setattr("app.jobs.handlers._build_job_repository", lambda session: jobs)
    session = AsyncSession()
    context = JobContext(session=session, providers=build_default_provider_registry())
    job = SimpleNamespace(id=uuid4(), payload={})

    first_result = await handle_ingest_collect(job, context)
    replay_result = await handle_ingest_collect(job, context)

    assert first_result == replay_result == {"failed": 0, "fetched": 2}
    assert list(jobs.by_key) == [f"story-group:{job.id}"]
    followup = jobs.by_key[f"story-group:{job.id}"]
    assert followup["job_type"] == "story.group_pending"
    assert followup["payload"] == {"limit": 100, "root_ingest_job_id": str(job.id)}
    assert followup["origin"] == JobOrigin.AUTOMATION
    await session.close()


@pytest.mark.asyncio
async def test_successful_ingestion_always_uses_job_repository_for_followup(monkeypatch):
    class FakeWorkflow:
        async def run(self, **kwargs):
            return {"failed": 0, "fetched": 1}

    calls = []

    class FakeJobs:
        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(job=SimpleNamespace(id=uuid4()), created=True)

    monkeypatch.setattr("app.jobs.handlers._build_workflow", FakeWorkflow)
    monkeypatch.setattr("app.jobs.handlers._build_job_repository", lambda session: FakeJobs())
    job = SimpleNamespace(id=uuid4(), payload={})
    context = JobContext(session=object(), providers=build_default_provider_registry())

    await handle_ingest_collect(job, context)

    assert len(calls) == 1
    assert calls[0]["idempotency_key"] == f"story-group:{job.id}"


@pytest.mark.asyncio
async def test_full_grouping_page_enqueues_one_idempotent_continuation(monkeypatch):
    first = pending_item("First story", "https://example.com/first")
    second = pending_item("Second story", "https://example.com/second")

    class FakeRepository:
        async def list_pending_content_items(self, *, limit, cursor):
            assert limit == 2
            assert cursor is None
            return [first, second]

        async def group_content_items(self, content_item_ids):
            return SimpleNamespace(id=content_item_ids[0])

        async def list_evidence(self, story_id):
            return [SimpleNamespace(evidence_snapshot_id=story_id)]

    class FakeJobs:
        def __init__(self):
            self.by_key = {}

        async def enqueue_job(self, **kwargs):
            self.by_key.setdefault(kwargs["idempotency_key"], kwargs)
            return SimpleNamespace(job=SimpleNamespace(id=uuid4()), created=True)

    jobs = FakeJobs()
    monkeypatch.setattr("app.stories.handlers.StoryRepository", lambda session: FakeRepository())
    monkeypatch.setattr("app.stories.handlers._build_job_repository", lambda session: jobs, raising=False)
    root_id = uuid4()
    job = SimpleNamespace(id=uuid4(), payload={"limit": 2, "root_ingest_job_id": str(root_id)})
    context = JobContext(session=object(), providers=build_default_provider_registry())

    first_result = await group_pending_content(job, context)
    replay_result = await group_pending_content(job, context)

    next_cursor = str(second.id)
    assert first_result == replay_result
    assert first_result["next_cursor"] == next_cursor
    assert list(jobs.by_key) == [f"story-group-page:{root_id}:{next_cursor}"]
    continuation = jobs.by_key[f"story-group-page:{root_id}:{next_cursor}"]
    assert continuation["payload"] == {
        "limit": 2,
        "cursor": next_cursor,
        "root_ingest_job_id": str(root_id),
    }
    assert continuation["origin"] == JobOrigin.AUTOMATION


@pytest.mark.asyncio
async def test_short_final_grouping_page_enqueues_no_continuation(monkeypatch):
    only = pending_item("Only story", "https://example.com/only")

    class FakeRepository:
        async def list_pending_content_items(self, *, limit, cursor):
            return [only]

        async def group_content_items(self, content_item_ids):
            return SimpleNamespace(id=only.id)

        async def list_evidence(self, story_id):
            return [SimpleNamespace(evidence_snapshot_id=only.id)]

    class FakeJobs:
        async def enqueue_job(self, **kwargs):
            raise AssertionError("final page must not enqueue a continuation")

    monkeypatch.setattr("app.stories.handlers.StoryRepository", lambda session: FakeRepository())
    monkeypatch.setattr("app.stories.handlers._build_job_repository", lambda session: FakeJobs(), raising=False)
    job = SimpleNamespace(
        id=uuid4(),
        payload={"limit": 2, "root_ingest_job_id": str(uuid4())},
    )
    context = JobContext(session=object(), providers=build_default_provider_registry())

    result = await group_pending_content(job, context)

    assert result["next_cursor"] is None
