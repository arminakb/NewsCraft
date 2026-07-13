from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.content_packs import get_variant_revision
from app.api.telegram_drafts import (
    TelegramContentHashIn,
    TelegramDraftEditIn,
    approve_telegram_draft,
    edit_telegram_draft,
    publish_telegram_draft,
)
from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.handlers import (
    build_telegram_process_handler,
    generation_input_hash,
)
from app.db.models import ContentItem, ItemMedia, MediaAsset, Source, SourceItem
from app.db.session import get_session
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    ContentPack,
    GenerationAttempt,
    GenerationRun,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.providers.fake import DeterministicFakeProvider
from app.generation.providers.openrouter import OpenRouterRetryableError
from app.generation.providers.profiles import ResolvedProviderProfile
from app.generation.providers.registry import build_default_provider_registry
from app.generation.telegram_schema import TelegramRewriteOutput
from app.jobs.errors import NeedsReviewJobError, RetryableJobError
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext
from app.jobs.types import JobOrigin
from app.main import app
from app.publishing.models import Destination, PublishJob
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision


class FakeProfileResolver:
    def __init__(self, provider=None) -> None:
        self.calls = []
        self.provider = provider or DeterministicFakeProvider(
            output={"body": "بازنویسی", "parse_mode": "HTML", "buttons": []}
        )

    async def resolve(self, profile, model_override):
        self.calls.append((profile.id, model_override))
        return ResolvedProviderProfile(
            profile_id=profile.id,
            provider_type="fake",
            model=model_override or profile.default_model or "fake-v1",
            provider=self.provider,
        )


class PausingProvider(DeterministicFakeProvider):
    def __init__(self, session_factory) -> None:
        super().__init__(output={"body": "بازنویسی", "parse_mode": "HTML", "buttons": []})
        self.session_factory = session_factory

    async def generate(self, request):
        async with self.session_factory() as session:
            control = await session.get(AutomationControl, "global")
            control.global_pause = True
            await session.commit()
        return await super().generate(request)


class RetryableProvider:
    provider_name = "openrouter"

    async def generate(self, request):
        raise OpenRouterRetryableError(code="openrouter_http_429", message="rate limited")


class BlockingProvider(DeterministicFakeProvider):
    def __init__(self) -> None:
        super().__init__(output={"body": "ordered", "parse_mode": "HTML", "buttons": []})
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, request):
        self.entered.set()
        await self.release.wait()
        return await super().generate(request)


class BlockingFailureProvider:
    provider_name = "openrouter"

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, request):
        self.entered.set()
        await self.release.wait()
        raise OpenRouterRetryableError(code="late_failure", message="late failure")


def durable_request_payload(
    *,
    dispatch,
    route,
    snapshot,
    source_item,
    prompt,
    job,
    active_generation_attempt_id=None,
):
    payload = {
        "semantic": {
            "dispatch_id": str(dispatch.id),
            "route_id": str(route.id),
            "story_revision_id": str(dispatch.story_revision_id),
            "evidence_snapshot_id": str(snapshot.id),
            "prompt_template_version_id": str(prompt.id),
            "prompt_checksum": prompt.checksum_sha256,
            "provider_profile_id": str(route.ai_provider_profile_id),
            "requested_model": "fake-route-model",
            "selected_model": "fake-route-model",
        },
        "input": {
            "source_text": snapshot.content_text,
            "source_url": snapshot.source_url,
            "source_channel": source_item.external_id_norm,
            "language": "fa",
            "direction": "rtl",
            "attribution_policy": "preserve",
            "custom_footer": None,
        },
        "execution": {
            "active_workflow_job_id": str(job.id),
            "active_workflow_attempt": job.attempt_count,
        },
    }
    if active_generation_attempt_id is not None:
        payload["execution"]["active_generation_attempt_id"] = str(active_generation_attempt_id)
    return payload


async def seed_dispatch(
    session,
    *,
    route_name: str = "Route",
    publishing_policy: str = "review_required",
    allow_auto: bool = False,
    shared: dict | None = None,
):
    shared = shared or {}
    source = shared.get("source") or Source(
        platform="telegram_public",
        name="Source",
        source_group="telegram",
        language_hint="fa",
    )
    destination = shared.get("destination") or Destination(
        name="Destination",
        platform="telegram",
        target_ref="@destination",
        secret_ref="TELEGRAM_DESTINATION_TOKEN",
        enabled=True,
        health_status="healthy",
        settings={"allow_auto_publish": allow_auto},
    )
    brand = shared.get("brand") or BrandProfile(
        name="Brand",
        output_language="fa",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
    )
    prompt_template = shared.get("prompt_template") or PromptTemplate(
        purpose_key="telegram_rewrite",
        name="Telegram rewrite",
    )
    provider = shared.get("provider") or AIProviderProfile(
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        settings={},
        enabled=True,
    )
    for value in (source, destination, brand, prompt_template, provider):
        session.add(value)
    await session.flush()
    prompt = shared.get("prompt") or PromptTemplateVersion(
        prompt_template_id=prompt_template.id,
        version=1,
        system_template="Rewrite truthfully",
        user_template=(
            "{source_text}\n{source_url}\n{source_channel}\n{language}\n{direction}\n"
            "{attribution_policy}\n{custom_footer}"
        ),
        output_schema_version="telegram_rewrite.v1",
        output_schema=TelegramRewriteOutput.model_json_schema(),
        checksum_sha256="a" * 64,
        is_active=True,
    )
    session.add(prompt)
    await session.flush()
    route = AutomationRoute(
        name=route_name,
        source_id=source.id,
        destination_id=destination.id,
        brand_profile_id=brand.id,
        prompt_template_version_id=prompt.id,
        ai_provider_profile_id=provider.id,
        access_mode="public_html",
        content_filters={"model": "fake-route-model"},
        media_policy="omit",
        attribution_policy="preserve",
        publishing_policy=publishing_policy,
        retry_policy={
            "max_attempts": 3,
            "base_delay_seconds": 30,
            "max_delay_seconds": 90,
        },
        cursor_state={"status": "ready"},
        enabled=True,
    )
    session.add(route)

    content_item = ContentItem(
        item_type="telegram_post",
        content_text="متن منبع",
        language_code="fa",
        direction="rtl",
        sort_at=datetime(2026, 7, 12, tzinfo=UTC),
        date_parse_status="parsed",
    )
    session.add(content_item)
    await session.flush()
    source_item = SourceItem(
        source_id=source.id,
        content_item_id=content_item.id,
        external_id_raw=f"telegram:{route_name}",
        external_id_norm=f"telegram:{route_name}",
        source_url=f"https://t.me/source/{route_name}",
        source_url_norm=f"https://t.me/source/{route_name}",
        content_text_raw="متن منبع",
    )
    session.add(source_item)
    story = shared.get("story") or Story(
        title="Story",
        status="telegram_provisional",
        primary_language="fa",
    )
    session.add(story)
    await session.flush()
    revision_number = int(shared.get("story_revision_number", 0)) + 1
    shared["story_revision_number"] = revision_number
    story_revision = StoryRevision(
        story_id=story.id,
        revision_number=revision_number,
        narrative="متن منبع",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[],
        created_by="telegram_capture",
    )
    session.add(story_revision)
    await session.flush()
    digest = hashlib.sha256("متن منبع".encode()).hexdigest()
    snapshot = StoryEvidenceSnapshot(
        story_id=story.id,
        content_item_id=content_item.id,
        evidence_key=f"telegram.source.{route_name}",
        source_url=source_item.source_url,
        content_text="متن منبع",
        content_sha256=digest,
        authors=[],
        snapshot_metadata={},
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        StoryEvidenceLink(
            story_revision_id=story_revision.id,
            evidence_snapshot_id=snapshot.id,
            claim_key="telegram.source",
            relationship="supports",
        )
    )
    dispatch = AutomationDispatch(
        route_id=route.id,
        source_item_id=source_item.id,
        story_revision_id=story_revision.id,
        source_key=f"source:{route_name}",
        source_fingerprint=uuid4().hex,
        source_message_ids=[revision_number],
        dispatch_kind="live",
        status="captured",
    )
    job = WorkflowJob(
        job_type="telegram.route.process",
        payload={},
        idempotency_key=f"telegram-process:{route.id}:{route_name}",
        origin=JobOrigin.AUTOMATION,
        status="running",
        attempt_count=1,
        max_attempts=3,
    )
    session.add_all([dispatch, job])
    await session.flush()
    job.payload = {"dispatch_id": str(dispatch.id), "force_review": False}
    shared.update(
        {
            "source": source,
            "destination": destination,
            "brand": brand,
            "prompt_template": prompt_template,
            "prompt": prompt,
            "provider": provider,
            "story": story,
        }
    )
    return dispatch, job, shared


@pytest.mark.asyncio
async def test_process_dispatch_persists_exact_review_revision_and_resumes_idempotently(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session)
        dispatch_id = dispatch.id
        job_id = job.id

    resolver = FakeProfileResolver()
    handler = build_telegram_process_handler(resolver)
    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        result = await handler(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
    assert result["review_required"] is True
    assert result["publish_job_id"] is None

    async with session_factory() as session:
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        revision = await session.get(PlatformVariantRevision, dispatch.variant_revision_id)
        run = await session.get(GenerationRun, dispatch.generation_run_id)
        attempt = await session.scalar(select(GenerationAttempt).where(GenerationAttempt.generation_run_id == run.id))
        assert revision.approval_state == "pending_review"
        assert revision.generation_attempt_id == attempt.id
        assert revision.revision_number == 1
        assert revision.parent_revision_id is None
        assert revision.content["source_item_id"] == str(dispatch.source_item_id)
        assert revision.content["direction"] == "rtl"
        assert revision.evidence_map[0]["excerpt_sha256"]
        assert revision.validation_results == [
            {"gate": "telegram_schema", "ok": True, "reason": None},
            {"gate": "evidence", "ok": True, "reason": None},
            {"gate": "media", "ok": True, "reason": None},
        ]
        assert run.status == attempt.status == "completed"
        assert generation_input_hash(run.request_payload) == run.input_hash
        assert resolver.calls == [(run.provider_profile_id, "fake-route-model")]

        await session.commit()
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        replay = await handler(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
        assert replay["revision_id"] == str(revision.id)
        assert replay["idempotent"] is True
        assert len(resolver.calls) == 1


@pytest.mark.asyncio
async def test_auto_publish_creates_one_durable_intent_without_remote_call(session_factory):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(
                session,
                publishing_policy="auto_publish",
                allow_auto=True,
            )
        dispatch_id = dispatch.id
        job_id = job.id

    handler = build_telegram_process_handler(FakeProfileResolver())
    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        result = await handler(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
    assert result["review_required"] is False
    assert result["publish_job_id"]

    async with session_factory() as session:
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        revision = await session.get(PlatformVariantRevision, dispatch.variant_revision_id)
        publish_job = await session.get(PublishJob, dispatch.publish_job_id)
        assert revision.approval_state == "approved"
        assert publish_job.platform_variant_revision_id == revision.id
        assert publish_job.payload_hash == revision.content_hash
        assert publish_job.workflow_job_id is not None


@pytest.mark.asyncio
async def test_auto_gate_reloads_global_pause_after_provider_call(session_factory):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(
                session,
                publishing_policy="auto_publish",
                allow_auto=True,
            )
        dispatch_id = dispatch.id
        job_id = job.id

    resolver = FakeProfileResolver(PausingProvider(session_factory))
    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        result = await build_telegram_process_handler(resolver)(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
    assert result["review_required"] is True
    assert result["publish_job_id"] is None

    async with session_factory() as session:
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        revision = await session.get(PlatformVariantRevision, dispatch.variant_revision_id)
        assert revision.approval_state == "pending_review"
        assert revision.approval_note == "global_pause"


@pytest.mark.asyncio
async def test_retryable_provider_failure_persists_attempt_and_route_retry_time(session_factory):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session)
        dispatch_id = dispatch.id
        job_id = job.id

    resolver = FakeProfileResolver(RetryableProvider())
    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        with pytest.raises(RetryableJobError) as caught:
            await build_telegram_process_handler(resolver)(
                job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )
        assert caught.value.retry_at is not None
        assert caught.value.retry_at.tzinfo is not None

    async with session_factory() as session:
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        run = await session.get(GenerationRun, dispatch.generation_run_id)
        attempt = await session.scalar(select(GenerationAttempt).where(GenerationAttempt.generation_run_id == run.id))
        assert run.status == attempt.status == "failed"
        assert run.error_class == attempt.error_class == "retryable"
        assert attempt.error_code == "openrouter_http_429"
        assert dispatch.status == "retryable"
        assert "telegram.generation.failed" in set(
            await session.scalars(select(WorkflowEvent.event_type).where(WorkflowEvent.workflow_job_id == job_id))
        )


@pytest.mark.asyncio
async def test_invalid_structured_output_is_durable_needs_review_not_retryable(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session)
        dispatch_id = dispatch.id
        job_id = job.id

    invalid = DeterministicFakeProvider(output={"body": "<script>unsafe</script>", "parse_mode": "HTML", "buttons": []})
    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        with pytest.raises(NeedsReviewJobError) as caught:
            await build_telegram_process_handler(FakeProfileResolver(invalid))(
                job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )
        assert caught.value.code == "telegram_generation_output_invalid"

    async with session_factory() as session:
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        run = await session.get(GenerationRun, dispatch.generation_run_id)
        attempt = await session.scalar(select(GenerationAttempt).where(GenerationAttempt.generation_run_id == run.id))
        assert dispatch.status == "needs_review"
        assert run.error_class == attempt.error_class == "needs_review"
        assert attempt.validation_errors


@pytest.mark.asyncio
async def test_completed_durable_output_resumes_revision_without_another_provider_call(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session)
            route = await session.get(AutomationRoute, dispatch.route_id)
            source_item = await session.get(SourceItem, dispatch.source_item_id)
            prompt = await session.get(
                PromptTemplateVersion,
                route.prompt_template_version_id,
            )
            link = await session.scalar(
                select(StoryEvidenceLink).where(StoryEvidenceLink.story_revision_id == dispatch.story_revision_id)
            )
            snapshot = await session.get(StoryEvidenceSnapshot, link.evidence_snapshot_id)
            request_payload = durable_request_payload(
                dispatch=dispatch,
                route=route,
                snapshot=snapshot,
                source_item=source_item,
                prompt=prompt,
                job=job,
            )
            run = GenerationRun(
                story_revision_id=dispatch.story_revision_id,
                provider_profile_id=route.ai_provider_profile_id,
                prompt_template_version_id=route.prompt_template_version_id,
                requested_model="fake-route-model",
                status="completed",
                input_hash=generation_input_hash(request_payload),
                request_payload=request_payload,
                output_payload={
                    "provider": "fake",
                    "requested_model": "fake-route-model",
                    "resolved_model": "fake-route-model",
                    "output": {
                        "body": "durable output",
                        "parse_mode": "HTML",
                        "buttons": [],
                    },
                    "raw_text": "{}",
                    "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0},
                    "finish_reason": "stop",
                },
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
            session.add(run)
            await session.flush()
            attempt = GenerationAttempt(
                generation_run_id=run.id,
                attempt_number=1,
                provider="fake",
                requested_model="fake-route-model",
                resolved_model="fake-route-model",
                prompt_snapshot={},
                response_payload=run.output_payload,
                usage=run.output_payload["usage"],
                validation_errors=[],
                status="completed",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
            session.add(attempt)
            request_payload["execution"]["active_generation_attempt_id"] = str(attempt.id)
            run.request_payload = request_payload
            dispatch.generation_run_id = run.id
        job_id = job.id

    resolver = FakeProfileResolver()
    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        result = await build_telegram_process_handler(resolver)(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
        revision = await session.get(
            PlatformVariantRevision,
            UUID(result["revision_id"]),
        )
        assert revision.content["body"] == "durable output"
        assert resolver.calls == []


@pytest.mark.asyncio
async def test_retry_fences_stale_generation_attempt_and_allocates_next_attempt(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session)
            route = await session.get(AutomationRoute, dispatch.route_id)
            job.attempt_count = 2
            source_item = await session.get(SourceItem, dispatch.source_item_id)
            prompt = await session.get(
                PromptTemplateVersion,
                route.prompt_template_version_id,
            )
            link = await session.scalar(
                select(StoryEvidenceLink).where(StoryEvidenceLink.story_revision_id == dispatch.story_revision_id)
            )
            snapshot = await session.get(StoryEvidenceSnapshot, link.evidence_snapshot_id)
            request_payload = durable_request_payload(
                dispatch=dispatch,
                route=route,
                snapshot=snapshot,
                source_item=source_item,
                prompt=prompt,
                job=SimpleNamespace(id=job.id, attempt_count=1),
            )
            run = GenerationRun(
                story_revision_id=dispatch.story_revision_id,
                provider_profile_id=route.ai_provider_profile_id,
                prompt_template_version_id=route.prompt_template_version_id,
                requested_model="fake-route-model",
                status="running",
                input_hash=generation_input_hash(request_payload),
                request_payload=request_payload,
                output_payload={},
                started_at=datetime.now(UTC),
            )
            session.add(run)
            await session.flush()
            stale_attempt = GenerationAttempt(
                generation_run_id=run.id,
                attempt_number=1,
                provider="fake",
                requested_model="fake-route-model",
                prompt_snapshot={},
                response_payload={},
                usage={},
                validation_errors=[],
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(stale_attempt)
            await session.flush()
            request_payload["execution"]["active_generation_attempt_id"] = str(stale_attempt.id)
            run.request_payload = request_payload
            dispatch.generation_run_id = run.id
        job_id = job.id
        run_id = run.id
        dispatch_id = dispatch.id

    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        await build_telegram_process_handler(FakeProfileResolver())(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )

    async with session_factory() as session:
        attempts = list(
            await session.scalars(
                select(GenerationAttempt)
                .where(GenerationAttempt.generation_run_id == run_id)
                .order_by(GenerationAttempt.attempt_number)
            )
        )
        assert [attempt.attempt_number for attempt in attempts] == [1, 2]
        assert attempts[0].error_code == "stale_generation_attempt"
        assert attempts[1].status == "completed"
        run = await session.get(GenerationRun, run_id)
        assert generation_input_hash(run.request_payload) == run.input_hash
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        assert dispatch.error_code is None
        assert dispatch.error_message is None


@pytest.mark.asyncio
async def test_late_stale_failure_cannot_clobber_winning_attempt_or_revision(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session)
        dispatch_id = dispatch.id
        job_id = job.id

    stale_provider = BlockingFailureProvider()

    async def run_stale():
        async with session_factory() as session:
            job = await session.get(WorkflowJob, job_id)
            await session.commit()
            return await build_telegram_process_handler(FakeProfileResolver(stale_provider))(
                job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )

    stale_task = asyncio.create_task(run_stale())
    await stale_provider.entered.wait()
    async with session_factory() as session:
        async with session.begin():
            retry_job = await session.get(WorkflowJob, job_id)
            retry_job.attempt_count = 2
        winning = await build_telegram_process_handler(FakeProfileResolver())(
            retry_job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
    stale_provider.release.set()
    stale_result = await stale_task
    assert stale_result["superseded"] is True

    async with session_factory() as session:
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        run = await session.get(GenerationRun, dispatch.generation_run_id)
        assert dispatch.variant_revision_id == UUID(winning["revision_id"])
        assert dispatch.status == "pending_review"
        assert run.status == "completed"
        attempts = list(
            await session.scalars(
                select(GenerationAttempt)
                .where(GenerationAttempt.generation_run_id == run.id)
                .order_by(GenerationAttempt.attempt_number)
            )
        )
        assert attempts[0].error_code == "stale_generation_attempt"
        assert attempts[1].status == "completed"


@pytest.mark.asyncio
async def test_concurrent_routes_allocate_global_revision_numbers_without_collision(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            first, first_job, shared = await seed_dispatch(session, route_name="A")
            second, second_job, _ = await seed_dispatch(
                session,
                route_name="B",
                shared=shared,
            )
            second.story_revision_id = first.story_revision_id
        ids = (first.id, second.id)
        job_ids = (first_job.id, second_job.id)

    async def run(job_id):
        async with session_factory() as session:
            job = await session.get(WorkflowJob, job_id)
            await session.commit()
            return await build_telegram_process_handler(FakeProfileResolver())(
                job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )

    await asyncio.gather(*(run(job_id) for job_id in job_ids))

    async with session_factory() as session:
        dispatches = [await session.get(AutomationDispatch, dispatch_id) for dispatch_id in ids]
        revisions = [
            await session.get(PlatformVariantRevision, dispatch.variant_revision_id) for dispatch in dispatches
        ]
        assert {revision.revision_number for revision in revisions} == {1, 2}
        assert len({revision.platform_variant_id for revision in revisions}) == 1


@pytest.mark.asyncio
async def test_same_route_reverse_completion_defers_later_until_parent_is_linked(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            first, first_job, shared = await seed_dispatch(session, route_name="ordered-A")
            second, second_job, _ = await seed_dispatch(
                session,
                route_name="ordered-B",
                shared=shared,
            )
            second.route_id = first.route_id
            second.story_revision_id = first.story_revision_id
        ordered = sorted(
            ((first, first_job), (second, second_job)),
            key=lambda pair: (pair[0].created_at, pair[0].id),
        )
        (earlier, earlier_job), (later, later_job) = ordered
        earlier_id, later_id = earlier.id, later.id
        earlier_job_id, later_job_id = earlier_job.id, later_job.id

    blocker = BlockingProvider()

    async def run_earlier():
        async with session_factory() as session:
            job = await session.get(WorkflowJob, earlier_job_id)
            await session.commit()
            return await build_telegram_process_handler(FakeProfileResolver(blocker))(
                job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )

    earlier_task = asyncio.create_task(run_earlier())
    await blocker.entered.wait()
    async with session_factory() as session:
        job = await session.get(WorkflowJob, later_job_id)
        await session.commit()
        with pytest.raises(RetryableJobError) as waiting:
            await build_telegram_process_handler(FakeProfileResolver())(
                job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )
        assert waiting.value.code == "telegram_route_lineage_waiting"
    blocker.release.set()
    await earlier_task

    resolver = FakeProfileResolver()
    async with session_factory() as session:
        async with session.begin():
            job = await session.get(WorkflowJob, later_job_id)
            job.attempt_count = 2
        await build_telegram_process_handler(resolver)(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
        assert resolver.calls == []

    async with session_factory() as session:
        earlier = await session.get(AutomationDispatch, earlier_id)
        later = await session.get(AutomationDispatch, later_id)
        earlier_revision = await session.get(
            PlatformVariantRevision,
            earlier.variant_revision_id,
        )
        later_revision = await session.get(
            PlatformVariantRevision,
            later.variant_revision_id,
        )
        assert later_revision.parent_revision_id == earlier_revision.id
        assert later_revision.revision_number == earlier_revision.revision_number + 1
        assert later.error_code is None
        assert later.error_message is None
        later_events = set(
            await session.scalars(select(WorkflowEvent.event_type).where(WorkflowEvent.workflow_job_id == later_job_id))
        )
        assert "telegram.process.deferred" in later_events
        assert "telegram.generation.failed" not in later_events


@pytest.mark.asyncio
async def test_simultaneous_same_route_finalization_has_no_dispatch_route_deadlock(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            first, first_job, shared = await seed_dispatch(session, route_name="simultaneous-A")
            second, second_job, _ = await seed_dispatch(
                session,
                route_name="simultaneous-B",
                shared=shared,
            )
            second.route_id = first.route_id
            second.story_revision_id = first.story_revision_id
        ordered = sorted(
            ((first, first_job), (second, second_job)),
            key=lambda pair: (pair[0].created_at, pair[0].id),
        )
        dispatch_ids = [pair[0].id for pair in ordered]
        job_ids = [pair[1].id for pair in ordered]

    providers = [BlockingProvider(), BlockingProvider()]

    async def run(index):
        async with session_factory() as session:
            job = await session.get(WorkflowJob, job_ids[index])
            await session.commit()
            return await build_telegram_process_handler(FakeProfileResolver(providers[index]))(
                job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )

    tasks = [asyncio.create_task(run(index)) for index in range(2)]
    await asyncio.gather(*(provider.entered.wait() for provider in providers))
    for provider in providers:
        provider.release.set()
    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=True),
        timeout=15,
    )
    waiting_indexes = [index for index, result in enumerate(results) if isinstance(result, RetryableJobError)]
    assert len(waiting_indexes) <= 1
    for index in waiting_indexes:
        async with session_factory() as session:
            async with session.begin():
                job = await session.get(WorkflowJob, job_ids[index])
                job.attempt_count = 2
            await build_telegram_process_handler(FakeProfileResolver())(
                job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )

    async with session_factory() as session:
        dispatches = [await session.get(AutomationDispatch, dispatch_id) for dispatch_id in dispatch_ids]
        revisions = [
            await session.get(PlatformVariantRevision, dispatch.variant_revision_id) for dispatch in dispatches
        ]
        assert revisions[1].parent_revision_id == revisions[0].id


@pytest.mark.asyncio
async def test_interleaved_routes_keep_global_numbers_and_route_specific_parent(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            first, first_job, shared = await seed_dispatch(session, route_name="A")
            second, second_job, _ = await seed_dispatch(
                session,
                route_name="B",
                shared=shared,
            )
            second.story_revision_id = first.story_revision_id
            edited, edit_job, _ = await seed_dispatch(
                session,
                route_name="A-edit",
                shared=shared,
            )
            edited.route_id = first.route_id
            edited.dispatch_kind = "source_edit"
        dispatch_ids = (first.id, second.id, edited.id)
        job_ids = (first_job.id, second_job.id, edit_job.id)

    for job_id in job_ids:
        async with session_factory() as session:
            job = await session.get(WorkflowJob, job_id)
            await session.commit()
            await build_telegram_process_handler(FakeProfileResolver())(
                job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )

    async with session_factory() as session:
        dispatches = [await session.get(AutomationDispatch, dispatch_id) for dispatch_id in dispatch_ids]
        revisions = [
            await session.get(PlatformVariantRevision, dispatch.variant_revision_id) for dispatch in dispatches
        ]
        assert [revision.revision_number for revision in revisions] == [1, 2, 3]
        assert revisions[1].parent_revision_id is None
        assert revisions[2].parent_revision_id == revisions[0].id
        assert revisions[2].approval_state == "pending_review"
        assert list(await session.scalars(select(PublishJob))) == []
        event_types = set(
            await session.scalars(select(WorkflowEvent.event_type).where(WorkflowEvent.workflow_job_id == job_ids[2]))
        )
        assert "telegram.generation.completed" in event_types
        assert "telegram.source_edit.revision_created" in event_types


@pytest.mark.asyncio
async def test_manual_child_approval_and_publish_bind_exact_hash_and_route_ancestry(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session)
        dispatch_id = dispatch.id
        job_id = job.id
    handler = build_telegram_process_handler(FakeProfileResolver())
    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        generated = await handler(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )

    async with session_factory() as session:
        edited = await edit_telegram_draft(
            UUID(generated["revision_id"]),
            TelegramDraftEditIn.model_validate(
                {
                    "content": {
                        "body": "ویرایش اپراتور",
                        "parse_mode": "HTML",
                        "buttons": [],
                    },
                    "media_asset_ids": [],
                }
            ),
            session,
        )
        child_id = edited["id"]
        child_hash = edited["content_hash"]
        assert edited["parent_revision_id"] == UUID(generated["revision_id"])
        assert edited["generation_attempt_id"] is None
        assert edited["approval_state"] == "pending_review"
        exact = await get_variant_revision(child_id, session)
        assert exact["id"] == child_id
        assert exact["validation_results"] == [{"gate": "telegram_schema", "ok": True, "reason": None}]
        assert exact["origin"] == "operator"

    async with session_factory() as session:
        with pytest.raises(HTTPException) as stale:
            await approve_telegram_draft(
                child_id,
                TelegramContentHashIn(content_hash="b" * 64),
                session,
            )
        assert stale.value.status_code == 409

    async with session_factory() as session:
        approved = await approve_telegram_draft(
            child_id,
            TelegramContentHashIn(content_hash=child_hash),
            session,
        )
        assert approved["approval_state"] == "approved"

    async with session_factory() as session:
        published = await publish_telegram_draft(
            child_id,
            TelegramContentHashIn(content_hash=child_hash),
            session,
        )
        publish_job_id = published["job"]["publish_job_id"]

    async with session_factory() as session:
        replayed = await publish_telegram_draft(
            child_id,
            TelegramContentHashIn(content_hash=child_hash),
            session,
        )
        assert replayed["job"]["publish_job_id"] == publish_job_id
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        assert dispatch.publish_job_id is None
        jobs = list(
            await session.scalars(select(PublishJob).where(PublishJob.platform_variant_revision_id == child_id))
        )
        assert len(jobs) == 1


@pytest.mark.asyncio
async def test_draft_http_contract_enforces_states_filters_and_telegram_platform(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session)
        route_id = dispatch.route_id
        job_id = job.id
    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        generated = await build_telegram_process_handler(FakeProfileResolver())(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
        generated_id = UUID(generated["revision_id"])

    async with session_factory() as session:
        async with session.begin():
            generated_revision = await session.get(PlatformVariantRevision, generated_id)
            telegram_variant = await session.get(
                PlatformVariant,
                generated_revision.platform_variant_id,
            )
            pack = await session.get(ContentPack, telegram_variant.content_pack_id)
            other_variant = PlatformVariant(content_pack_id=pack.id, platform="linkedin")
            session.add(other_variant)
            await session.flush()
            other_revision = PlatformVariantRevision(
                platform_variant_id=other_variant.id,
                revision_number=1,
                content={},
                content_hash="f" * 64,
                evidence_map=[],
                validation_results=[],
                approval_state="pending_review",
                created_by="test",
            )
            session.add(other_revision)
        other_id = other_revision.id

    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            listed = await client.get(
                "/telegram/drafts",
                params={"route_id": str(route_id), "approval_state": "pending_review"},
            )
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()] == [str(generated_id)]
            assert (
                await client.get(
                    "/telegram/drafts",
                    params={"approval_state": "review_required"},
                )
            ).status_code == 422
            assert (await client.get(f"/telegram/drafts/{uuid4()}")).status_code == 404
            assert (await client.get(f"/telegram/drafts/{other_id}")).status_code == 404
            assert (
                await client.post(
                    f"/telegram/drafts/{other_id}/approve",
                    json={"content_hash": "f" * 64},
                )
            ).status_code == 404

            edited = await client.post(
                f"/telegram/drafts/{generated_id}/revisions",
                json={
                    "content": {
                        "body": "HTTP edit",
                        "parse_mode": "HTML",
                        "buttons": [],
                    },
                    "media_asset_ids": [],
                },
            )
            assert edited.status_code == 201
            child = edited.json()
            assert child["approval_state"] == "pending_review"
            assert (
                await client.post(
                    f"/telegram/drafts/{child['id']}/approve",
                    json={"content_hash": "0" * 64},
                )
            ).status_code == 409
            approved = await client.post(
                f"/telegram/drafts/{child['id']}/approve",
                json={"content_hash": child["content_hash"]},
            )
            assert approved.status_code == 200
            assert approved.json()["approval_state"] == "approved"
            published = await client.post(
                f"/telegram/drafts/{child['id']}/publish",
                json={"content_hash": child["content_hash"]},
            )
            assert published.status_code == 202

            rejected_child = await client.post(
                f"/telegram/drafts/{generated_id}/revisions",
                json={
                    "content": {
                        "body": "Reject me",
                        "parse_mode": "HTML",
                        "buttons": [],
                    },
                    "media_asset_ids": [],
                },
            )
            rejected = await client.post(
                f"/telegram/drafts/{rejected_child.json()['id']}/reject",
                json={
                    "content_hash": rejected_child.json()["content_hash"],
                    "note": "operator rejected",
                },
            )
            assert rejected.status_code == 200
            assert rejected.json()["approval_state"] == "rejected"
            assert (
                await client.post(
                    f"/telegram/drafts/{rejected_child.json()['id']}/approve",
                    json={"content_hash": rejected_child.json()["content_hash"]},
                )
            ).status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_manual_edit_rejects_cross_story_and_unrelated_or_unready_preserve_media(
    session_factory,
):
    async with session_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session)
            route = await session.get(AutomationRoute, dispatch.route_id)
            route.media_policy = "preserve"
        dispatch_id = dispatch.id
        job_id = job.id
    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        await session.commit()
        generated = await build_telegram_process_handler(FakeProfileResolver())(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
        generated_id = UUID(generated["revision_id"])

    async with session_factory() as session:
        async with session.begin():
            unrelated = MediaAsset(
                original_url="https://example.com/unrelated.jpg",
                normalized_url="https://example.com/unrelated.jpg",
                url_hash="1" * 64,
                kind="image",
                source_field="test",
                checksum_sha256="2" * 64,
                storage_path="/tmp/unrelated.jpg",
                fetch_status="downloaded",
            )
            session.add(unrelated)
            await session.flush()
        unrelated_id = unrelated.id

    async with session_factory() as session:
        with pytest.raises(HTTPException) as unrelated_error:
            await edit_telegram_draft(
                generated_id,
                TelegramDraftEditIn.model_validate(
                    {
                        "content": {
                            "body": "unrelated",
                            "parse_mode": "HTML",
                            "buttons": [],
                        },
                        "media_asset_ids": [unrelated_id],
                    }
                ),
                session,
            )
        assert unrelated_error.value.status_code == 422

    async with session_factory() as session:
        async with session.begin():
            dispatch = await session.get(AutomationDispatch, dispatch_id)
            source_item = await session.get(SourceItem, dispatch.source_item_id)
            asset = await session.get(MediaAsset, unrelated_id)
            asset.fetch_status = "remote_only"
            asset.storage_path = None
            asset.checksum_sha256 = None
            session.add(
                ItemMedia(
                    content_item_id=source_item.content_item_id,
                    media_asset_id=asset.id,
                    role="inline",
                    sort_order=0,
                    extracted_from="test",
                )
            )
    async with session_factory() as session:
        with pytest.raises(HTTPException) as unready_error:
            await edit_telegram_draft(
                generated_id,
                TelegramDraftEditIn.model_validate(
                    {
                        "content": {
                            "body": "unready",
                            "parse_mode": "HTML",
                            "buttons": [],
                        },
                        "media_asset_ids": [unrelated_id],
                    }
                ),
                session,
            )
        assert unready_error.value.status_code == 422

    async with session_factory() as session:
        async with session.begin():
            other_story = Story(
                title="Other story",
                status="telegram_provisional",
                primary_language="fa",
            )
            session.add(other_story)
            await session.flush()
            text = "other evidence"
            digest = hashlib.sha256(text.encode()).hexdigest()
            other_snapshot = StoryEvidenceSnapshot(
                story_id=other_story.id,
                evidence_key="other.story.evidence",
                source_url="https://example.com/other",
                content_text=text,
                content_sha256=digest,
                authors=[],
                snapshot_metadata={},
            )
            session.add(other_snapshot)
            await session.flush()
            revision = await session.get(PlatformVariantRevision, generated_id)
            revision.evidence_map = [
                {
                    "evidence_snapshot_id": str(other_snapshot.id),
                    "evidence_key": other_snapshot.evidence_key,
                    "source_url": "https://example.com/other",
                    "locator": f"chars:0-{len(text)}",
                    "excerpt_sha256": digest,
                }
            ]
    async with session_factory() as session:
        with pytest.raises(HTTPException) as cross_story:
            await edit_telegram_draft(
                generated_id,
                TelegramDraftEditIn.model_validate(
                    {
                        "content": {
                            "body": "cross story",
                            "parse_mode": "HTML",
                            "buttons": [],
                        },
                        "media_asset_ids": [],
                    }
                ),
                session,
            )
        assert cross_story.value.status_code == 409
