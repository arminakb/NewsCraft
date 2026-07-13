from __future__ import annotations

import hashlib
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.content_packs import get_editorial_profile_resolver
from app.api.telegram_drafts import require_revision_transition
from app.db.model_registry import Base
from app.db.session import get_session
from app.generation.default_prompts import (
    seed_default_editorial_prompts,
    seed_default_telegram_configuration,
)
from app.generation.editorial_service import (
    ApprovalRequest,
    EditorialService,
    EditVariantRequest,
    GeneratePackRequest,
)
from app.generation.models import GenerationRun, PlatformVariantRevision
from app.generation.providers.base import GenerationProviderResult
from app.generation.providers.profiles import ResolvedProviderProfile
from app.generation.providers.registry import build_default_provider_registry
from app.generation.telegram_schema import TelegramRewriteOutput
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext, build_default_registry
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin
from app.jobs.worker import WorkerRunner
from app.main import app
from app.research.fake import FakeResearchBackend
from app.research.handlers import build_research_story_handler
from app.research.models import ResearchAttempt, ResearchRun
from app.research.service import ResearchService
from app.stories.handlers import handle_manual_intake
from app.stories.models import Story

ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest_asyncio.fixture(scope="module")
async def release3_engine() -> AsyncIterator[AsyncEngine]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for the durable Release 3 integration flow")
    database_name = make_url(TEST_DATABASE_URL).database
    if not database_name or not database_name.endswith("_test"):
        raise RuntimeError("Refusing destructive integration test unless database ends in '_test'")
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def release3_factory(release3_engine: AsyncEngine):
    table_names = [
        release3_engine.dialect.identifier_preparer.quote(table.name) for table in Base.metadata.sorted_tables
    ]
    async with release3_engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
    return async_sessionmaker(release3_engine, expire_on_commit=False)


class _AcceptanceProvider:
    provider_name = "fake"

    async def generate(self, request):
        if request.purpose == "canonical_story":
            evidence = json.loads(request.messages[1].content.split("Persisted evidence JSON: ", 1)[1])
            source = evidence[-1]
            content = source["content_text"]
            output = {
                "headline": "Release confirmed",
                "narrative": (
                    "The release evidence was checked through the deterministic editorial "
                    "acceptance flow and remains bound to its immutable source snapshot."
                ),
                "facts": [
                    {
                        "text": "The supplied source confirms the release evidence.",
                        "citations": [
                            {
                                "evidence_key": source["evidence_key"],
                                "evidence_snapshot_id": source["evidence_snapshot_id"],
                                "source_url": source["source_url"],
                                "locator": f"chars:0-{len(content)}",
                                "excerpt_sha256": hashlib.sha256(content.encode()).hexdigest(),
                            }
                        ],
                    }
                ],
                "disagreements": [],
                "angles": ["Explain the verified release timeline."],
                "missing_information": [],
            }
        elif request.purpose == "telegram_pack":
            output = {"body": "Verified Telegram draft", "parse_mode": "HTML", "buttons": []}
        else:  # pragma: no cover - the registry constrains this acceptance flow
            raise AssertionError(f"unexpected generation purpose: {request.purpose}")
        return GenerationProviderResult(
            provider="fake",
            requested_model=request.requested_model,
            resolved_model=request.requested_model or "fake-v1",
            output=output,
            raw_text=json.dumps(output, sort_keys=True),
            usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0},
            finish_reason="stop",
        )


class _AcceptanceProfileResolver:
    def __init__(self) -> None:
        self.provider = _AcceptanceProvider()

    async def validate_availability(self, profile, model_override):
        return await self.resolve(profile, model_override)

    async def resolve(self, profile, model_override):
        return ResolvedProviderProfile(
            profile_id=profile.id,
            provider_type="fake",
            model=model_override or profile.default_model,
            provider=self.provider,
        )


@dataclass
class AppHarness:
    client: AsyncClient
    session_factory: async_sessionmaker
    worker: WorkerRunner
    brand_id: UUID
    fake_provider_profile_id: UUID
    canonical_prompt_version_id: UUID
    telegram_prompt_version_id: UUID

    async def post_json(self, path: str, payload: dict, *, expected_status: int):
        response = await self.client.post(path, json=payload)
        assert response.status_code == expected_status, response.text
        return response.json()

    async def run_until_idle(self) -> None:
        for _ in range(20):
            if not await self.worker.run_once():
                return
        raise AssertionError("worker did not become idle")

    async def story_for_job(self, job_id: str) -> Story:
        async with self.session_factory() as session:
            job = await session.get(WorkflowJob, UUID(job_id))
            assert job is not None and job.status == "succeeded"
            story = await session.get(Story, UUID(job.result["story_id"]))
            assert story is not None
            return story


@pytest_asyncio.fixture
async def app_harness(release3_factory):
    resolver = _AcceptanceProfileResolver()
    research_backend = FakeResearchBackend.from_fixture(
        ROOT / "backend/tests/fixtures/research_brief.json"
    )
    async with release3_factory() as session:
        defaults = await seed_default_telegram_configuration(
            session, openrouter_available=False
        )
        prompts = await seed_default_editorial_prompts(session)
        await session.commit()
        ids = (
            defaults.brand.id,
            defaults.provider("fake").id,
            prompts.canonical_story.id,
            prompts.telegram_pack.id,
        )

    async def override_session():
        async with release3_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_editorial_profile_resolver] = lambda: resolver
    registry = build_default_registry(
        capabilities=("ingestion", "generation"),
        profile_resolver=resolver,
        research_backend_resolver=lambda _profile: research_backend,
    )
    worker = WorkerRunner(
        session_factory=release3_factory,
        handler_registry=registry,
        provider_registry=build_default_provider_registry(),
        worker_id="release3-acceptance-worker",
        capabilities=("ingestion", "generation"),
        heartbeat_seconds=60,
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield AppHarness(client, release3_factory, worker, *ids)
    finally:
        app.dependency_overrides.clear()
        await worker.close()


def test_operator_runbook_records_release_3_offline_and_live_provider_contracts():
    runbook = (ROOT / "docs/operations/research-and-generation.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for exact_setting in (
        "OPENROUTER_API_KEY=",
        "CODEX_ENABLED=true",
        "CODEX_EXECUTABLE=codex",
        "CODEX_HOME=/home/operator/.codex",
        "- ${CODEX_HOME}:/codex-auth:ro",
    ):
        assert exact_setting in runbook
    for phrase in (
        "Fake mode needs no credentials",
        "local Codex authentication",
        "controlled DuckDuckGo loop",
        "AIProviderProfile.settings",
        "Canonical story",
        "Telegram pack",
        "Add source material",
        "Research more",
        "Deep research",
        "Save revision",
        "Approve",
    ):
        assert phrase in runbook
    assert "Research and generation" in readme
    assert "docs/operations/research-and-generation.md" in readme


@pytest.mark.asyncio
async def test_http_manual_story_research_generation_edit_and_exact_approval(app_harness):
    intake = await app_harness.post_json(
        "/stories/manual",
        {
            "kind": "text",
            "title": "Release",
            "text": "x" * 900,
            "source_label": "Operator",
            "source_url": None,
        },
        expected_status=202,
    )
    assert intake["status"] == "queued" and intake["deduplicated"] is False
    await app_harness.run_until_idle()
    story = await app_harness.story_for_job(intake["job_id"])
    assert story.status == "inbox"

    research = await app_harness.post_json(
        f"/stories/{story.id}/research-runs",
        {
            "mode": "manual",
            "depth": "standard",
            "provider_profile_id": str(app_harness.fake_provider_profile_id),
            "query_hint": "Verify date",
        },
        expected_status=202,
    )
    assert research["disposition"] == "enqueued" and research["job_id"]
    await app_harness.run_until_idle()
    research_detail = (
        await app_harness.client.get(f"/research-runs/{research['run_id']}")
    )
    assert research_detail.status_code == 200
    assert research_detail.json()["status"] == "succeeded"

    pack = await app_harness.post_json(
        f"/stories/{story.id}/content-packs",
        {
            "brand_profile_id": str(app_harness.brand_id),
            "platform": "telegram",
            "generation_provider_profile_id": str(
                app_harness.fake_provider_profile_id
            ),
            "canonical_prompt_template_version_id": str(
                app_harness.canonical_prompt_version_id
            ),
            "platform_prompt_template_version_id": str(
                app_harness.telegram_prompt_version_id
            ),
            "research_mode": "off",
            "research_provider_profile_id": None,
            "research_run_id": research["run_id"],
        },
        expected_status=202,
    )
    assert pack["status"] == "queued" and pack["deduplicated"] is False
    await app_harness.run_until_idle()

    async with app_harness.session_factory() as session:
        canonical_job = await session.get(WorkflowJob, UUID(pack["job_id"]))
        telegram_job = await session.get(
            WorkflowJob, UUID(canonical_job.result["continuation_job_id"])
        )
        generated = await session.get(
            PlatformVariantRevision, UUID(telegram_job.result["revision_id"])
        )
        runs = list(
            await session.scalars(
                select(GenerationRun).order_by(
                    GenerationRun.created_at, GenerationRun.id
                )
            )
        )
        assert [run.prompt_template_version_id for run in runs] == [
            app_harness.canonical_prompt_version_id,
            app_harness.telegram_prompt_version_id,
        ]

    blocked = await app_harness.client.post(
        f"/telegram/drafts/{generated.id}/publish",
        json={"content_hash": generated.content_hash},
    )
    assert blocked.status_code == 409
    assert "current state" in blocked.json()["detail"]

    edited = await app_harness.post_json(
        f"/platform-variants/{generated.platform_variant_id}/revisions",
        {
            "base_revision_id": str(generated.id),
            "base_content_hash": generated.content_hash,
            "content": {
                "body": "Edited copy",
                "parse_mode": "HTML",
                "buttons": [],
            },
            "media_asset_ids": [],
            "edit_note": "Operator edit",
        },
        expected_status=201,
    )
    assert edited["approval_state"] == "pending_review"
    assert edited["content"]["body"] == "Edited copy"
    approved = await app_harness.post_json(
        f"/platform-variant-revisions/{edited['id']}/approve",
        {
            "expected_content_hash": edited["content_hash"],
            "note": "Ready",
        },
        expected_status=200,
    )
    assert approved["id"] == edited["id"]
    assert approved["approval_state"] == "approved"

    eligible = await app_harness.client.post(
        f"/telegram/drafts/{edited['id']}/publish",
        json={"content_hash": edited["content_hash"]},
    )
    assert eligible.status_code == 409
    assert eligible.json()["detail"] == "Telegram draft has no route provenance"


@pytest.mark.asyncio
async def test_supplemental_direct_service_flow(release3_factory):
    async with release3_factory() as session:
        defaults = await seed_default_telegram_configuration(session, openrouter_available=False)
        prompts = await seed_default_editorial_prompts(session)
        fake_profile = defaults.provider("fake")
        brand_id = defaults.brand.id
        fake_profile_id = fake_profile.id
        canonical_prompt_id = prompts.canonical_story.id
        telegram_prompt_id = prompts.telegram_pack.id
        intake = await JobRepository(session).enqueue_job(
            job_type="manual_intake",
            payload={
                "kind": "text",
                "title": "Release",
                "text": "x" * 900,
                "source_label": "Operator",
                "source_url": None,
            },
            idempotency_key="release3-acceptance-manual-text",
            origin=JobOrigin.MANUAL,
        )
        await session.commit()
        intake_job = await session.get(WorkflowJob, intake.job.id)
        intake_result = await handle_manual_intake(
            intake_job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
        await session.commit()

        story = await session.get(Story, UUID(intake_result["story_id"]))
        assert story is not None and story.status == "inbox"
        story_id = story.id

        research = await ResearchService(session).request(
            story_id=story_id,
            mode="manual",
            depth="standard",
            provider_profile_id=fake_profile_id,
            query_hint="Verify date",
        )
        await session.commit()
        assert research.job_id is not None and research.run_id is not None
        research_job = await session.get(WorkflowJob, research.job_id)
        fake_research = FakeResearchBackend.from_fixture(ROOT / "backend/tests/fixtures/research_brief.json")
        await build_research_story_handler(lambda _profile: fake_research)(
            research_job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
        await session.commit()
        research_run = await session.get(ResearchRun, research.run_id)
        assert research_run.status == "succeeded"
        assert research_run.result_story_revision_id is not None

        resolver = _AcceptanceProfileResolver()
        editorial = EditorialService(session, profile_resolver=resolver)
        pack_request = await editorial.request_content_pack(
            story_id,
            GeneratePackRequest(
                brand_profile_id=brand_id,
                platform="telegram",
                generation_provider_profile_id=fake_profile_id,
                canonical_prompt_template_version_id=canonical_prompt_id,
                platform_prompt_template_version_id=telegram_prompt_id,
                research_mode="off",
                research_run_id=research_run.id,
            ),
        )
        await session.commit()

        from app.generation.handlers import (
            build_canonical_generation_handler,
            build_pack_generation_handler,
        )

        generation_context = JobContext(
            session=session,
            providers=build_default_provider_registry(),
        )
        canonical_job = await session.get(WorkflowJob, pack_request.job_id)
        canonical_result = await build_canonical_generation_handler(resolver)(canonical_job, generation_context)
        await session.commit()
        telegram_job = await session.get(WorkflowJob, UUID(canonical_result["continuation_job_id"]))
        telegram_result = await build_pack_generation_handler(resolver)(telegram_job, generation_context)
        await session.commit()

        generated = await session.get(PlatformVariantRevision, UUID(telegram_result["revision_id"]))
        edited = await editorial.edit_variant(
            UUID(telegram_result["variant_id"]),
            EditVariantRequest(
                base_revision_id=generated.id,
                base_content_hash=generated.content_hash,
                content=TelegramRewriteOutput(body="Edited copy", parse_mode="HTML", buttons=[]),
                media_asset_ids=[],
                edit_note="Operator edit",
            ),
        )
        await session.commit()
        assert edited.approval_state == "pending_review"
        assert edited.content["body"] == "Edited copy"

        with pytest.raises(HTTPException):
            require_revision_transition(
                edited,
                action="publish",
                content_hash=edited.content_hash,
            )
        approved = await editorial.approve_revision(
            edited.id,
            ApprovalRequest(
                expected_content_hash=edited.content_hash,
                note="Ready",
            ),
        )
        await session.commit()
        require_revision_transition(
            approved,
            action="publish",
            content_hash=approved.content_hash,
        )
        assert approved.id == edited.id
        assert approved.approval_state == "approved"

        runs = list(await session.scalars(select(GenerationRun).order_by(GenerationRun.created_at, GenerationRun.id)))
        assert [run.prompt_template_version_id for run in runs] == [
            canonical_prompt_id,
            telegram_prompt_id,
        ]


@pytest.mark.asyncio
async def test_stale_research_attempt_uses_captured_job_id_after_real_rollback(
    release3_factory,
):
    async with release3_factory() as session:
        defaults = await seed_default_telegram_configuration(
            session, openrouter_available=False
        )
        intake = await JobRepository(session).enqueue_job(
            job_type="manual_intake",
            payload={
                "kind": "text",
                "title": "Concurrent research",
                "text": "x" * 900,
                "source_label": "Operator",
                "source_url": None,
            },
            idempotency_key="release3-stale-research-manual-text",
            origin=JobOrigin.MANUAL,
        )
        await session.commit()
        intake_job = await session.get(WorkflowJob, intake.job.id)
        intake_result = await handle_manual_intake(
            intake_job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )
        await session.commit()
        requested = await ResearchService(session).request(
            story_id=UUID(intake_result["story_id"]),
            mode="manual",
            depth="standard",
            provider_profile_id=defaults.provider("fake").id,
            query_hint="Verify concurrent completion",
        )
        await session.commit()
        assert requested.job_id is not None and requested.run_id is not None
        research_job = await session.get(WorkflowJob, requested.job_id)
        assert research_job is not None

        winning_backend = FakeResearchBackend.from_fixture(
            ROOT / "backend/tests/fixtures/research_brief.json"
        )

        class InterleavingBackend:
            async def research(self, request):
                async with release3_factory() as competing_session:
                    competing_job = await competing_session.get(
                        WorkflowJob, requested.job_id
                    )
                    assert competing_job is not None
                    await build_research_story_handler(
                        lambda _profile: winning_backend
                    )(
                        competing_job,
                        JobContext(
                            session=competing_session,
                            providers=build_default_provider_registry(),
                        ),
                    )
                return await winning_backend.research(request)

        stale = await build_research_story_handler(
            lambda _profile: InterleavingBackend()
        )(
            research_job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )

    assert stale["stale_attempt_ignored"] is True
    async with release3_factory() as verification_session:
        run = await verification_session.get(ResearchRun, requested.run_id)
        attempts = list(
            await verification_session.scalars(
                select(ResearchAttempt)
                .where(ResearchAttempt.research_run_id == requested.run_id)
                .order_by(ResearchAttempt.attempt_number)
            )
        )
        stale_events = list(
            await verification_session.scalars(
                select(WorkflowEvent).where(
                    WorkflowEvent.workflow_job_id == requested.job_id,
                    WorkflowEvent.event_type == "research.stale_attempt_ignored",
                )
            )
        )

    assert run is not None and run.status == "succeeded"
    assert [attempt.status for attempt in attempts] == ["failed", "succeeded"]
    assert len(stale_events) == 1
    assert stale_events[0].event_data["attempt_id"] == stale["attempt_id"]
