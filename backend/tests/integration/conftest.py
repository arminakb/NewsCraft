from __future__ import annotations

import hashlib
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.api.content_packs import get_editorial_profile_resolver
from app.api.exports import _export_root, _media_root
from app.db.model_registry import Base
from app.db.session import get_session
from app.generation.default_prompts import (
    seed_default_editorial_prompts,
    seed_default_telegram_configuration,
)
from app.generation.providers.base import GenerationProviderResult
from app.generation.providers.profiles import ResolvedProviderProfile
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.models import WorkflowJob
from app.jobs.registry import build_default_registry
from app.jobs.worker import WorkerRunner
from app.main import app
from app.research.fake import FakeResearchBackend
from app.stories.models import Story

ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest_asyncio.fixture(scope="module")
async def release3_engine() -> AsyncIterator[AsyncEngine]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for the durable integration flows")
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

    def __init__(self) -> None:
        self._citation: dict[str, Any] | None = None

    async def generate(self, request):
        if request.purpose == "canonical_story":
            evidence = json.loads(
                request.messages[1].content.split(
                    "Persisted evidence JSON: ",
                    1,
                )[1]
            )
            source = evidence[-1]
            content = source["content_text"]
            self._citation = {
                "evidence_key": source["evidence_key"],
                "evidence_snapshot_id": source["evidence_snapshot_id"],
                "source_url": source["source_url"],
                "locator": f"chars:0-{len(content)}",
                "excerpt_sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
            output = {
                "headline": "Release confirmed",
                "narrative": (
                    "The release evidence was checked through the deterministic "
                    "editorial acceptance flow and remains bound to its immutable "
                    "source snapshot."
                ),
                "facts": [
                    {
                        "text": "The supplied source confirms the release evidence.",
                        "citations": [self._citation],
                    }
                ],
                "disagreements": [],
                "angles": ["Explain the verified release timeline."],
                "missing_information": [],
            }
        elif request.purpose == "telegram_pack":
            output = {
                "body": "Verified Telegram draft",
                "parse_mode": "HTML",
                "buttons": [],
            }
        elif request.purpose in {"instagram_pack", "x_pack", "blog_pack"}:
            if self._citation is None:
                raise AssertionError("manual platform generation requires canonical evidence")
            output = self._manual_platform_output(request.purpose, self._citation)
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

    @staticmethod
    def _manual_platform_output(
        purpose: str,
        citation: dict[str, Any],
    ) -> dict[str, Any]:
        if purpose == "instagram_pack":
            return {
                "hook": "The verified release is confirmed",
                "caption": (
                    "The immutable source snapshot confirms the announced release "
                    "and keeps this package grounded in the reviewed evidence."
                ),
                "cta": "Review the cited source before publishing.",
                "hashtags": ["#NewsCraft", "#VerifiedNews"],
                "alt_text": "A summary card describing the verified release.",
                "carousel": [
                    {
                        "order": 1,
                        "headline": "Release confirmed",
                        "body": "The cited source confirms the announced release.",
                        "media": {
                            "media_asset_id": None,
                            "role": "slide",
                            "order": 1,
                            "alt_text": "A text card stating that the release is confirmed.",
                            "manual_brief": "Create a simple source-backed summary card.",
                            "image_prompt": None,
                        },
                    }
                ],
                "citations": [citation],
                "manual_checklist": ["Verify carousel order and source attribution before publishing"],
            }
        if purpose == "x_pack":
            return {
                "mode": "single",
                "posts": [
                    {
                        "order": 1,
                        "text": (
                            "The immutable source snapshot confirms the announced "
                            "release. Review the cited evidence before publishing."
                        ),
                        "media": [],
                        "citations": [citation],
                    }
                ],
                "link_strategy": "last_post",
                "manual_checklist": ["Verify the post and source link before publishing"],
            }
        if purpose == "blog_pack":
            source_url = citation["source_url"]
            return {
                "title": "The verified release and its source evidence",
                "slug": "verified-release-source-evidence",
                "excerpt": ("A concise source-backed account of the announced release."),
                "body_markdown": (
                    "## What the source confirms\n\n"
                    + "The immutable source snapshot confirms the announced release " * 12
                ),
                "headings": ["What the source confirms"],
                "citations": [citation],
                "tags": ["release", "verification"],
                "seo_description": (
                    "A verified account of the announced release, grounded in an "
                    "immutable source snapshot and prepared for manual publication."
                ),
                "hero_media": None,
                "canonical_sources": [source_url] if source_url is not None else [],
                "manual_checklist": ["Verify the article, canonical source, and SEO fields"],
            }
        raise AssertionError(f"unexpected manual generation purpose: {purpose}")


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


@pytest.fixture
def acceptance_profile_resolver():
    return _AcceptanceProfileResolver()


@dataclass(frozen=True, slots=True)
class ResearchedStory:
    id: UUID
    research_run_id: UUID


@dataclass
class AppHarness:
    client: AsyncClient
    session_factory: async_sessionmaker
    worker: WorkerRunner
    brand_id: UUID
    fake_provider_profile_id: UUID
    canonical_prompt_version_id: UUID
    telegram_prompt_version_id: UUID
    instagram_prompt_version_id: UUID
    x_prompt_version_id: UUID
    blog_prompt_version_id: UUID
    export_root: Path
    media_root: Path

    async def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        expected_status: int,
    ) -> Any:
        response = await self.client.post(path, json=payload)
        assert response.status_code == expected_status, response.text
        return response.json()

    async def get_json(
        self,
        path: str,
        *,
        expected_status: int = 200,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = await self.client.get(path, params=params)
        assert response.status_code == expected_status, response.text
        return response.json()

    async def patch_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        expected_status: int,
    ) -> Any:
        response = await self.client.patch(path, json=payload)
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

    async def create_researched_story(self) -> ResearchedStory:
        intake = await self.post_json(
            "/stories/manual",
            {
                "kind": "text",
                "title": "Multi-platform release",
                "text": "Source-backed release context. " * 40,
                "source_label": "Acceptance operator",
                "source_url": None,
            },
            expected_status=202,
        )
        assert intake["status"] == "queued"
        assert intake["deduplicated"] is False
        await self.run_until_idle()
        story = await self.story_for_job(intake["job_id"])
        research = await self.post_json(
            f"/stories/{story.id}/research-runs",
            {
                "mode": "manual",
                "depth": "standard",
                "provider_profile_id": str(self.fake_provider_profile_id),
                "query_hint": "Verify the announced release",
            },
            expected_status=202,
        )
        assert research["disposition"] == "enqueued"
        assert research["job_id"]
        await self.run_until_idle()
        detail = await self.get_json(f"/research-runs/{research['run_id']}")
        assert detail["status"] == "succeeded"
        return ResearchedStory(
            id=story.id,
            research_run_id=UUID(research["run_id"]),
        )

    async def request_pack(
        self,
        story_id: UUID,
        *,
        research_run_id: UUID,
        platforms: list[str],
    ) -> dict[str, Any]:
        return await self.post_json(
            f"/stories/{story_id}/content-packs",
            {
                "brand_profile_id": str(self.brand_id),
                "platforms": platforms,
                "generation_provider_profile_id": str(self.fake_provider_profile_id),
                "research_mode": "off",
                "research_provider_profile_id": None,
                "research_run_id": str(research_run_id),
            },
            expected_status=202,
        )

    async def pack_for_job(self, job_id: str) -> dict[str, Any]:
        async with self.session_factory() as session:
            canonical = await session.get(WorkflowJob, UUID(job_id))
            assert canonical is not None and canonical.status == "succeeded"
            continuation_id = UUID(canonical.result["continuation_job_id"])
            continuation = await session.get(WorkflowJob, continuation_id)
            assert continuation is not None and continuation.status == "succeeded"
            pack_id = UUID(continuation.result["content_pack_id"])
        return await self.get_json(f"/content-packs/{pack_id}")

    async def approve_exact_revision(
        self,
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        approved = await self.post_json(
            f"/platform-variant-revisions/{revision['id']}/approve",
            {
                "expected_content_hash": revision["content_hash"],
                "note": "Approved by the deterministic acceptance flow",
            },
            expected_status=200,
        )
        for field in (
            "id",
            "platform_variant_id",
            "platform",
            "content_pack_id",
            "story_id",
            "revision_number",
            "content_hash",
        ):
            assert approved[field] == revision[field]
        assert approved["approval_state"] == "approved"
        return approved

    async def request_export(
        self,
        pack_id: str,
        *,
        revision_ids: list[str],
        formats: list[str],
        include_media: bool,
    ) -> dict[str, Any]:
        return await self.post_json(
            f"/content-packs/{pack_id}/exports",
            {
                "content_pack_id": pack_id,
                "revision_ids": revision_ids,
                "formats": formats,
                "include_media": include_media,
            },
            expected_status=202,
        )

    async def export_for_job(self, job_id: str) -> dict[str, Any]:
        return await self.get_json(f"/exports/{job_id}")

    async def assert_export_downloads(self, export: dict[str, Any]) -> None:
        assert export["downloads"]
        for path in export["downloads"]:
            response = await self.client.get(path)
            assert response.status_code == 200, response.text
            assert response.content

    async def create_manual_plan(
        self,
        revision_id: str,
        *,
        scheduled_for: datetime,
        display_timezone: str,
    ) -> dict[str, Any]:
        return await self.post_json(
            "/manual-publication-plans",
            {
                "revision_id": revision_id,
                "scheduled_for": scheduled_for.isoformat(),
                "display_timezone": display_timezone,
            },
            expected_status=201,
        )

    async def complete_all_checks_and_mark_published(
        self,
        plan: dict[str, Any],
        *,
        external_url: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        ready = await self.patch_json(
            f"/manual-publication-plans/{plan['id']}/checklist",
            {"checklist_state": {key: True for key in plan["checklist_state"]}},
            expected_status=200,
        )
        assert ready["status"] == "ready"
        assert all(ready["checklist_state"].values())
        return await self.post_json(
            f"/manual-publication-plans/{plan['id']}/mark-published",
            {"external_url": external_url, "note": note},
            expected_status=200,
        )

    async def calendar(
        self,
        *,
        start: datetime,
        end: datetime,
        display_timezone: str,
    ) -> dict[str, Any]:
        return await self.get_json(
            "/calendar",
            params={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "timezone": display_timezone,
            },
        )


@pytest_asyncio.fixture
async def app_harness(
    release3_factory,
    acceptance_profile_resolver,
    tmp_path: Path,
):
    resolver = acceptance_profile_resolver
    research_backend = FakeResearchBackend.from_fixture(ROOT / "backend/tests/fixtures/research_brief.json")
    export_root = tmp_path / "exports"
    media_root = tmp_path / "media"
    media_root.mkdir()
    async with release3_factory() as session:
        defaults = await seed_default_telegram_configuration(
            session,
            openrouter_available=False,
        )
        prompts = await seed_default_editorial_prompts(session)
        await session.commit()
        ids = {
            "brand_id": defaults.brand.id,
            "fake_provider_profile_id": defaults.provider("fake").id,
            "canonical_prompt_version_id": prompts.canonical_story.id,
            "telegram_prompt_version_id": prompts.telegram_pack.id,
            "instagram_prompt_version_id": prompts.instagram_pack.id,
            "x_prompt_version_id": prompts.x_pack.id,
            "blog_prompt_version_id": prompts.blog_pack.id,
        }

    async def override_session():
        async with release3_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_editorial_profile_resolver] = lambda: resolver
    app.dependency_overrides[_export_root] = lambda: export_root
    app.dependency_overrides[_media_root] = lambda: media_root
    registry = build_default_registry(
        capabilities=("ingestion", "generation"),
        profile_resolver=resolver,
        research_backend_resolver=lambda _profile: research_backend,
        export_root=export_root,
        media_root=media_root,
    )
    worker = WorkerRunner(
        session_factory=release3_factory,
        handler_registry=registry,
        provider_registry=build_default_provider_registry(),
        worker_id="release-acceptance-worker",
        capabilities=("ingestion", "generation"),
        heartbeat_seconds=60,
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield AppHarness(
                client=client,
                session_factory=release3_factory,
                worker=worker,
                export_root=export_root,
                media_root=media_root,
                **ids,
            )
    finally:
        app.dependency_overrides.clear()
        await worker.close()


@pytest_asyncio.fixture
async def researched_story(app_harness: AppHarness) -> ResearchedStory:
    return await app_harness.create_researched_story()
