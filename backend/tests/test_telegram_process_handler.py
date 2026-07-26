from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.handlers import (
    ProcessDispatchPayload,
    _resolve_process_prompt,
    build_evidence_map,
    build_telegram_process_handler,
    sha256_canonical,
    validate_evidence_snapshot,
)
from app.automations.telegram.policy import evaluate_auto_publish
from app.automations.telegram.process_operations import _process_route_dispatch
from app.db.models import ContentItem, MediaAsset, SourceItem
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    GenerationAttempt,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.provider_settings import default_codex_provider_settings
from app.generation.providers.codex import CodexGenerationProvider
from app.generation.providers.profiles import ResolvedProviderProfile
from app.generation.telegram_schema import TelegramRewriteOutput
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext
from app.publishing.models import Destination
from app.research.models import ResearchRun
from app.stories.models import StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision


def valid_gate_input() -> dict:
    return {
        "global_pause": False,
        "global_dry_run": False,
        "route_paused": False,
        "destination_enabled": True,
        "destination_health": "healthy",
        "validation_ok": True,
        "evidence_ready": True,
        "media_ready": True,
    }


async def test_follow_active_resolves_once_and_persists_exact_job_prompt_snapshot():
    template = PromptTemplate(
        id=uuid4(),
        purpose_key="telegram_rewrite",
        name="Rewrite",
    )
    pinned = PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=template.id,
        version=1,
        system_template="one",
        user_template="one",
        output_schema_version="telegram_rewrite.v1",
        output_schema={},
        checksum_sha256="a" * 64,
        is_active=False,
    )
    active = PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=template.id,
        version=2,
        system_template="two",
        user_template="two",
        output_schema_version="telegram_rewrite.v1",
        output_schema={},
        checksum_sha256="b" * 64,
        is_active=True,
    )
    route = AutomationRoute(
        id=uuid4(),
        prompt_policy="follow_active",
        prompt_template_version_id=pinned.id,
    )
    workflow_job = SimpleNamespace(id=uuid4(), payload={"dispatch_id": str(uuid4())})

    class Session:
        async def get(self, model, identifier):
            if model is WorkflowJob and identifier == workflow_job.id:
                return workflow_job
            return next(
                (item for item in (template, pinned, active) if isinstance(item, model) and item.id == identifier),
                None,
            )

        async def scalars(self, statement):
            entity = statement.column_descriptions[0].get("entity")
            return [item for item in (template, pinned, active) if isinstance(item, entity)]

    session = Session()
    resolved = await _resolve_process_prompt(
        session,
        route=route,
        payload=ProcessDispatchPayload(dispatch_id=uuid4()),
        workflow_job_id=workflow_job.id,
    )
    assert resolved.id == active.id
    assert workflow_job.payload["prompt_template_version_id"] == str(active.id)
    assert workflow_job.payload["prompt_checksum"] == active.checksum_sha256

    active.is_active = False
    replay = await _resolve_process_prompt(
        session,
        route=route,
        payload=ProcessDispatchPayload(
            dispatch_id=uuid4(),
            prompt_template_version_id=active.id,
            prompt_checksum=active.checksum_sha256,
        ),
        workflow_job_id=workflow_job.id,
    )
    assert replay.id == active.id


@pytest.mark.parametrize(
    ("override", "allowed", "reason"),
    [
        ({}, True, None),
        ({"global_pause": True}, False, "global_pause"),
        ({"global_dry_run": True}, False, "global_dry_run"),
        ({"route_paused": True}, False, "route_paused"),
        ({"destination_enabled": False}, False, "destination_disabled"),
        ({"destination_health": "broken"}, False, "destination_unhealthy"),
        ({"validation_ok": False}, False, "variant_invalid"),
        ({"evidence_ready": False}, False, "evidence_invalid"),
        ({"media_ready": False}, False, "media_not_ready"),
    ],
)
def test_auto_publish_gate_is_fail_closed(override, allowed, reason):
    decision = evaluate_auto_publish(**{**valid_gate_input(), **override})

    assert (decision.allowed, decision.reason) == (allowed, reason)


def test_generation_finalization_locks_variant_before_runtime_controls():
    """Keep the writer, reviewed scheduler, and publish worker acyclic."""

    source = inspect.getsource(_process_route_dispatch)
    finalization = source[source.index("session.expire_all()") :]

    variant_lock = finalization.index("await _content_pack_and_variant")
    dispatch_lock = finalization.index("locked_dispatch = await session.scalar")
    route_lock = finalization.index("locked_route = await session.scalar")
    lineage_recheck = finalization.index("refreshed_parent = await _route_parent_revision")
    control_lock = finalization.index("select(AutomationControl)", route_lock)
    destination_lock = finalization.index("select(Destination)")
    publish_gate = finalization.index("gate = evaluate_auto_publish")

    assert variant_lock < dispatch_lock < route_lock < lineage_recheck < control_lock < destination_lock < publish_gate


def test_captured_snapshot_is_verified_and_cited_exactly():
    text = "متن منبع"
    snapshot = SimpleNamespace(
        id=uuid4(),
        evidence_key="telegram:channel:42",
        source_url="https://t.me/channel/42",
        content_text=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )

    validate_evidence_snapshot(snapshot)
    evidence = build_evidence_map(snapshot)

    assert evidence == [
        {
            "evidence_snapshot_id": str(snapshot.id),
            "evidence_key": snapshot.evidence_key,
            "source_url": snapshot.source_url,
            "locator": f"chars:0-{len(text)}",
            "excerpt_sha256": snapshot.content_sha256,
        }
    ]
    assert sha256_canonical({"content": {"body": "x"}, "evidence_map": evidence}) == (
        sha256_canonical({"evidence_map": evidence, "content": {"body": "x"}})
    )


@pytest.mark.parametrize("text,digest", [("", hashlib.sha256(b"").hexdigest()), ("body", "0" * 64)])
def test_invalid_snapshot_fails_before_generation(text, digest):
    snapshot = SimpleNamespace(content_text=text, content_sha256=digest)

    with pytest.raises(ValueError, match="evidence"):
        validate_evidence_snapshot(snapshot)


@pytest.mark.asyncio
async def test_automation_revision_writer_waits_for_live_regeneration_fence(monkeypatch):
    from app.automations.telegram.handlers import _require_automation_variant_write_allowed
    from app.generation.revision_fence import RegenerationFenceConflict
    from app.jobs.errors import RetryableJobError

    variant_id = uuid4()

    async def reject(session, **kwargs):
        assert kwargs == {"variant_id": variant_id}
        raise RegenerationFenceConflict("Variant regeneration is in progress")

    monkeypatch.setattr(
        "app.automations.telegram.process_operations.require_revision_write_allowed",
        reject,
    )
    with pytest.raises(RetryableJobError) as caught:
        await _require_automation_variant_write_allowed(SimpleNamespace(), variant_id)

    assert caught.value.code == "telegram_variant_regeneration_in_progress"


class ProbeStop(BaseException):
    pass


class ProbeExecutor:
    async def run(self, *args, **kwargs):
        raise ProbeStop


class CapturingCodexProvider:
    provider_name = "codex"

    def __init__(self, profile):
        self.inner = CodexGenerationProvider(executor=ProbeExecutor(), profile=profile)
        self.request = None
        self.validation_error = None

    async def generate(self, request):
        self.request = request
        try:
            return await self.inner.generate(request)
        except ValueError as exc:
            self.validation_error = exc
            raise ProbeStop from None


class ProbeResolver:
    def __init__(self, profile, provider):
        self.profile = profile
        self.provider = provider

    async def resolve(self, profile, model_override):
        return ResolvedProviderProfile(
            profile_id=profile.id,
            provider_type="codex",
            model=profile.default_model,
            provider=self.provider,
        )


class AsyncContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class HandlerProbeSession:
    def __init__(self, values, dispatch, link):
        self.values = list(values)
        self.dispatch = dispatch
        self.link = link

    def begin(self):
        return AsyncContext()

    def in_transaction(self):
        return False

    async def rollback(self):
        return None

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is AutomationDispatch:
            return self.dispatch
        return next((value for value in self.values if isinstance(value, entity)), None)

    async def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is StoryEvidenceLink:
            return [self.link]
        if entity in {MediaAsset, GenerationAttempt}:
            return []
        return [value for value in self.values if isinstance(value, entity)]

    async def get(self, model, identifier):
        return next(
            (value for value in self.values if isinstance(value, model) and value.id == identifier),
            None,
        )

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        self.values.append(value)

    async def flush(self):
        return None


async def test_manual_route_resumes_once_successful_research_revision_is_persisted():
    profile = AIProviderProfile(
        id=uuid4(),
        name="Codex CLI",
        provider_type="codex",
        default_model="gpt-5.4",
        secret_ref=None,
        settings=default_codex_provider_settings().model_dump(mode="json"),
        enabled=True,
    )
    provider = CapturingCodexProvider(profile)
    route = AutomationRoute(
        id=uuid4(),
        source_id=uuid4(),
        destination_id=uuid4(),
        brand_profile_id=uuid4(),
        prompt_template_version_id=uuid4(),
        ai_provider_profile_id=profile.id,
        research_mode="manual",
        content_filters={"research_provider_profile_id": str(profile.id)},
        attribution_policy="preserve",
        custom_footer=None,
        retry_policy={},
    )
    story_revision = StoryRevision(id=uuid4(), story_id=uuid4(), revision_number=1)
    content_item = ContentItem(id=uuid4(), content_text="source", direction="ltr")
    source_item = SourceItem(
        id=uuid4(),
        source_id=route.source_id,
        content_item_id=content_item.id,
        external_id_raw="source:1",
        external_id_norm="source:1",
        content_text_raw="source",
    )
    text = "source"
    digest = hashlib.sha256(text.encode()).hexdigest()
    snapshot = StoryEvidenceSnapshot(
        id=uuid4(),
        story_id=story_revision.story_id,
        evidence_key="telegram.source.1",
        source_url="https://t.me/source/1",
        content_text=text,
        content_sha256=digest,
        authors=[],
        snapshot_metadata={},
    )
    link = StoryEvidenceLink(
        story_revision_id=story_revision.id,
        evidence_snapshot_id=snapshot.id,
        claim_key="telegram.source",
        relationship="supports",
    )
    prompt = PromptTemplateVersion(
        id=route.prompt_template_version_id,
        prompt_template_id=uuid4(),
        version=1,
        system_template="Locked system",
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
        secret_ref="TELEGRAM_DESTINATION_TOKEN",
        enabled=True,
        health_status="healthy",
        settings={},
    )
    dispatch = AutomationDispatch(
        id=uuid4(),
        route_id=route.id,
        source_item_id=source_item.id,
        story_revision_id=story_revision.id,
        source_key="source:1",
        source_fingerprint="f" * 64,
        source_message_ids=[1],
        dispatch_kind="live",
        status="captured",
        created_at=datetime.now(UTC),
    )
    manual_run = ResearchRun(
        id=uuid4(),
        story_id=story_revision.story_id,
        requested_mode="manual",
        provider_profile_id=profile.id,
        status="succeeded",
        query_budget=4,
        page_budget=8,
        time_budget_seconds=120,
        result_story_revision_id=story_revision.id,
        created_at=dispatch.created_at,
        finished_at=dispatch.created_at,
    )
    session = HandlerProbeSession(
        [
            route,
            story_revision,
            source_item,
            content_item,
            snapshot,
            prompt,
            brand,
            profile,
            destination,
        ],
        dispatch,
        link,
    )
    job = SimpleNamespace(
        id=uuid4(),
        payload={"dispatch_id": str(dispatch.id), "force_review": False},
        attempt_count=1,
    )
    handler = build_telegram_process_handler(ProbeResolver(profile, provider))

    from app.jobs.errors import NeedsReviewJobError

    with pytest.raises(NeedsReviewJobError, match="Manual research"):
        await handler(job, JobContext(session=session, providers=SimpleNamespace()))
    assert provider.request is None

    # Represents the operator-requested ResearchService/handler result becoming durable.
    session.values.append(manual_run)
    job.attempt_count = 2
    with pytest.raises(ProbeStop):
        await handler(job, JobContext(session=session, providers=SimpleNamespace()))

    assert provider.validation_error is None
    assert provider.request.metadata["provider_profile_id"] == str(profile.id)
    assert set(provider.request.metadata) == {
        "dispatch_id",
        "route_id",
        "evidence_snapshot_id",
        "provider_profile_id",
    }
    assert "secret" not in str(provider.request.metadata).lower()
    assert "settings" not in provider.request.metadata


async def test_manual_route_stops_for_review_until_operator_research_succeeds():
    research_profile_id = uuid4()
    route = AutomationRoute(
        id=uuid4(),
        source_id=uuid4(),
        destination_id=uuid4(),
        brand_profile_id=uuid4(),
        prompt_template_version_id=uuid4(),
        ai_provider_profile_id=uuid4(),
        research_mode="manual",
        content_filters={"research_provider_profile_id": str(research_profile_id)},
    )
    revision = StoryRevision(id=uuid4(), story_id=uuid4(), revision_number=1)
    source_item = SourceItem(id=uuid4(), source_id=route.source_id, content_item_id=uuid4())
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
        created_at=datetime.now(UTC),
    )
    session = HandlerProbeSession([route, revision, source_item], dispatch, SimpleNamespace())
    job = SimpleNamespace(
        id=uuid4(),
        payload={"dispatch_id": str(dispatch.id)},
        attempt_count=1,
    )
    from app.jobs.errors import NeedsReviewJobError

    with pytest.raises(NeedsReviewJobError, match="Manual research"):
        await build_telegram_process_handler(SimpleNamespace())(
            job, JobContext(session=session, providers=SimpleNamespace())
        )
    assert dispatch.status == "needs_review"
    assert dispatch.error_code == "telegram_manual_research_required"
    assert not any(isinstance(value, GenerationAttempt) for value in session.values)
