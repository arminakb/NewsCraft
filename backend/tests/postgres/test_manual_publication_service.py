from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.automations.telegram.handlers import sha256_canonical
from app.generation.models import (
    BrandProfile,
    ContentPack,
    PlatformVariant,
    PlatformVariantRevision,
)
from app.jobs.models import WorkflowEvent
from app.manual_publication.models import ManualPublicationPlan
from app.manual_publication.service import ManualPublicationService
from app.stories.models import Story, StoryRevision


def _instagram_content() -> tuple[dict[str, object], list[dict[str, object]]]:
    citation = {
        "evidence_key": "evidence:one",
        "evidence_snapshot_id": str(uuid4()),
        "source_url": "https://example.com/report",
        "locator": "chars:0-12",
        "excerpt_sha256": "a" * 64,
    }
    return (
        {
            "hook": "What changed?",
            "caption": "A grounded caption for a manual Instagram post.",
            "cta": "Read the cited report.",
            "hashtags": ["#NewsCraft"],
            "alt_text": "A source image illustrating the update.",
            "carousel": [],
            "citations": [citation],
            "manual_checklist": ["Review before publication"],
        },
        [citation],
    )


@pytest.mark.asyncio
async def test_concurrent_exact_create_replay_has_one_active_plan_and_one_event(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
):
    story = Story(id=uuid4(), title="Manual publication race", status="inbox", primary_language="en")
    story_revision = StoryRevision(
        id=uuid4(),
        story_id=story.id,
        parent_revision_id=None,
        revision_number=1,
        narrative="Grounded story",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[],
        created_by="test",
    )
    brand = BrandProfile(
        id=uuid4(),
        name=f"Manual Race {uuid4()}",
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
        status="ready",
    )
    variant = PlatformVariant(
        id=uuid4(),
        content_pack_id=pack.id,
        platform="instagram",
    )
    content, evidence_map = _instagram_content()
    revision = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=[{"gate": "platform_schema", "ok": True, "reason": None}],
        approval_state="approved",
        approval_note=None,
        approved_at=datetime.now(UTC),
        created_by="test",
    )
    db_session.add_all([story, brand])
    await db_session.flush()
    db_session.add(story_revision)
    await db_session.flush()
    db_session.add(pack)
    await db_session.flush()
    db_session.add(variant)
    await db_session.flush()
    db_session.add(revision)
    await db_session.commit()
    scheduled_for = datetime.now(UTC) + timedelta(hours=2)

    async def create() -> object:
        async with session_factory() as session:
            plan = await ManualPublicationService(session).create_plan(
                revision.id,
                scheduled_for,
                "Asia/Tehran",
            )
            await session.commit()
            return plan.id

    first_id, second_id = await asyncio.gather(create(), create())

    assert first_id == second_id
    assert await db_session.scalar(select(func.count()).select_from(ManualPublicationPlan)) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WorkflowEvent)
            .where(WorkflowEvent.event_type == "manual_publication.plan.created")
        )
        == 1
    )
