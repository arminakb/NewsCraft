from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.generation.default_prompts import prompt_checksum
from app.generation.handlers import build_pack_generation_handler
from app.generation.models import (
    BrandProfile,
    ContentPack,
    GenerationAttempt,
    GenerationRun,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.jobs.errors import NeedsReviewJobError
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision


@pytest.mark.asyncio
async def test_later_platform_failure_and_worker_rollback_cannot_erase_prior_checkpoint(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    story_id, snapshot_id, story_revision_id, brand_id = uuid4(), uuid4(), uuid4(), uuid4()
    evidence_text = "Evidence"
    citation = {
        "evidence_key": "evidence:one",
        "evidence_snapshot_id": str(snapshot_id),
        "source_url": "https://example.com/report",
        "locator": "chars:0-8",
        "excerpt_sha256": hashlib.sha256(evidence_text.encode()).hexdigest(),
    }
    story = Story(id=story_id, title="Grounded", status="inbox", primary_language="en")
    snapshot = StoryEvidenceSnapshot(
        id=snapshot_id,
        story_id=story_id,
        content_item_id=None,
        evidence_key="evidence:one",
        source_url="https://example.com/report",
        title="Evidence",
        content_text=evidence_text,
        authors=[],
        published_at=None,
        content_sha256=hashlib.sha256(evidence_text.encode()).hexdigest(),
        snapshot_metadata={},
    )
    story_revision = StoryRevision(
        id=story_revision_id,
        story_id=story_id,
        parent_revision_id=None,
        revision_number=1,
        narrative="Grounded story",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[citation],
        created_by="generation",
    )
    brand = BrandProfile(
        id=brand_id,
        name="Durability Newsroom",
        output_language="en",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=False,
    )
    prompts = {}
    for platform in ("instagram", "blog"):
        template = PromptTemplate(
            id=uuid4(),
            purpose_key=f"{platform}_pack",
            name=f"{platform} durability",
            description=None,
        )
        system_template = f"{platform} system"
        user_template = "Story={canonical_story_json}"
        output_schema = {}
        version = PromptTemplateVersion(
            id=uuid4(),
            prompt_template_id=template.id,
            version=1,
            system_template=system_template,
            user_template=user_template,
            output_schema_version=f"{platform}.v1",
            output_schema=output_schema,
            checksum_sha256=prompt_checksum(system_template, user_template, output_schema),
            is_active=True,
        )
        prompts[platform] = version
        db_session.add_all([template, version])
    job = WorkflowJob(
        id=uuid4(),
        job_type="content_pack.generate",
        status="running",
        payload={
            "story_revision_id": str(story_revision_id),
            "brand_profile_id": str(brand_id),
            "generation_provider_profile_id": str(uuid4()),
            "platforms": ["instagram", "blog"],
            "platform_prompt_template_version_ids": {
                platform: str(prompt.id) for platform, prompt in prompts.items()
            },
            "platform_prompt_checksums": {
                platform: prompt.checksum_sha256 for platform, prompt in prompts.items()
            },
        },
        result={},
        priority=0,
        idempotency_key=f"durability:{uuid4()}",
        origin="manual",
        pause_sensitive=True,
        attempt_count=1,
        max_attempts=3,
        progress=0,
    )
    db_session.add_all([story, snapshot, story_revision, brand, job])
    await db_session.commit()

    raw_instagram = {
        "hook": "Grounded",
        "caption": "Grounded caption",
        "cta": "Read",
        "hashtags": [],
        "alt_text": "Grounded",
        "carousel": [],
        "citations": [citation],
        "manual_checklist": ["Verify"],
    }
    first_run_id = None
    calls = 0

    async def invoke(context, **kwargs):
        nonlocal calls, first_run_id
        calls += 1
        await kwargs["before_provider_call"]()
        if calls == 2:
            raise NeedsReviewJobError(
                code="citation_integrity",
                message="Later platform failed before provider",
            )
        authored = kwargs["validate_output"](raw_instagram)
        run = GenerationRun(
            id=uuid4(),
            story_revision_id=story_revision_id,
            provider_profile_id=None,
            prompt_template_version_id=prompts["instagram"].id,
            requested_model="fake-v1",
            status="succeeded",
            input_hash="a" * 64,
            request_payload={},
            output_payload={},
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        attempt = GenerationAttempt(
            id=uuid4(),
            generation_run_id=run.id,
            attempt_number=1,
            provider="fake",
            requested_model="fake-v1",
            resolved_model="fake-v1",
            prompt_snapshot={},
            response_payload=raw_instagram,
            usage={},
            validation_errors=[],
            status="succeeded",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        context.session.add_all([run, attempt])
        await context.session.flush()
        first_run_id = run.id
        return run, attempt, authored

    monkeypatch.setattr("app.generation.handlers._invoke", invoke)
    with pytest.raises(NeedsReviewJobError, match="Later platform failed"):
        await build_pack_generation_handler(SimpleNamespace())(
            job,
            JobContext(session=db_session, providers=SimpleNamespace()),
        )
    await db_session.rollback()

    async with session_factory() as reopened:
        durable_job = await reopened.get(WorkflowJob, job.id)
        pack = await reopened.scalar(select(ContentPack))
        variant = await reopened.scalar(
            select(PlatformVariant).where(PlatformVariant.platform == "instagram")
        )
        blog_variant = await reopened.scalar(
            select(PlatformVariant).where(PlatformVariant.platform == "blog")
        )
        revision = await reopened.scalar(select(PlatformVariantRevision))
        run = await reopened.get(GenerationRun, first_run_id)

        assert pack is not None
        assert variant is not None and variant.content_pack_id == pack.id
        assert revision is not None and revision.platform_variant_id == variant.id
        assert blog_variant is None
        assert durable_job is not None
        assert durable_job.result["platforms"] == ["instagram"]
        assert durable_job.result["revision_id"] == str(revision.id)
        assert run is not None
        assert run.output_payload["_artifact"]["revision_id"] == str(revision.id)
