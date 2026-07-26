from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.telegram_schemas import TelegramResearchPolicyInput, TelegramRouteCreate
from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.handlers import build_telegram_process_handler
from app.db.models import ContentItem, SourceItem
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplateVersion
from app.generation.provider_settings import default_codex_provider_settings
from app.generation.telegram_schema import TelegramRewriteOutput
from app.jobs.errors import NeedsReviewJobError
from app.jobs.registry import JobContext
from app.publishing.models import Destination
from app.research.handlers import build_research_story_handler
from app.research.models import ResearchRun
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision
from tests.research.test_handlers import (
    ObservingBackend,
    _lifecycle_fixture,
    _subscribe_dispatch,
)
from tests.test_telegram_process_handler import (
    CapturingCodexProvider,
    HandlerProbeSession,
    ProbeResolver,
    ProbeStop,
)


def test_off_policy_stores_no_research_profile():
    value = TelegramResearchPolicyInput.model_validate({"research_mode": "off", "research_provider_profile_id": None})
    assert value.research_provider_profile_id is None


def test_automatic_policy_requires_profile_uuid():
    with pytest.raises(ValidationError, match="require"):
        TelegramResearchPolicyInput.model_validate(
            {"research_mode": "auto_if_incomplete", "research_provider_profile_id": None}
        )


def test_route_accepts_profile_id_and_never_accepts_backend_literal():
    profile_id = uuid4()
    route = TelegramRouteCreate.model_validate(
        {
            "name": "Research route",
            "source_id": str(uuid4()),
            "destination_id": str(uuid4()),
            "brand_profile_id": str(uuid4()),
            "prompt_template_version_id": str(uuid4()),
            "ai_provider_profile_id": str(uuid4()),
            "prompt_policy": "pinned",
            "access_mode": "public_html",
            "research_mode": "manual",
            "content_filters": {"research_provider_profile_id": str(profile_id)},
        }
    )
    assert route.content_filters.research_provider_profile_id == profile_id
    with pytest.raises(ValidationError):
        TelegramRouteCreate.model_validate(
            {
                **route.model_dump(mode="json"),
                "content_filters": {"research_backend": "openrouter"},
            }
        )


def _process_probe(*, mode: str, complete: bool, manual_succeeded: bool = False):
    now = datetime.now(UTC)
    generation_profile = AIProviderProfile(
        id=uuid4(),
        name="Codex",
        provider_type="codex",
        default_model="gpt-5.4",
        secret_ref=None,
        settings=default_codex_provider_settings().model_dump(mode="json"),
        enabled=True,
    )
    research_profile = AIProviderProfile(
        id=uuid4(),
        name="Research fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    route = AutomationRoute(
        id=uuid4(),
        source_id=uuid4(),
        destination_id=uuid4(),
        brand_profile_id=uuid4(),
        prompt_template_version_id=uuid4(),
        ai_provider_profile_id=generation_profile.id,
        research_mode=mode,
        content_filters=({} if mode == "off" else {"research_provider_profile_id": str(research_profile.id)}),
        attribution_policy="preserve",
        custom_footer=None,
        retry_policy={},
    )
    story = Story(
        id=uuid4(),
        title="Telegram story",
        status="inbox",
        primary_language="fa",
        superseded_by_id=None,
        created_at=now,
        updated_at=now,
    )
    revision = StoryRevision(id=uuid4(), story_id=story.id, revision_number=1)
    content_item = ContentItem(id=uuid4(), content_text="source", direction="ltr")
    source_item = SourceItem(
        id=uuid4(),
        source_id=route.source_id,
        content_item_id=content_item.id,
        external_id_raw="source:1",
        external_id_norm="source:1",
        content_text_raw="source",
    )
    text = "x" * (500 if complete else 20)
    digest = sha256(text.encode()).hexdigest()
    snapshot = StoryEvidenceSnapshot(
        id=uuid4(),
        story_id=story.id,
        evidence_key=f"url:https://one.example/item:{digest}",
        source_url="https://one.example/item",
        content_text=text,
        content_sha256=digest,
        authors=[],
        snapshot_metadata={"is_primary": complete},
        captured_at=now,
    )
    snapshots = [snapshot]
    if complete:
        other_text = "y" * 500
        other_digest = sha256(other_text.encode()).hexdigest()
        snapshots.append(
            StoryEvidenceSnapshot(
                id=uuid4(),
                story_id=story.id,
                evidence_key=f"url:https://two.example/item:{other_digest}",
                source_url="https://two.example/item",
                content_text=other_text,
                content_sha256=other_digest,
                authors=[],
                snapshot_metadata={},
                captured_at=now,
            )
        )
    link = StoryEvidenceLink(
        story_revision_id=revision.id,
        evidence_snapshot_id=snapshot.id,
        claim_key="telegram.source",
        relationship="supports",
    )
    prompt = PromptTemplateVersion(
        id=route.prompt_template_version_id,
        prompt_template_id=uuid4(),
        version=1,
        system_template="Locked",
        user_template=(
            "{source_text} {source_url} {source_channel} {language} {direction} {attribution_policy} {custom_footer}"
        ),
        output_schema_version="telegram_rewrite.v1",
        output_schema=TelegramRewriteOutput.model_json_schema(),
        checksum_sha256="a" * 64,
        is_active=True,
    )
    brand = BrandProfile(id=route.brand_profile_id, name="Brand", output_language="fa", tone="neutral")
    destination = Destination(
        id=route.destination_id,
        name="Destination",
        platform="telegram",
        target_ref="@destination",
        secret_ref="DESTINATION_TOKEN",
        enabled=True,
        health_status="healthy",
        settings={},
    )
    dispatch = AutomationDispatch(
        id=uuid4(),
        route_id=route.id,
        source_item_id=source_item.id,
        story_revision_id=revision.id,
        source_key="source:1",
        source_fingerprint="f" * 64,
        source_message_ids=[1],
        dispatch_kind="live",
        status="captured",
        created_at=now,
    )
    values = [
        route,
        story,
        revision,
        source_item,
        content_item,
        *snapshots,
        prompt,
        brand,
        generation_profile,
        research_profile,
        destination,
    ]
    if manual_succeeded:
        values.append(
            ResearchRun(
                id=uuid4(),
                story_id=story.id,
                requested_mode="manual",
                provider_profile_id=research_profile.id,
                status="succeeded",
                query_budget=4,
                page_budget=8,
                time_budget_seconds=120,
                result_story_revision_id=revision.id,
                created_at=now,
                finished_at=now,
            )
        )
    provider = CapturingCodexProvider(generation_profile)
    session = HandlerProbeSession(values, dispatch, link)
    job = SimpleNamespace(
        id=uuid4(),
        payload={"dispatch_id": str(dispatch.id)},
        attempt_count=1,
    )
    handler = build_telegram_process_handler(ProbeResolver(generation_profile, provider))
    return SimpleNamespace(
        handler=handler,
        session=session,
        job=job,
        provider=provider,
        dispatch=dispatch,
        research_profile=research_profile,
    )


async def test_off_mode_enters_generation_without_research_enqueue(monkeypatch):
    probe = _process_probe(mode="off", complete=False)

    class ForbiddenJobs:
        def __init__(self, _session):
            raise AssertionError("off mode constructed a research repository")

    monkeypatch.setattr("app.research.service.JobRepository", ForbiddenJobs)
    with pytest.raises(ProbeStop):
        await probe.handler(probe.job, JobContext(session=probe.session, providers=SimpleNamespace()))
    assert probe.provider.request is not None


async def test_manual_mode_reviews_without_auto_research_then_resumes_once():
    pending = _process_probe(mode="manual", complete=False)
    with pytest.raises(NeedsReviewJobError, match="Manual research"):
        await pending.handler(pending.job, JobContext(session=pending.session, providers=SimpleNamespace()))
    assert pending.provider.request is None

    resumed = _process_probe(mode="manual", complete=False, manual_succeeded=True)
    with pytest.raises(ProbeStop):
        await resumed.handler(resumed.job, JobContext(session=resumed.session, providers=SimpleNamespace()))
    assert resumed.provider.request is not None


async def test_auto_complete_valid_profile_skips_research_and_enters_generation(monkeypatch):
    probe = _process_probe(mode="auto_if_incomplete", complete=True)
    calls = []

    class FakeJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("complete story enqueued research")

    monkeypatch.setattr("app.research.service.JobRepository", FakeJobs)
    with pytest.raises(ProbeStop):
        await probe.handler(probe.job, JobContext(session=probe.session, providers=SimpleNamespace()))
    assert calls == []
    assert probe.provider.request is not None


async def test_auto_incomplete_enqueues_one_exact_research_job_before_generation(monkeypatch):
    probe = _process_probe(mode="auto_if_incomplete", complete=False)
    calls = []

    class FakeJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                job=SimpleNamespace(id=uuid4(), status="queued", payload=kwargs["payload"]),
                created=True,
            )

    monkeypatch.setattr("app.research.service.JobRepository", FakeJobs)
    result = await probe.handler(probe.job, JobContext(session=probe.session, providers=SimpleNamespace()))
    assert probe.provider.request is None
    assert len(calls) == 1 and calls[0]["job_type"] == "research_story"
    assert calls[0]["payload"]["provider_profile_id"] == str(probe.research_profile.id)
    assert calls[0]["idempotency_key"].startswith("research_story:")
    assert calls[0]["idempotency_key"].endswith(f":{probe.research_profile.id}:fake-v1:auto_if_incomplete:standard")
    assert str(probe.dispatch.id) not in calls[0]["idempotency_key"]
    continuation = calls[0]["payload"]["continuations"][0]
    assert continuation["job_type"] == "telegram.route.process"
    assert continuation["payload"]["dispatch_id"] == str(probe.dispatch.id)
    assert result["research_job_id"] is not None


async def test_successful_research_continuation_is_once_and_carries_completed_id(monkeypatch):
    session, job, run, output = _lifecycle_fixture()
    _subscribe_dispatch(session, job, run)
    calls = []

    class FakeJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(job=SimpleNamespace(id=uuid4()), created=True)

    monkeypatch.setattr("app.research.continuations.JobRepository", FakeJobs)
    backend = ObservingBackend(session, output)
    handler = build_research_story_handler(lambda _profile: backend)
    await handler(job, JobContext(session=session, providers=SimpleNamespace()))
    replay = await handler(job, JobContext(session=session, providers=SimpleNamespace()))
    assert replay["idempotent"] is True
    assert len(calls) == 1 and backend.calls == 1
    assert calls[0]["job_type"] == "telegram.route.process"
    assert calls[0]["payload"]["completed_research_run_id"] == str(run.id)
    assert "continuation" not in calls[0]["payload"]


async def test_failed_research_leaves_dispatch_review_without_continuation_or_publish(monkeypatch):
    session, job, run, output = _lifecycle_fixture(unknown_key=True)
    dispatch = _subscribe_dispatch(session, job, run)
    calls = []

    class FakeJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("app.research.continuations.JobRepository", FakeJobs)
    with pytest.raises(NeedsReviewJobError):
        await build_research_story_handler(lambda _profile: ObservingBackend(session, output))(
            job, JobContext(session=session, providers=SimpleNamespace())
        )
    persisted = next(
        value for value in session.values if isinstance(value, AutomationDispatch) and value.id == dispatch.id
    )
    assert persisted.status == "needs_review"
    assert persisted.publish_job_id is None and persisted.variant_revision_id is None
    assert calls == []
