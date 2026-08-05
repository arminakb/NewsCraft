from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.automations.definitions.execution import AutomationExecutionService
from app.automations.definitions.models import AutomationRun
from app.automations.definitions.schemas import AutomationCreate, AutomationRunStart
from app.automations.definitions.service import AutomationDefinitionService
from app.generation.default_prompts import seed_default_editorial_prompts, seed_default_telegram_configuration
from app.generation.models import PlatformVariantRevision
from app.generation.providers.fake import DeterministicFakeProvider
from app.generation.providers.profiles import ResolvedProviderProfile
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.models import WorkflowJob, WorkflowSchedule
from app.jobs.registry import JobContext, build_default_registry
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution
from app.publishing.models import Publication, PublishJob
from app.security.auth import TEST_ADMIN
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision


class FakeProfileResolver:
    def __init__(self) -> None:
        self.provider = DeterministicFakeProvider()

    async def validate_availability(self, profile, model_override):
        return await self.resolve(profile, model_override)

    async def resolve(self, profile, model_override):
        return ResolvedProviderProfile(
            profile_id=profile.id,
            provider_type="fake",
            model=model_override or profile.default_model,
            provider=self.provider,
        )


async def _run_one_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    resolver: FakeProfileResolver,
    job_type: str,
    worker_id: str,
) -> dict[str, object]:
    async with session_factory() as session:
        repository = JobRepository(session)
        job = await repository.claim_next_job(
            worker_id=worker_id,
            lease_seconds=300,
            allowed_job_types=(job_type,),
        )
        assert job is not None
        execution = JobExecution.from_job(job)
        await session.commit()
        registry = build_default_registry(capabilities=("generation",), profile_resolver=resolver)
        result = await registry.get(job_type)(
            execution,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
        await JobRepository(session).finish_job(
            job_id=execution.id,
            worker_id=worker_id,
            result=result,
        )
        await session.commit()
        return result


async def test_template_dry_run_survives_worker_restart_and_never_publishes(
    session_factory: async_sessionmaker[AsyncSession],
):
    resolver = FakeProfileResolver()
    async with session_factory() as session:
        prompts = await seed_default_editorial_prompts(session)
        defaults = await seed_default_telegram_configuration(session)
        provider = defaults.provider("fake")
        evidence_id = uuid4()
        evidence_text = "A durable source confirms the restart-safe automation acceptance journey."
        story = Story(title="Restart-safe workflow", status="inbox", primary_language="en")
        session.add(story)
        await session.flush()
        snapshot = StoryEvidenceSnapshot(
            id=evidence_id,
            story_id=story.id,
            content_item_id=None,
            evidence_key="automation.acceptance",
            source_url="https://example.com/automation-acceptance",
            title="Acceptance source",
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

        graph = {
            "schema_version": 1,
            "entry_node_id": "trigger-1",
            "nodes": [
                {"id": "trigger-1", "type": "manual", "config": {}},
                {"id": "generate-1", "type": "generate_content_pack", "config": {}},
                {"id": "draft-1", "type": "save_drafts", "config": {}},
            ],
            "edges": [
                {
                    "source_node_id": "trigger-1",
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
        graph["nodes"][0]["config"] = {"story_revision_id": str(revision.id)}
        graph["nodes"][1]["config"] = {
            "editorial_profile_id": str(defaults.brand.id),
            "provider_profile_id": str(provider.id),
            "prompt_version_ids": [str(prompts.canonical_story.id), str(prompts.telegram_pack.id)],
            "prompt_checksums": {
                str(prompts.canonical_story.id): prompts.canonical_story.checksum_sha256,
                str(prompts.telegram_pack.id): prompts.telegram_pack.checksum_sha256,
            },
            "platforms": ["telegram"],
        }
        created = await AutomationDefinitionService(session).create_automation(
            AutomationCreate(name="Template restart proof", graph=graph),
            principal=TEST_ADMIN,
            idempotency_key="automation-template-restart-proof",
        )
        started = await AutomationExecutionService(session).start(
            created.id,
            AutomationRunStart(version_number=1, dry_run=True),
            principal=TEST_ADMIN,
            capability_status=None,
            idempotency_key="automation-template-restart-run",
        )
        run_id = started.id
        version_id = started.automation_version_id
        await session.commit()

    canonical = await _run_one_job(
        session_factory,
        resolver=resolver,
        job_type="content_pack.generate",
        worker_id="generation-before-restart",
    )
    assert canonical["continuation_job_id"]

    platform = await _run_one_job(
        session_factory,
        resolver=resolver,
        job_type="content_pack.generate_telegram",
        worker_id="generation-after-restart",
    )

    async with session_factory() as reopened:
        run = await reopened.get(AutomationRun, run_id)
        generated = await reopened.get(PlatformVariantRevision, UUID(str(platform["revision_id"])))
        assert run is not None
        assert run.automation_version_id == version_id
        assert run.dry_run is True
        assert run.status == "succeeded"
        assert generated is not None and generated.approval_state == "pending_review"
        assert await reopened.scalar(select(func.count()).select_from(PublishJob)) == 0
        assert await reopened.scalar(select(func.count()).select_from(Publication)) == 0
        assert await reopened.scalar(
            select(func.count()).select_from(WorkflowJob).where(WorkflowJob.job_type == "telegram.publish")
        ) == 0


async def test_schedule_activation_materializes_version_pinned_pause_sensitive_schedule(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        prompts = await seed_default_editorial_prompts(session)
        defaults = await seed_default_telegram_configuration(session)
        provider = defaults.provider("fake")
        graph = {
            "schema_version": 1,
            "entry_node_id": "schedule-1",
            "nodes": [
                {
                    "id": "schedule-1",
                    "type": "schedule",
                    "config": {
                        "schedule_kind": "interval",
                        "timezone": "Asia/Tehran",
                        "interval_minutes": 30,
                    },
                },
                {
                    "id": "select-1",
                    "type": "select_content",
                    "config": {"max_count": 5, "sort": "newest"},
                },
                {
                    "id": "generate-1",
                    "type": "generate_content_pack",
                    "config": {
                        "editorial_profile_id": str(defaults.brand.id),
                        "provider_profile_id": str(provider.id),
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
                    "source_node_id": "schedule-1",
                    "source_port": "tick",
                    "target_node_id": "select-1",
                    "target_port": "tick",
                },
                {
                    "source_node_id": "select-1",
                    "source_port": "stories",
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
        service = AutomationDefinitionService(session)
        created = await service.create_automation(
            AutomationCreate(name="Scheduled desk", graph=graph),
            principal=TEST_ADMIN,
            idempotency_key="scheduled-desk-create",
        )
        activated = await service.activate(
            created.id,
            expected_revision=1,
            principal=TEST_ADMIN,
            capability_status=None,
            idempotency_key="scheduled-desk-activate",
        )
        schedule = await session.scalar(
            select(WorkflowSchedule).where(WorkflowSchedule.schedule_key == f"automation:{created.id}")
        )
        assert schedule is not None
        assert schedule.enabled is True
        assert schedule.pause_sensitive is True
        assert schedule.job_type == "automation.run.start"
        assert schedule.payload == {
            "automation_id": str(created.id),
            "automation_version_id": str(activated.active_version_id),
        }
        assert schedule.interval_minutes == 30

        paused = await service.pause(created.id, expected_revision=2, principal=TEST_ADMIN)
        assert schedule.enabled is False
        await service.resume(
            created.id,
            expected_revision=paused.revision,
            principal=TEST_ADMIN,
            capability_status=None,
        )
        assert schedule.enabled is True
        await session.commit()
