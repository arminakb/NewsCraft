from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import ContentItem, Source
from app.db.session import get_session
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    ContentPack,
    PlatformVariant,
    PlatformVariantRevision,
)
from app.jobs.models import WorkflowJob
from app.llm_providers.models import LLMProvider
from app.main import app
from app.publishing.models import Destination, Publication, PublishJob
from app.research.models import ResearchRun
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision

CONTENT_ITEMS = 20_000
STORIES = 1_000
JOBS = 10_000
PACKS = 250
PUBLICATIONS = 250
RESEARCH_RUNS = 250
SOURCES = 20

SURFACES: dict[str, tuple[str, ...]] = {
    "Today": (
        "/jobs/summary",
        "/jobs?status=running&limit=25",
        "/jobs?status=failed&status=needs_review&limit=25",
        "/jobs?status=succeeded&limit=10",
        "/telegram/publication-outcomes",
        "/telegram/reconciliation",
    ),
    "Inbox": ("/stories?editorial_state=inbox&limit=50",),
    "Feed": ("/articles?limit=50", "/articles/facets"),
    "Raw Content": ("/content-items?limit=100",),
    "Drafts": ("/content-pack-requests",),
    "Jobs": ("/jobs?limit=100", "/jobs/summary"),
    "Library": (
        "/library/originals?limit=50",
        "/library/evidence?limit=50",
        "/library/research-runs?limit=50",
    ),
}


def _batches(rows: list[dict], size: int = 1_000) -> Iterable[list[dict]]:
    for offset in range(0, len(rows), size):
        yield rows[offset : offset + size]


async def _insert_rows(session, model, rows: list[dict]) -> None:
    for batch in _batches(rows):
        await session.execute(insert(model), batch)


async def _truncate_database(engine: AsyncEngine) -> None:
    table_names = [engine.dialect.identifier_preparer.quote(table.name) for table in Base.metadata.sorted_tables]
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE"))


async def _seed_dataset(factory: async_sessionmaker) -> dict[str, int]:
    now = datetime.now(UTC)
    source_ids = [uuid4() for _ in range(SOURCES)]
    content_ids = [uuid4() for _ in range(CONTENT_ITEMS)]
    story_ids = [uuid4() for _ in range(STORIES)]
    snapshot_ids = [uuid4() for _ in range(STORIES)]
    story_revision_ids = [uuid4() for _ in range(PACKS)]
    pack_ids = [uuid4() for _ in range(PACKS)]
    variant_ids = [uuid4() for _ in range(PACKS)]
    variant_revision_ids = [uuid4() for _ in range(PACKS)]
    workflow_job_ids = [uuid4() for _ in range(JOBS)]
    publish_job_ids = [uuid4() for _ in range(PUBLICATIONS)]
    destination_id = uuid4()
    brand_id = uuid4()
    provider_id = uuid4()

    async with factory() as session:
        await _insert_rows(
            session,
            Source,
            [
                {
                    "id": source_id,
                    "platform": "rss",
                    "name": f"Benchmark source {index:02d}",
                    "feed_url": f"https://benchmark.invalid/feed/{index}",
                    "homepage_url": f"https://benchmark.invalid/source/{index}",
                    "source_group": "benchmark",
                    "language_hint": "fa" if index % 3 == 0 else "en",
                    "active": True,
                }
                for index, source_id in enumerate(source_ids)
            ],
        )
        await _insert_rows(
            session,
            ContentItem,
            [
                {
                    "id": content_id,
                    "item_type": "article",
                    "canonical_url": f"https://benchmark.invalid/articles/{index}",
                    "title": f"Representative newsroom item {index}",
                    "summary": f"Summary for representative item {index}",
                    "content_text": (f"Evidence-rich body for item {index}. " * 20),
                    "language_code": "fa" if index % 3 == 0 else "en",
                    "script_code": "Arab" if index % 3 == 0 else "Latn",
                    "direction": "rtl" if index % 3 == 0 else "ltr",
                    "tags": [f"topic-{index % 12}", f"desk-{index % 5}"],
                    "published_at": now - timedelta(seconds=index),
                    "sort_at": now - timedelta(seconds=index),
                    "date_parse_status": "parsed",
                    "primary_source_id": source_ids[index % SOURCES],
                    "status": ("approved" if index % 4 == 0 else "new"),
                    "score": index % 101,
                    "metrics": {"classification": {"category": f"topic-{index % 12}"}},
                    "content_type": ("analysis" if index % 5 == 0 else "article"),
                    "classification_metadata": {
                        "source_domain": "benchmark.invalid",
                        "source_name": f"Benchmark source {index % SOURCES:02d}",
                        "source_platform": "rss",
                    },
                    "quality_status": ("ready" if index % 4 == 0 else "needs_review"),
                    "is_rewrite_ready": index % 4 == 0,
                }
                for index, content_id in enumerate(content_ids)
            ],
        )
        await _insert_rows(
            session,
            Story,
            [
                {
                    "id": story_id,
                    "title": f"Representative story {index}",
                    "status": ("inbox" if index % 4 != 0 else "shortlisted"),
                    "primary_language": "fa" if index % 3 == 0 else "en",
                    "created_at": now - timedelta(minutes=index),
                    "updated_at": now - timedelta(seconds=index),
                }
                for index, story_id in enumerate(story_ids)
            ],
        )
        await _insert_rows(
            session,
            StoryEvidenceSnapshot,
            [
                {
                    "id": snapshot_id,
                    "story_id": story_ids[index],
                    "content_item_id": content_ids[index],
                    "evidence_key": f"benchmark:{index}",
                    "source_url": f"https://benchmark.invalid/articles/{index}",
                    "title": f"Representative evidence {index}",
                    "content_text": f"Immutable representative evidence {index}. " * 12,
                    "authors": [f"Reporter {index % 30}"],
                    "published_at": now - timedelta(minutes=index),
                    "content_sha256": hashlib.sha256(f"evidence-{index}".encode()).hexdigest(),
                    "captured_at": now - timedelta(seconds=index),
                }
                for index, snapshot_id in enumerate(snapshot_ids)
            ],
        )
        await _insert_rows(
            session,
            StoryRevision,
            [
                {
                    "id": revision_id,
                    "story_id": story_ids[index],
                    "revision_number": 1,
                    "narrative": f"Canonical representative narrative {index}",
                    "facts": [],
                    "disagreements": [],
                    "angles": [],
                    "citations": [],
                    "created_by": "benchmark",
                    "created_at": now - timedelta(seconds=index),
                }
                for index, revision_id in enumerate(story_revision_ids)
            ],
        )
        session.add_all(
            [
                BrandProfile(
                    id=brand_id,
                    name="Benchmark brand",
                    output_language="en",
                    tone="neutral",
                    editorial_rules=[],
                    attribution_rules={},
                    default_hashtags=[],
                    platform_preferences={},
                    is_default=True,
                ),
                AIProviderProfile(
                    id=provider_id,
                    name="Benchmark fake provider",
                    provider_type="fake",
                    default_model="fake-v1",
                    settings={},
                    enabled=True,
                ),
                LLMProvider(
                    id=provider_id,
                    name="Benchmark fake provider",
                    protocol="fake",
                    base_url=None,
                    default_model="fake-v1",
                    enabled=True,
                    secret_id=None,
                    settings={},
                    health_status="healthy",
                    generation_capability="ready",
                    research_capability="ready",
                    ownership="system_managed",
                ),
                Destination(
                    id=destination_id,
                    name="Benchmark Telegram destination",
                    platform="telegram",
                    target_ref="@benchmark",
                    secret_ref="BENCHMARK_TELEGRAM_TOKEN",
                    enabled=True,
                    health_status="healthy",
                    settings={},
                ),
            ]
        )
        await session.flush()
        await _insert_rows(
            session,
            ContentPack,
            [
                {
                    "id": pack_ids[index],
                    "story_revision_id": story_revision_ids[index],
                    "brand_profile_id": brand_id,
                    "status": "draft",
                    "created_at": now - timedelta(seconds=index),
                    "updated_at": now - timedelta(seconds=index),
                }
                for index in range(PACKS)
            ],
        )
        await _insert_rows(
            session,
            PlatformVariant,
            [
                {
                    "id": variant_ids[index],
                    "content_pack_id": pack_ids[index],
                    "platform": "telegram",
                    "created_at": now - timedelta(seconds=index),
                }
                for index in range(PACKS)
            ],
        )
        await _insert_rows(
            session,
            PlatformVariantRevision,
            [
                {
                    "id": variant_revision_ids[index],
                    "platform_variant_id": variant_ids[index],
                    "revision_number": 1,
                    "content": {
                        "body": f"Representative Telegram draft {index}",
                        "parse_mode": "HTML",
                        "buttons": [],
                        "source_item_id": None,
                        "source_url": None,
                        "media_policy": "omit",
                        "media_asset_ids": [],
                        "direction": "ltr",
                        "dry_run": False,
                    },
                    "content_hash": hashlib.sha256(f"variant-{index}".encode()).hexdigest(),
                    "evidence_map": [],
                    "validation_results": [],
                    "approval_state": ("approved" if index % 3 == 0 else "pending_review"),
                    "approved_at": (now - timedelta(seconds=index) if index % 3 == 0 else None),
                    "created_by": "generation",
                    "created_at": now - timedelta(seconds=index),
                }
                for index in range(PACKS)
            ],
        )
        statuses = ("queued", "running", "failed", "needs_review", "succeeded")
        await _insert_rows(
            session,
            WorkflowJob,
            [
                {
                    "id": job_id,
                    "job_type": ("content_pack.generate" if index < PACKS else f"benchmark.task.{index % 8}"),
                    "status": statuses[index % len(statuses)],
                    "payload": (
                        {
                            "story_id": str(story_ids[index]),
                            "brand_profile_id": str(brand_id),
                            "platforms": ["telegram"],
                        }
                        if index < PACKS
                        else {"benchmark_index": index}
                    ),
                    "result": {},
                    "idempotency_key": f"benchmark-job-{index}",
                    "origin": "manual",
                    "scheduled_for": now - timedelta(seconds=index),
                    "progress": (100 if statuses[index % len(statuses)] == "succeeded" else index % 100),
                    "started_at": (now - timedelta(minutes=index) if index % 5 in {1, 4} else None),
                    "finished_at": (now - timedelta(seconds=index) if index % 5 == 4 else None),
                    "created_at": now - timedelta(seconds=index),
                    "updated_at": now - timedelta(seconds=index),
                }
                for index, job_id in enumerate(workflow_job_ids)
            ],
        )
        await _insert_rows(
            session,
            ResearchRun,
            [
                {
                    "id": uuid4(),
                    "story_id": story_ids[index],
                    "requested_mode": "manual",
                    "provider_profile_id": provider_id,
                    "status": "succeeded",
                    "query_budget": 5,
                    "page_budget": 10,
                    "time_budget_seconds": 120,
                    "result_story_revision_id": story_revision_ids[index],
                    "created_at": now - timedelta(seconds=index),
                    "started_at": now - timedelta(seconds=index + 2),
                    "finished_at": now - timedelta(seconds=index),
                }
                for index in range(RESEARCH_RUNS)
            ],
        )
        await _insert_rows(
            session,
            PublishJob,
            [
                {
                    "id": publish_job_ids[index],
                    "workflow_job_id": workflow_job_ids[index],
                    "destination_id": destination_id,
                    "platform_variant_revision_id": variant_revision_ids[index],
                    "status": "succeeded",
                    "idempotency_key": f"benchmark-publish-{index}",
                    "payload_hash": hashlib.sha256(f"publish-{index}".encode()).hexdigest(),
                    "created_at": now - timedelta(seconds=index),
                    "updated_at": now - timedelta(seconds=index),
                }
                for index in range(PUBLICATIONS)
            ],
        )
        await _insert_rows(
            session,
            Publication,
            [
                {
                    "id": uuid4(),
                    "publish_job_id": publish_job_ids[index],
                    "destination_id": destination_id,
                    "platform_variant_revision_id": variant_revision_ids[index],
                    "remote_message_ids": [10_000 + index],
                    "permalink": f"https://t.me/benchmark/{10_000 + index}",
                    "payload_hash": hashlib.sha256(f"publish-{index}".encode()).hexdigest(),
                    "published_at": now - timedelta(seconds=index),
                    "reconciliation_status": "confirmed",
                }
                for index in range(PUBLICATIONS)
            ],
        )
        await session.commit()

    return {
        "content_items": CONTENT_ITEMS,
        "stories": STORIES,
        "jobs": JOBS,
        "content_packs": PACKS,
        "platform_revisions": PACKS,
        "publications": PUBLICATIONS,
        "research_runs": RESEARCH_RUNS,
        "sources": SOURCES,
    }


class QueryCounter:
    def __init__(self, engine: AsyncEngine) -> None:
        self.count = 0
        event.listen(engine.sync_engine, "before_cursor_execute", self._before_cursor_execute)

    def _before_cursor_execute(self, *_args) -> None:
        self.count += 1

    def reset(self) -> None:
        self.count = 0

    def close(self, engine: AsyncEngine) -> None:
        event.remove(engine.sync_engine, "before_cursor_execute", self._before_cursor_execute)


async def _request_surface(client: AsyncClient, paths: tuple[str, ...]) -> int:
    responses = await asyncio.gather(*(client.get(path) for path in paths))
    failures = [response for response in responses if response.status_code != 200]
    if failures:
        failure = failures[0]
        raise RuntimeError(f"{failure.request.url.path} returned {failure.status_code}: {failure.text[:500]}")
    return sum(len(response.content) for response in responses)


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


async def _measure(
    engine: AsyncEngine,
    factory: async_sessionmaker,
    *,
    repetitions: int,
) -> dict[str, dict]:
    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    counter = QueryCounter(engine)
    output: dict[str, dict] = {}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://benchmark") as client:
            for surface, paths in SURFACES.items():
                await _request_surface(client, paths)
                timings: list[float] = []
                query_counts: list[int] = []
                response_bytes = 0
                for _ in range(repetitions):
                    counter.reset()
                    started = perf_counter()
                    response_bytes = await _request_surface(client, paths)
                    timings.append((perf_counter() - started) * 1_000)
                    query_counts.append(counter.count)
                output[surface] = {
                    "requests": list(paths),
                    "query_counts": query_counts,
                    "query_count_max": max(query_counts),
                    "timings_ms": [round(value, 2) for value in timings],
                    "p50_ms": round(_percentile(timings, 0.50), 2),
                    "p95_ms": round(_percentile(timings, 0.95), 2),
                    "response_bytes": response_bytes,
                }
    finally:
        counter.close(engine)
        app.dependency_overrides.pop(get_session, None)
    return output


async def _run(repetitions: int) -> dict:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("TEST_DATABASE_URL is required")
    database_name = make_url(database_url).database
    if not database_name or not database_name.endswith("_test"):
        raise RuntimeError("Refusing performance baseline unless the database name ends in '_test'")
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await _truncate_database(engine)
        dataset = await _seed_dataset(factory)
        surfaces = await _measure(engine, factory, repetitions=repetitions)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "database": "PostgreSQL",
            "repetitions": repetitions,
            "dataset": dataset,
            "surfaces": surfaces,
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture the refactor performance baseline on disposable PostgreSQL")
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 11))
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print(json.dumps(asyncio.run(_run(args.repetitions)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
