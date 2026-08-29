from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.automations.definitions.execution import AutomationExecutionService
from app.automations.definitions.schemas import AutomationCreate, AutomationRunStart
from app.automations.definitions.service import AutomationDefinitionService
from app.generation.default_prompts import (
    seed_default_editorial_prompts,
    seed_default_telegram_configuration,
    seed_starter_prompts,
)
from app.generation.models import PromptTemplate, PromptTemplateVersion
from app.jobs.errors import PermanentJobError
from app.research.handlers import _resolve_payload_system_prompt
from app.research.models import ResearchRun
from app.research.prompts import compose_system_policy as _compose_system_policy
from app.security.auth import TEST_ADMIN
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision


async def test_starter_prompts_seed_two_reusable_user_editable_prompts(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        await seed_starter_prompts(session)
        await seed_starter_prompts(session)
        await session.commit()
        rows = list(await session.scalars(select(PromptTemplate).order_by(PromptTemplate.name)))
    starters = [item for item in rows if item.purpose_key.endswith("_starter")]
    assert len(starters) == 2
    assert {item.name for item in starters} == {
        "News Article Research — Structured Evidence",
        "News Article Generation — Evidence-Based Editorial Post",
    }
    starter_ids = {item.id for item in starters}
    async with session_factory() as session:
        versions = list(await session.scalars(select(PromptTemplateVersion)))
    starter_versions = [item for item in versions if item.prompt_template_id in starter_ids]
    assert len(starter_versions) == 2
    assert all(item.is_active and item.version == 1 for item in starter_versions)


def test_compose_system_policy_keeps_safety_policy_first():
    assert _compose_system_policy(None) == _compose_system_policy("")
    composed = _compose_system_policy("Always answer in Persian.")
    assert composed.startswith(_compose_system_policy(None))
    assert "Operator research instructions:" in composed
    assert composed.endswith("Always answer in Persian.")


async def test_resolve_payload_system_prompt_enforces_active_and_checksum(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        await seed_starter_prompts(session)
        await session.commit()
        template = await session.scalar(
            select(PromptTemplate).where(PromptTemplate.purpose_key == "news_research_starter")
        )
        version = await session.scalar(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.prompt_template_id == template.id
            )
        )
        good_payload = {
            "prompt_template_version_id": str(version.id),
            "prompt_checksum_sha256": version.checksum_sha256,
        }
        assert await _resolve_payload_system_prompt(session, {}) is None
        assert await _resolve_payload_system_prompt(session, good_payload) == version.system_template

        try:
            await _resolve_payload_system_prompt(
                session, dict(good_payload, prompt_checksum_sha256="b" * 64)
            )
        except PermanentJobError as exc:
            assert exc.code == "research_prompt_checksum_mismatch"
        else:
            raise AssertionError("checksum mismatch must fail")

        try:
            await _resolve_payload_system_prompt(
                session,
                {"prompt_template_version_id": str(uuid4()), "prompt_checksum_sha256": "c" * 64},
            )
        except PermanentJobError as exc:
            assert exc.code == "research_prompt_unavailable"
        else:
            raise AssertionError("missing prompt must fail")


def _research_graph(
    *,
    provider_id,
    brand_id,
    prompts,
    research_prompt_version,
    checksum_mismatch: bool = False,
) -> dict[str, object]:
    checksum = (
        "d" * 64
        if checksum_mismatch
        else research_prompt_version.checksum_sha256
    )
    return {
        "schema_version": 1,
        "entry_node_id": "trigger-1",
        "nodes": [
            {"id": "trigger-1", "type": "manual", "config": {}},
            {
                "id": "research-1",
                "type": "research",
                "config": {
                    "provider_profile_id": str(provider_id),
                    "prompt_template_version_id": str(research_prompt_version.id),
                    "prompt_checksum_sha256": checksum,
                    "mode": "auto_if_incomplete",
                    "query_budget": 2,
                    "page_budget": 3,
                    "time_budget_seconds": 60,
                },
            },
            {
                "id": "generate-1",
                "type": "generate_content_pack",
                "config": {
                    "editorial_profile_id": str(brand_id),
                    "provider_profile_id": str(provider_id),
                    "prompt_version_ids": [
                        str(prompts.canonical_story.id),
                        str(prompts.telegram_pack.id),
                    ],
                    "prompt_checksums": {
                        str(prompts.canonical_story.id): prompts.canonical_story.checksum_sha256,
                        str(prompts.telegram_pack.id): prompts.telegram_pack.checksum_sha256,
                    },
                    "platforms": ["telegram"],
                },
            },
            {"id": "draft-1", "type": "save_drafts", "config": {}},
        ],
        "edges": [
            {
                "source_node_id": "trigger-1",
                "source_port": "story",
                "target_node_id": "research-1",
                "target_port": "story",
            },
            {
                "source_node_id": "research-1",
                "source_port": "story",
                "target_node_id": "generate-1",
                "target_port": "story",
            },
            {
                "source_node_id": "generate-1",
                "source_port": "drafts",
                "target_node_id": "draft-1",
                "target_port": "drafts",
            },
        ],
        "output_node_ids": ["draft-1"],
        "metadata": {"layout": {}},
    }


async def _seed_story_with_evidence(session: AsyncSession) -> Story:
    evidence_text = "Two independent sources confirm the budget-bound research pipeline."
    story = Story(title="Budgeted research", status="inbox", primary_language="en")
    session.add(story)
    await session.flush()
    snapshot = StoryEvidenceSnapshot(
        id=uuid4(),
        story_id=story.id,
        content_item_id=None,
        evidence_key="budget.pipeline",
        source_url="https://example.com/budget-pipeline",
        title="Pipeline source",
        content_text=evidence_text,
        authors=[],
        published_at=None,
        content_sha256=hashlib.sha256(evidence_text.encode()).hexdigest(),
        snapshot_metadata={},
    )
    revision = StoryRevision(
        story_id=story.id,
        parent_revision_id=None,
        revision_number=1,
        narrative=evidence_text,
        facts=[],
        disagreements=[],
        angles=[],
        citations=[
            {
                "evidence_key": snapshot.evidence_key,
                "evidence_snapshot_id": str(snapshot.id),
                "source_url": snapshot.source_url,
                "locator": f"chars:0-{len(evidence_text)}",
                "excerpt_sha256": snapshot.content_sha256,
            }
        ],
        created_by="test-suite",
    )
    session.add_all([snapshot, revision])
    await session.flush()
    return story


async def test_research_node_persists_prompt_and_node_budgets_into_run(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        await seed_default_editorial_prompts(session)
        await seed_starter_prompts(session)
        defaults = await seed_default_telegram_configuration(session)
        provider = defaults.provider("fake")
        template = await session.scalar(
            select(PromptTemplate).where(PromptTemplate.purpose_key == "news_research_starter")
        )
        version = await session.scalar(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.prompt_template_id == template.id
            )
        )
        story = await _seed_story_with_evidence(session)
        graph = _research_graph(
            provider_id=provider.id,
            brand_id=defaults.brand.id,
            prompts=await _seeded_editorial_prompts(session),
            research_prompt_version=version,
        )
        graph["nodes"][0]["config"] = {"story_revision_id": str((await _revision_for_story(session, story)).id)}  # type: ignore[index]
        created = await AutomationDefinitionService(session).create_automation(
            AutomationCreate(name="Prompted research", graph=graph),
            principal=TEST_ADMIN,
            idempotency_key="research-prompt-budget-create",
        )
        started = await AutomationExecutionService(session).start(
            created.id,
            AutomationRunStart(version_number=1, dry_run=True),
            principal=TEST_ADMIN,
            capability_status=None,
            idempotency_key="research-prompt-budget-start",
        )
        assert started.status == "queued"
        run = await session.scalar(select(ResearchRun).where(ResearchRun.story_id == story.id))
        assert run is not None
        # Node budgets are authoritative over the provider-derived defaults.
        assert run.query_budget == 2
        assert run.page_budget == 3
        assert run.time_budget_seconds == 60


async def test_validate_reports_wrong_research_prompt_checksum(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        await seed_default_editorial_prompts(session)
        await seed_starter_prompts(session)
        defaults = await seed_default_telegram_configuration(session)
        provider = defaults.provider("fake")
        template = await session.scalar(
            select(PromptTemplate).where(PromptTemplate.purpose_key == "news_research_starter")
        )
        version = await session.scalar(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.prompt_template_id == template.id
            )
        )
        graph = _research_graph(
            provider_id=provider.id,
            brand_id=defaults.brand.id,
            prompts=await _seeded_editorial_prompts(session),
            research_prompt_version=version,
            checksum_mismatch=True,
        )
        created = await AutomationDefinitionService(session).create_automation(
            AutomationCreate(name="Bad checksum research", graph=graph),
            principal=TEST_ADMIN,
            idempotency_key="research-bad-checksum-create",
        )
        result = await AutomationDefinitionService(session).validate_version(
            created.id, 1, capability_status=None
        )

    checksum_findings = [
        item
        for item in result.findings
        if item.field_path == "config.prompt_checksum_sha256"
        and item.code == "automation_resource_unavailable"
    ]
    assert checksum_findings, "checksum drift must be reported"


async def _seeded_editorial_prompts(session: AsyncSession):
    from dataclasses import dataclass

    @dataclass(frozen=True, slots=True)
    class Prompts:
        canonical_story: PromptTemplateVersion
        telegram_pack: PromptTemplateVersion

    async def one(purpose: str) -> PromptTemplateVersion:
        template = await session.scalar(
            select(PromptTemplate).where(PromptTemplate.purpose_key == purpose)
        )
        return await session.scalar(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.prompt_template_id == template.id
            )
        )

    return Prompts(canonical_story=await one("canonical_story"), telegram_pack=await one("telegram_pack"))


async def _revision_for_story(session: AsyncSession, story: Story) -> StoryRevision:
    return await session.scalar(
        select(StoryRevision).where(StoryRevision.story_id == story.id)
    )
