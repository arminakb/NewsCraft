from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.automations.models import AutomationDispatch
from app.generation.models import AIProviderProfile
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.research.models import ResearchAttempt, ResearchRun, ResearchSource
from app.research.service import ResearchRequestError, ResearchService
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision
from tests.research.test_handlers import (
    TransactionalSession,
    _lifecycle_fixture,
    _subscribe_dispatch,
)


class _Scalars:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)


class FakeSession:
    def __init__(self, story, snapshots, profile=None):
        self.story = story
        self.snapshots = snapshots
        self.profile = profile

    async def scalar(self, _statement):
        return self.story

    async def scalars(self, _statement):
        return _Scalars(self.snapshots)

    async def get(self, _model, identity):
        if self.profile is not None and identity == self.profile.id:
            return self.profile
        return None


def _fake_profile(*, enabled=True):
    return SimpleNamespace(
        id=uuid4(), enabled=enabled, provider_type="fake", secret_ref=None,
        settings={}, default_model="fake-v1",
    )


def _story_and_evidence(*, complete: bool):
    now = datetime.now(UTC)
    story = Story(
        id=uuid4(),
        title="Durable research",
        status="inbox",
        primary_language="en",
        superseded_by_id=None,
        created_at=now,
        updated_at=now,
    )
    text = "x" * 500 if complete else "short"
    snapshots = [
        StoryEvidenceSnapshot(
            id=uuid4(), story_id=story.id, content_item_id=None,
            evidence_key=f"operator-text:{index:064x}", source_url=f"https://source{index}.example/item",
            title="Evidence", content_text=text, authors=[], published_at=None,
            content_sha256=f"{index:064x}", snapshot_metadata={"is_primary": index == 1}, captured_at=now,
        )
        for index in (1, 2) if complete
    ]
    if not complete:
        snapshots = [
            StoryEvidenceSnapshot(
                id=uuid4(), story_id=story.id, content_item_id=None,
                evidence_key="operator-text:" + "0" * 64, source_url=None,
                title="Evidence", content_text=text, authors=[], published_at=None,
                content_sha256="0" * 64, snapshot_metadata={}, captured_at=now,
            )
        ]
    return story, snapshots


async def test_off_mode_never_enqueues_research():
    story, snapshots = _story_and_evidence(complete=False)
    result = await ResearchService(FakeSession(story, snapshots)).request(
        story_id=story.id, mode="off", depth="standard",
        provider_profile_id=None, query_hint=None,
    )
    assert result.disposition == "skipped"
    assert result.job_id is None


async def test_auto_mode_returns_complete_without_loading_a_profile():
    story, snapshots = _story_and_evidence(complete=True)
    profile = _fake_profile()
    result = await ResearchService(FakeSession(story, snapshots, profile)).request(
        story_id=story.id, mode="auto_if_incomplete", depth="standard",
        provider_profile_id=profile.id, query_hint=None,
    )
    assert result.disposition == "complete_without_research"
    assert result.completeness.complete is True


@pytest.mark.parametrize("profile", [None, _fake_profile(enabled=False)])
async def test_auto_complete_still_rejects_missing_or_disabled_profile(profile):
    story, snapshots = _story_and_evidence(complete=True)
    profile_id = uuid4() if profile is None else profile.id
    with pytest.raises(ResearchRequestError, match="unavailable"):
        await ResearchService(FakeSession(story, snapshots, profile)).request(
            story_id=story.id, mode="auto_if_incomplete", depth="standard",
            provider_profile_id=profile_id, query_hint=None,
        )


async def test_auto_complete_still_rejects_unavailable_fake_profile():
    story, snapshots = _story_and_evidence(complete=True)
    profile = _fake_profile()
    profile.settings = {"not_allowed": True}
    with pytest.raises(ResearchRequestError, match="invalid"):
        await ResearchService(FakeSession(story, snapshots, profile)).request(
            story_id=story.id, mode="auto_if_incomplete", depth="standard",
            provider_profile_id=profile.id, query_hint=None,
        )


async def test_off_mode_rejects_a_profile_id():
    story, snapshots = _story_and_evidence(complete=False)
    with pytest.raises(ResearchRequestError, match="cannot select"):
        await ResearchService(FakeSession(story, snapshots)).request(
            story_id=story.id, mode="off", depth="standard",
            provider_profile_id=uuid4(), query_hint=None,
        )


async def test_actual_run_projection_is_complete_and_never_exposes_provider_secrets():
    now = datetime.now(UTC)
    story_id, run_id, profile_id, revision_id = uuid4(), uuid4(), uuid4(), uuid4()
    run = ResearchRun(
        id=run_id, story_id=story_id, requested_mode="manual",
        provider_profile_id=profile_id, status="succeeded", query_budget=4,
        page_budget=8, time_budget_seconds=120, result_story_revision_id=revision_id,
        created_at=now, started_at=now, finished_at=now,
    )
    profile = AIProviderProfile(
        id=profile_id, name="Sensitive profile", provider_type="openrouter",
        default_model="model", secret_ref="OPENROUTER_API_KEY",
        settings={"authorization": "Bearer forbidden", "http_proxy": "http://secret"},
        enabled=True,
    )
    attempt = ResearchAttempt(
        id=uuid4(), research_run_id=run_id, attempt_number=1, queries=[],
        status="succeeded", usage={"pages": 1}, started_at=now, finished_at=now,
    )
    source = ResearchSource(
        id=uuid4(), research_run_id=run_id, url="https://example.com/report",
        title="Report", publisher="Publisher", published_at=None,
        content_sha256="a" * 64, extraction_status="ok", relevance=0,
        citation_key="url:https://example.com/report:" + "a" * 64,
        snapshot_metadata={"retrieved_at": now.isoformat()}, created_at=now,
    )
    job = WorkflowJob(
        id=uuid4(), job_type="research_story", status="succeeded",
        payload={
            "run_id": str(run_id), "requested_model": "model",
            "evidence_set_hash": "b" * 64,
            "completeness": {"complete": False},
            "budget": {"max_queries": 4, "max_pages": 8, "max_elapsed_seconds": 120},
        },
        idempotency_key=str(uuid4()), origin="manual",
    )
    event = WorkflowEvent(
        id=uuid4(), workflow_job_id=job.id, event_type="research.succeeded",
        actor="automation", event_data={"resolved_model": "resolved-model"}, created_at=now,
    )
    detail = await ResearchService(
        TransactionalSession([run, profile, attempt, source, job, event])
    ).get_run(run_id)
    assert detail["provider"] == {
        "id": profile_id, "name": "Sensitive profile", "provider_type": "openrouter",
    }
    assert detail["requested_model"] == "model"
    assert detail["resolved_model"] == "resolved-model"
    assert detail["budget"]["max_pages"] == 8
    assert detail["attempts"][0]["usage"] == {"pages": 1}
    assert detail["events"][0]["event_type"] == "research.succeeded"
    assert detail["sources"][0]["citation_key"].endswith("a" * 64)
    assert detail["result_revision_id"] == revision_id
    assert detail["job_status"] == "succeeded"
    rendered = str(detail).lower()
    assert "openrouter_api_key" not in rendered
    assert "bearer forbidden" not in rendered
    assert "http://secret" not in rendered


async def test_late_unique_subscriber_on_succeeded_canonical_run_continues_immediately(monkeypatch):
    session, canonical_job, run, _output = _lifecycle_fixture()
    run.requested_mode = "auto_if_incomplete"
    canonical_job.payload = {**canonical_job.payload, "mode": "auto_if_incomplete"}
    _subscribe_dispatch(session, canonical_job, run)
    descriptor = canonical_job.payload["continuations"][0]
    canonical_job.payload = {**canonical_job.payload, "continuations": []}
    story = next(value for value in session.values if isinstance(value, Story))
    now = datetime.now(UTC)
    for index, host in enumerate(("one.example", "two.example"), start=1):
        text = str(index) * 500
        digest = hashlib.sha256(text.encode()).hexdigest()
        session.values.append(
            StoryEvidenceSnapshot(
                id=uuid4(), story_id=story.id,
                evidence_key=f"url:https://{host}/item:{digest}",
                source_url=f"https://{host}/item", content_text=text,
                content_sha256=digest, authors=[],
                snapshot_metadata={"is_primary": index == 1}, captured_at=now,
            )
        )
    result_revision = StoryRevision(
        id=uuid4(), story_id=story.id, revision_number=2,
        parent_revision_id=UUID(descriptor["expected_story_revision_id"]),
        narrative="Research result", facts=[], disagreements=[], angles=[], citations=[],
        created_by="research",
    )
    session.values.append(result_revision)
    run.status = "succeeded"
    run.result_story_revision_id = result_revision.id
    research_calls = []
    continuation_calls = []

    class ExistingJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            research_calls.append(kwargs)
            return SimpleNamespace(job=canonical_job, created=False)

    class ContinuationJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            continuation_calls.append(kwargs)
            return SimpleNamespace(job=SimpleNamespace(id=uuid4()), created=True)

    monkeypatch.setattr("app.research.service.JobRepository", ExistingJobs)
    monkeypatch.setattr("app.research.continuations.JobRepository", ContinuationJobs)
    service = ResearchService(session)
    first = await service.request(
        story_id=story.id, mode="auto_if_incomplete", depth="standard",
        provider_profile_id=run.provider_profile_id, query_hint=None,
        continuation=descriptor,
    )
    second = await service.request(
        story_id=story.id, mode="auto_if_incomplete", depth="standard",
        provider_profile_id=run.provider_profile_id, query_hint=None,
        continuation=descriptor,
    )
    assert first.job_id == canonical_job.id
    assert second.disposition == "complete_without_research"
    assert research_calls == []
    assert len(continuation_calls) == 1
    assert continuation_calls[0]["payload"]["completed_research_run_id"] == str(run.id)

    original_dispatch = next(
        value for value in session.values if isinstance(value, AutomationDispatch)
    )
    operator_revision = StoryRevision(
        id=uuid4(), story_id=story.id, revision_number=3,
        parent_revision_id=result_revision.id, narrative="Operator revision",
        facts=[], disagreements=[], angles=[], citations=[], created_by="manual",
    )
    newer_dispatch = AutomationDispatch(
        id=uuid4(), route_id=original_dispatch.route_id, source_item_id=uuid4(),
        story_revision_id=operator_revision.id, source_key="source:new",
        source_fingerprint="e" * 64, source_message_ids=[2],
        dispatch_kind="live", status="captured",
    )
    session.values.extend([operator_revision, newer_dispatch])
    newer_descriptor = {
        **descriptor,
        "payload": {"dispatch_id": str(newer_dispatch.id), "force_review": False},
        "idempotency_prefix": f"telegram-route-process-after-research:{newer_dispatch.id}",
        "subscriber_id": f"telegram-dispatch:{newer_dispatch.id}",
        "expected_story_revision_id": str(operator_revision.id),
    }
    newer = await service.request(
        story_id=story.id, mode="auto_if_incomplete", depth="standard",
        provider_profile_id=run.provider_profile_id, query_hint=None,
        continuation=newer_descriptor,
    )
    assert newer.disposition == "complete_without_research"
    assert newer_dispatch.story_revision_id == operator_revision.id
    assert len(continuation_calls) == 1
