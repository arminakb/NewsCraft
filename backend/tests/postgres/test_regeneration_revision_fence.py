from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.generation.editorial_service import (
    EditorialService,
    InvalidGenerationRequest,
    RegenerateVariantRequest,
    RevisionConflict,
)
from app.generation.handlers import build_regenerate_handler
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    ContentPack,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.platform_schemas import (
    InstagramEditPayload,
    InstagramVariantPayload,
    ManualPlatformEditRequest,
)
from app.generation.revision_fence import acquire_regeneration_fence
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext
from app.research.schemas import CitationRef
from app.stories.models import Story, StoryRevision


@pytest.mark.asyncio
async def test_committed_regeneration_fence_prevents_second_session_revision_advance(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
):
    now = datetime.now(UTC)
    story = Story(id=uuid4(), title="Fenced", status="inbox", primary_language="en")
    story_revision = StoryRevision(
        id=uuid4(),
        story_id=story.id,
        parent_revision_id=None,
        revision_number=1,
        narrative="Grounded",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[],
        created_by="generation",
    )
    brand = BrandProfile(
        id=uuid4(),
        name="Fence Newsroom",
        output_language="en",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=False,
    )
    pack = ContentPack(
        id=uuid4(),
        story_revision_id=story_revision.id,
        brand_profile_id=brand.id,
        status="draft",
    )
    variant = PlatformVariant(id=uuid4(), content_pack_id=pack.id, platform="instagram")
    base = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content={},
        content_hash="b" * 64,
        evidence_map=[],
        validation_results=[{"gate": "platform_schema", "ok": True, "reason": None}],
        approval_state="approved",
        created_by="generation",
    )
    owner_job = WorkflowJob(
        id=uuid4(),
        job_type="content_pack.regenerate",
        status="running",
        payload={},
        result={},
        priority=0,
        idempotency_key=f"fence:{uuid4()}",
        origin="manual",
        pause_sensitive=True,
        attempt_count=1,
        max_attempts=3,
        lease_owner="worker-fence",
        lease_expires_at=now + timedelta(minutes=5),
        heartbeat_at=now,
        progress=0,
    )
    db_session.add_all([story, brand, owner_job])
    await db_session.flush()
    db_session.add(story_revision)
    await db_session.flush()
    db_session.add(pack)
    await db_session.flush()
    db_session.add(variant)
    await db_session.flush()
    db_session.add(base)
    await db_session.commit()

    locked_variant = await db_session.scalar(
        select(PlatformVariant).where(PlatformVariant.id == variant.id).with_for_update()
    )
    assert locked_variant is not None
    await acquire_regeneration_fence(
        db_session,
        variant_id=variant.id,
        base_revision_id=base.id,
        base_content_hash=base.content_hash,
        workflow_job_id=owner_job.id,
        workflow_attempt=owner_job.attempt_count,
        lease_owner=owner_job.lease_owner,
        now=now,
    )
    await db_session.commit()

    citation = CitationRef(
        evidence_key="evidence:one",
        evidence_snapshot_id=uuid4(),
        source_url="https://example.com/report",
        locator="chars:0-8",
        excerpt_sha256="a" * 64,
    )
    content = InstagramVariantPayload(
        hook="Grounded",
        caption="Grounded caption",
        cta="Read",
        hashtags=[],
        alt_text="Grounded",
        carousel=[],
        citations=[citation],
        manual_checklist=["Verify"],
    )
    request = ManualPlatformEditRequest(
        base_revision_id=base.id,
        base_content_hash=base.content_hash,
        payload=InstagramEditPayload(platform="instagram", content=content),
        evidence_map=[citation],
        edit_note="Must wait for regeneration",
    )

    async with session_factory() as competing:
        with pytest.raises(RevisionConflict, match="regeneration"):
            await EditorialService(competing).edit_manual_platform_variant(variant.id, request)
        await competing.rollback()

    async with session_factory() as reopened:
        revision_count = await reopened.scalar(
            select(func.count())
            .select_from(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant.id)
        )
        assert revision_count == 1


@pytest.mark.asyncio
async def test_cached_regeneration_replay_does_not_deadlock_with_manual_edit(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    story = Story(id=uuid4(), title="Lock order", status="inbox", primary_language="en")
    story_revision = StoryRevision(
        id=uuid4(),
        story_id=story.id,
        parent_revision_id=None,
        revision_number=1,
        narrative="Grounded",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[],
        created_by="generation",
    )
    brand = BrandProfile(
        id=uuid4(),
        name="Lock Order Newsroom",
        output_language="en",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=False,
    )
    pack = ContentPack(
        id=uuid4(),
        story_revision_id=story_revision.id,
        brand_profile_id=brand.id,
        status="draft",
    )
    variant = PlatformVariant(id=uuid4(), content_pack_id=pack.id, platform="instagram")
    base = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content={},
        content_hash="b" * 64,
        evidence_map=[],
        validation_results=[{"gate": "platform_schema", "ok": True, "reason": None}],
        approval_state="approved",
        created_by="generation",
    )
    db_session.add_all([story, brand])
    await db_session.flush()
    db_session.add(story_revision)
    await db_session.flush()
    db_session.add(pack)
    await db_session.flush()
    db_session.add(variant)
    await db_session.flush()
    db_session.add(base)
    await db_session.commit()

    payload_citation = CitationRef(
        evidence_key="evidence:payload",
        evidence_snapshot_id=uuid4(),
        source_url="https://example.com/payload",
        locator="chars:0-8",
        excerpt_sha256="a" * 64,
    )
    mismatched_citation = payload_citation.model_copy(update={"evidence_key": "evidence:mismatch"})
    edit_request = ManualPlatformEditRequest(
        base_revision_id=base.id,
        base_content_hash=base.content_hash,
        payload=InstagramEditPayload(
            platform="instagram",
            content=InstagramVariantPayload(
                hook="Grounded",
                caption="Grounded caption",
                cta="Read",
                hashtags=[],
                alt_text="Grounded",
                carousel=[],
                citations=[payload_citation],
                manual_checklist=["Verify"],
            ),
        ),
        evidence_map=[mismatched_citation],
        edit_note="Exercise the real editor lock order",
    )
    edit_holds_variant = asyncio.Event()
    allow_edit_revision_lock = asyncio.Event()

    async def pause_after_edit_variant_lock(session, **kwargs):
        assert kwargs == {"variant_id": variant.id}
        edit_holds_variant.set()
        await allow_edit_revision_lock.wait()

    monkeypatch.setattr(
        "app.generation.manual_edit.require_revision_write_allowed",
        pause_after_edit_variant_lock,
    )

    def cached_replay_builder(profile_resolver):
        async def replay(job, context):
            # Cached artifact validation later locks the variant. The wrapper
            # must not already hold the current revision while waiting here.
            locked = await context.session.scalar(
                select(PlatformVariant).where(PlatformVariant.id == variant.id).with_for_update()
            )
            assert locked is not None
            return {"replayed": True}

        return replay

    monkeypatch.setattr(
        "app.generation.variant_regeneration.build_pack_generation_handler",
        cached_replay_builder,
    )
    job = SimpleNamespace(
        payload={
            "variant_id": str(variant.id),
            "base_revision_id": str(base.id),
            "base_content_hash": base.content_hash,
            "platforms": ["instagram"],
            "platform_prompt_template_version_ids": {"instagram": str(uuid4())},
            "platform_prompt_checksums": {"instagram": "c" * 64},
        }
    )

    edit_task = None
    replay_task = None
    async with (
        session_factory() as editing,
        session_factory() as replaying,
        session_factory() as observer,
    ):
        try:
            await editing.execute(text("SET LOCAL lock_timeout = '750ms'"))
            replay_pid = await replaying.scalar(text("SELECT pg_backend_pid()"))
            edit_task = asyncio.create_task(
                EditorialService(editing).edit_manual_platform_variant(
                    variant.id,
                    edit_request,
                )
            )
            await asyncio.wait_for(edit_holds_variant.wait(), timeout=2)
            replay_task = asyncio.create_task(
                build_regenerate_handler(SimpleNamespace())(
                    job,
                    JobContext(session=replaying, providers=SimpleNamespace()),
                )
            )

            deadline = asyncio.get_running_loop().time() + 2
            while True:
                wait_type = await observer.scalar(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": replay_pid},
                )
                if wait_type == "Lock":
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("regeneration replay did not wait on the editor lock")
                await asyncio.sleep(0.01)

            allow_edit_revision_lock.set()
            with pytest.raises(InvalidGenerationRequest) as edit_error:
                await edit_task
            assert edit_error.value.code == "citation_integrity"
            await editing.rollback()

            assert await asyncio.wait_for(replay_task, timeout=2) == {"replayed": True}
            await replaying.rollback()
        finally:
            allow_edit_revision_lock.set()
            for task in (edit_task, replay_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (edit_task, replay_task) if task is not None),
                return_exceptions=True,
            )
            await editing.rollback()
            await replaying.rollback()


@pytest.mark.asyncio
async def test_cached_regeneration_replay_does_not_invert_normal_pack_lock_order(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    story = Story(id=uuid4(), title="Pack lock order", status="inbox", primary_language="en")
    story_revision = StoryRevision(
        id=uuid4(),
        story_id=story.id,
        parent_revision_id=None,
        revision_number=1,
        narrative="Grounded",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[],
        created_by="generation",
    )
    brand = BrandProfile(
        id=uuid4(),
        name="Pack Lock Order Newsroom",
        output_language="en",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=False,
    )
    pack = ContentPack(
        id=uuid4(),
        story_revision_id=story_revision.id,
        brand_profile_id=brand.id,
        status="draft",
    )
    variant = PlatformVariant(id=uuid4(), content_pack_id=pack.id, platform="instagram")
    base = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content={},
        content_hash="b" * 64,
        evidence_map=[],
        validation_results=[{"gate": "platform_schema", "ok": True, "reason": None}],
        approval_state="approved",
        created_by="generation",
    )
    db_session.add_all([story, brand])
    await db_session.flush()
    db_session.add(story_revision)
    await db_session.flush()
    db_session.add(pack)
    await db_session.flush()
    db_session.add(variant)
    await db_session.flush()
    db_session.add(base)
    await db_session.commit()

    def cached_replay_builder(profile_resolver):
        async def replay(job, context):
            # Match the real pack handler's persistence order. If the wrapper
            # still holds Variant, this first Story lock completes the
            # Variant -> Story half of the old cycle.
            locked_story = await context.session.scalar(select(Story).where(Story.id == story.id).with_for_update())
            locked_pack = await context.session.scalar(
                select(ContentPack).where(ContentPack.id == pack.id).with_for_update()
            )
            locked_variant = await context.session.scalar(
                select(PlatformVariant).where(PlatformVariant.id == variant.id).with_for_update()
            )
            assert locked_story is not None
            assert locked_pack is not None
            assert locked_variant is not None
            return {"replayed": True}

        return replay

    monkeypatch.setattr(
        "app.generation.variant_regeneration.build_pack_generation_handler",
        cached_replay_builder,
    )
    job = SimpleNamespace(
        payload={
            "variant_id": str(variant.id),
            "base_revision_id": str(base.id),
            "base_content_hash": base.content_hash,
            "platforms": ["instagram"],
            "platform_prompt_template_version_ids": {"instagram": str(uuid4())},
            "platform_prompt_checksums": {"instagram": "c" * 64},
        }
    )

    replay_task = None
    async with (
        session_factory() as normal_generation,
        session_factory() as replaying,
        session_factory() as observer,
    ):
        try:
            await normal_generation.execute(text("SET LOCAL lock_timeout = '750ms'"))
            assert (
                await normal_generation.scalar(select(Story).where(Story.id == story.id).with_for_update()) is not None
            )
            assert (
                await normal_generation.scalar(select(ContentPack).where(ContentPack.id == pack.id).with_for_update())
                is not None
            )

            replay_pid = await replaying.scalar(text("SELECT pg_backend_pid()"))
            replay_task = asyncio.create_task(
                build_regenerate_handler(SimpleNamespace())(
                    job,
                    JobContext(session=replaying, providers=SimpleNamespace()),
                )
            )

            deadline = asyncio.get_running_loop().time() + 2
            while True:
                wait_type = await observer.scalar(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": replay_pid},
                )
                if wait_type == "Lock":
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("regeneration replay did not wait on the story lock")
                await asyncio.sleep(0.01)

            # This is the normal pack handler's next lock. It must remain
            # available while replay waits on Story; otherwise PostgreSQL sees
            # Story -> Variant versus Variant -> Story.
            assert (
                await normal_generation.scalar(
                    select(PlatformVariant).where(PlatformVariant.id == variant.id).with_for_update()
                )
                is not None
            )
            await normal_generation.commit()

            assert await asyncio.wait_for(replay_task, timeout=2) == {"replayed": True}
            await replaying.rollback()
        finally:
            if replay_task is not None and not replay_task.done():
                replay_task.cancel()
            if replay_task is not None:
                await asyncio.gather(replay_task, return_exceptions=True)
            await normal_generation.rollback()
            await replaying.rollback()


@pytest.mark.asyncio
async def test_regeneration_enqueue_does_not_lock_prompt_behind_variant(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
):
    story = Story(id=uuid4(), title="Enqueue lock order", status="inbox", primary_language="en")
    story_revision = StoryRevision(
        id=uuid4(),
        story_id=story.id,
        parent_revision_id=None,
        revision_number=1,
        narrative="Grounded",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[],
        created_by="generation",
    )
    brand = BrandProfile(
        id=uuid4(),
        name="Enqueue Lock Order Newsroom",
        output_language="en",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=False,
    )
    profile = AIProviderProfile(
        id=uuid4(),
        name="Enqueue Lock Provider",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    template = PromptTemplate(
        id=uuid4(),
        purpose_key="instagram_pack",
        name="Instagram enqueue lock prompt",
        description=None,
    )
    prompt = PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=template.id,
        version=1,
        system_template="Grounded system",
        user_template="Story={canonical_story_json}",
        output_schema_version="instagram_pack.v1",
        output_schema={},
        checksum_sha256="c" * 64,
        is_active=True,
        activated_at=datetime.now(UTC),
        activated_by_type="system",
        activated_by_id="test-suite",
        activation_reason="Test fixture",
    )
    pack = ContentPack(
        id=uuid4(),
        story_revision_id=story_revision.id,
        brand_profile_id=brand.id,
        status="draft",
    )
    variant = PlatformVariant(id=uuid4(), content_pack_id=pack.id, platform="instagram")
    current = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content={},
        content_hash="b" * 64,
        evidence_map=[],
        validation_results=[{"gate": "platform_schema", "ok": True, "reason": None}],
        approval_state="approved",
        created_by="generation",
    )
    db_session.add_all([story, brand, profile, template])
    await db_session.flush()
    db_session.add_all([story_revision, prompt])
    await db_session.flush()
    db_session.add(pack)
    await db_session.flush()
    db_session.add(variant)
    await db_session.flush()
    db_session.add(current)
    await db_session.commit()

    class Jobs:
        async def enqueue_job(self, **kwargs):
            return SimpleNamespace(
                job=SimpleNamespace(id=uuid4(), status="queued"),
                created=True,
            )

    async with session_factory() as cached_worker, session_factory() as enqueueing:
        try:
            locked_prompt = await cached_worker.scalar(
                select(PromptTemplateVersion).where(PromptTemplateVersion.id == prompt.id).with_for_update()
            )
            assert locked_prompt is not None
            await enqueueing.execute(text("SET LOCAL lock_timeout = '750ms'"))

            accepted = await asyncio.wait_for(
                EditorialService(enqueueing, jobs=Jobs()).regenerate_variant(
                    variant.id,
                    RegenerateVariantRequest(
                        generation_provider_profile_id=profile.id,
                        instruction="Try again",
                    ),
                ),
                timeout=2,
            )
            assert accepted.status == "queued"
            await enqueueing.commit()

            # The worker's Prompt -> Variant order can now continue because
            # enqueue did not hold Variant while waiting for the prompt row.
            locked_variant = await cached_worker.scalar(
                select(PlatformVariant).where(PlatformVariant.id == variant.id).with_for_update()
            )
            assert locked_variant is not None
        finally:
            await enqueueing.rollback()
            await cached_worker.rollback()
