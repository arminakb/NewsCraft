"""End-to-end news production validation.

Proves the full chain with deterministic fakes:
Settings (provider + prompt APIs) → workflow persistence → runtime execution
(research → structured output → generation) → review boundary (pending_review,
no publishing).
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.llm_providers as llm_api
from app.automations.definitions.execution import AutomationExecutionService
from app.automations.definitions.models import AutomationRun
from app.automations.definitions.schemas import AutomationCreate, AutomationRunStart
from app.automations.definitions.service import AutomationDefinitionService
from app.core.config import Settings
from app.db.session import get_session
from app.generation.default_prompts import (
    seed_default_editorial_prompts,
    seed_default_telegram_configuration,
    seed_starter_prompts,
)
from app.generation.models import PlatformVariantRevision, PromptTemplate, PromptTemplateVersion
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext, build_default_registry
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution
from app.main import app
from app.publishing.models import Publication, PublishJob
from app.research.handlers import DefaultResearchBackendResolver
from app.security.auth import TEST_ADMIN
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision
from tests.postgres.test_automation_execution import FakeProfileResolver


def _encoded(byte: int) -> str:
    import base64

    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def _provider_api_config() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        secret_key_version="v1",
        secret_master_key=_encoded(3),
        security_internal_scopes="jobs:read,jobs:write,providers:read",
    )


async def _api(db_session: AsyncSession, method: str, path: str, json: dict | None = None):
    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, json=json)
    finally:
        app.dependency_overrides.pop(get_session, None)


async def _drain_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    resolver: FakeProfileResolver,
    worker_id: str,
    max_jobs: int = 8,
) -> list[str]:
    """Claim and execute every queued job until the queue drains."""

    executed: list[str] = []
    while len(executed) < max_jobs:
        async with session_factory() as session:
            repository = JobRepository(session)
            job = await repository.claim_next_job(
                worker_id=worker_id,
                lease_seconds=300,
                allowed_job_types=("research_story", "content_pack.generate", "content_pack.generate_telegram"),
            )
            if job is None:
                break
            execution = JobExecution.from_job(job)
            await session.commit()
            handler_registry = build_default_registry(
                capabilities=("generation",),
                profile_resolver=resolver,
                research_backend_resolver=DefaultResearchBackendResolver(resolver),
            )
            result = await handler_registry.get(job.job_type)(
                execution,
                JobContext(session=session, providers=build_default_provider_registry()),
            )
            await JobRepository(session).finish_job(
                job_id=execution.id,
                worker_id=worker_id,
                result=result,
            )
            await session.commit()
            executed.append(job.job_type)
    return executed


async def test_settings_to_reviewable_news_post_pipeline(
    session_factory: async_sessionmaker[AsyncSession],
):
    resolver = FakeProfileResolver()
    async with session_factory() as session:
        # --- Steps 1-2: Settings. Provider created through the public API;
        # starter prompts seeded exactly as production startup does.
        original = llm_api.settings
        llm_api.settings = _provider_api_config()
        try:
            created = await _api(
                session,
                "POST",
                "/llm-providers",
                {
                    "name": "Pipeline provider",
                    "base_url": "https://llm.example/v1",
                    "default_model": "vendor/model",
                    "api_key": "pipeline-secret-canary",
                },
            )
        finally:
            llm_api.settings = original
        assert created.status_code == 201, created.text
        provider_payload = created.json()
        assert provider_payload["enabled"] is False
        assert "pipeline-secret-canary" not in created.text
        listed = await _api(session, "GET", "/llm-providers")
        assert any(item["id"] == provider_payload["id"] for item in listed.json())

        # The untested provider is selectable by nodes: catalog labels are correct.
        catalog = await _api(session, "GET", "/automation-node-catalog")
        by_type = {item["type"]: item for item in catalog.json()["nodes"]}
        research_schema = by_type["research"]["config_schema"]["properties"]
        assert research_schema["provider_profile_id"]["title"] == "LLM Provider"
        assert research_schema["prompt_template_version_id"]["title"] == "System Prompt"
        assert research_schema["query_budget"]["title"] == "Query Budget"

        await seed_default_editorial_prompts(session)
        await seed_starter_prompts(session)
        defaults = await seed_default_telegram_configuration(session)
        fake_profile = defaults.provider("fake")

        template = await session.scalar(
            select(PromptTemplate).where(PromptTemplate.purpose_key == "news_research_starter")
        )
        research_prompt = await session.scalar(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.prompt_template_id == template.id
            )
        )

        async def active_version(purpose: str) -> PromptTemplateVersion:
            return await session.scalar(
                select(PromptTemplateVersion).join(
                    PromptTemplate,
                    PromptTemplate.id == PromptTemplateVersion.prompt_template_id,
                ).where(PromptTemplate.purpose_key == purpose)
            )

        canonical = await active_version("canonical_story")
        telegram_pack = await active_version("telegram_pack")

        # Article input awaiting research.
        evidence_text = "A wired report confirms the end-to-end pipeline produced reviewable news."
        story = Story(title="Pipeline acceptance", status="inbox", primary_language="en")
        session.add(story)
        await session.flush()
        snapshot = StoryEvidenceSnapshot(
            id=uuid4(),
            story_id=story.id,
            content_item_id=None,
            evidence_key="pipeline.acceptance",
            source_url="https://example.com/pipeline",
            title="Wire report",
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
                {
                    "id": "research-1",
                    "type": "research",
                    "config": {
                        "provider_profile_id": str(fake_profile.id),
                        "prompt_template_version_id": str(research_prompt.id),
                        "prompt_checksum_sha256": research_prompt.checksum_sha256,
                        "mode": "auto_if_incomplete",
                        "query_budget": 2,
                        "page_budget": 4,
                        "time_budget_seconds": 120,
                    },
                },
                {
                    "id": "generate-1",
                    "type": "generate_content_pack",
                    "config": {
                        "editorial_profile_id": str(defaults.brand.id),
                        "provider_profile_id": str(fake_profile.id),
                        "prompt_version_ids": [str(canonical.id), str(telegram_pack.id)],
                        "prompt_checksums": {
                            str(canonical.id): canonical.checksum_sha256,
                            str(telegram_pack.id): telegram_pack.checksum_sha256,
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
        graph["nodes"][0]["config"] = {"story_revision_id": str(revision.id)}  # type: ignore[index]

        saved = await AutomationDefinitionService(session).create_automation(
            AutomationCreate(name="Pipeline acceptance", graph=graph),
            principal=TEST_ADMIN,
            idempotency_key="pipeline-create",
        )
        automation_id = saved.id
        await session.commit()

    # --- Step 5: reload the persisted snapshot; selections must survive.
    async with session_factory() as session:
        reloaded = await AutomationDefinitionService(session).get_version(automation_id, 1)
        graph_nodes = [node.model_dump(mode="json", by_alias=True) for node in reloaded.graph.nodes]
    research_config = next(
        node["config"] for node in graph_nodes if node["id"] == "research-1"
    )
    generate_config = next(
        node["config"] for node in graph_nodes if node["id"] == "generate-1"
    )
    assert research_config["provider_profile_id"] == str(fake_profile.id)
    assert research_config["prompt_template_version_id"] == str(research_prompt.id)
    assert research_config["prompt_checksum_sha256"] == research_prompt.checksum_sha256
    assert research_config["query_budget"] == 2
    assert research_config["page_budget"] == 4
    assert research_config["time_budget_seconds"] == 120
    assert generate_config["provider_profile_id"] == str(fake_profile.id)

    # --- Step 6: runtime executes research then generation.
    async with session_factory() as session:
        started = await AutomationExecutionService(session).start(
            automation_id,
            AutomationRunStart(version_number=1, dry_run=True),
            principal=TEST_ADMIN,
            capability_status=None,
            idempotency_key="pipeline-start",
        )
        assert started.status == "queued"
        await session.commit()

    executed = await _drain_jobs(session_factory, resolver=resolver, worker_id="pipeline-worker")
    assert executed[0] == "research_story"
    assert any(job.startswith("content_pack.generate") for job in executed), executed

    # --- Step 7: results + review boundary.
    async with session_factory() as session:
        run_row = await session.scalar(
            select(AutomationRun).where(AutomationRun.automation_id == automation_id)
        )
        assert run_row is not None and run_row.status == "succeeded"
        revisions = list(await session.scalars(select(PlatformVariantRevision)))
        assert revisions, "generation must produce platform revisions"
        assert all(item.approval_state == "pending_review" for item in revisions)
        assert (await session.scalars(select(PublishJob).limit(1))).first() is None
        assert (await session.scalars(select(Publication).limit(1))).first() is None
        publish_job = await session.scalar(
            select(WorkflowJob).where(WorkflowJob.job_type == "telegram.publish")
        )
        assert publish_job is None
