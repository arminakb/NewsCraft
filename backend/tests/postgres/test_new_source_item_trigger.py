from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.models import AutomationRun
from app.automations.definitions.source_execution import handle_new_source_item
from app.db.models import Source, SourceItem
from app.db.session import get_session
from app.ingestion.repository import IngestionRepository
from app.ingestion.workflow import FetchedSourceBatch, IngestionWorkflow, PreparedSource
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution
from app.main import app
from app.sources.base import ParsedSourceItem


async def test_new_source_item_event_creates_one_durable_run_and_worker_output(
    db_session: AsyncSession,
):
    source = Source(
        platform="rss",
        name="Durable RSS",
        feed_url="https://example.test/feed.xml",
        source_group="news",
        language_hint="en",
        active=True,
    )
    db_session.add(source)
    await db_session.flush()
    source_id = source.id

    created = await _request(
        db_session,
        "POST",
        "/automations",
        headers={"Idempotency-Key": f"source-trigger-create-{uuid4()}"},
        json={"name": "New source item workflow", "graph": _graph(str(source_id))},
    )
    assert created.status_code == 201, created.text
    automation_id = created.json()["id"]
    activated = await _request(
        db_session,
        "POST",
        f"/automations/{automation_id}/activate",
        headers={"Idempotency-Key": f"source-trigger-activate-{uuid4()}"},
        json={"expected_revision": 1},
    )
    assert activated.status_code == 200, activated.text
    await db_session.commit()

    run = await IngestionRepository(db_session).create_run("test", "test-parser")
    await db_session.commit()
    batch = _batch(source, "stable-rss-guid")
    persisted = await IngestionWorkflow().persist_source(db_session, run_id=run.id, batch=batch)
    assert persisted.items == 1
    await db_session.commit()

    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WorkflowEvent)
            .where(WorkflowEvent.event_type == "source_item.created")
        )
        == 1
    )
    assert await db_session.scalar(select(func.count()).select_from(AutomationRun)) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WorkflowJob)
            .where(WorkflowJob.job_type == "automation.run.start")
        )
        == 1
    )

    job = await JobRepository(db_session).claim_next_job(
        worker_id="source-trigger-test",
        lease_seconds=60,
        allowed_job_types=("automation.run.start",),
        now=datetime.now(UTC),
    )
    assert job is not None
    execution = JobExecution.from_job(job)
    result = await handle_new_source_item(execution, JobContext(session=db_session, providers=None))  # type: ignore[arg-type]
    await JobRepository(db_session).finish_job(
        job_id=job.id,
        worker_id="source-trigger-test",
        result=result,
        now=datetime.now(UTC),
    )
    await db_session.commit()

    automation_run = await db_session.scalar(
        select(AutomationRun).where(AutomationRun.automation_id == UUID(automation_id))
    )
    assert automation_run is not None
    assert automation_run.status == "succeeded"
    stored_job = await db_session.get(WorkflowJob, job.id)
    assert stored_job is not None
    output = stored_job.result["output"]
    assert output["source_item"]["source_id"] == str(source_id)
    assert output["source_item"]["title"] == "Durable item"
    assert output["content_item"]["content_type"] == "article"
    assert output["trigger"]["type"] == "new_source_item"

    second_run = await IngestionRepository(db_session).create_run("test-repeat", "test-parser")
    await db_session.commit()
    repeated = await IngestionWorkflow().persist_source(
        db_session,
        run_id=second_run.id,
        batch=_batch(source, "stable-rss-guid", title="Edited durable item"),
    )
    assert repeated.items == 1
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(SourceItem)) == 1
    assert await db_session.scalar(select(func.count()).select_from(AutomationRun)) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WorkflowJob)
            .where(WorkflowJob.job_type == "automation.run.start")
        )
        == 1
    )


def _graph(source_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "entry_node_id": "source-trigger-1",
        "nodes": [
            {
                "id": "source-trigger-1",
                "type": "new_source_item",
                "config": {"source_ids": [source_id]},
            }
        ],
        "edges": [],
        "output_node_ids": ["source-trigger-1"],
        "metadata": {"layout": {}},
    }


def _batch(source: Source, external_id: str, *, title: str = "Durable item") -> FetchedSourceBatch:
    return FetchedSourceBatch(
        source=PreparedSource(
            id=source.id,
            name=source.name,
            platform=source.platform,
            feed_url=source.feed_url,
            telegram_username=source.telegram_username,
            default_timezone=source.default_timezone or "UTC",
            etag=source.etag,
            last_modified=source.last_modified,
        ),
        request_url=source.feed_url or "https://example.test/feed.xml",
        final_url=source.feed_url or "https://example.test/feed.xml",
        http_status=200,
        headers={"content-type": "application/rss+xml"},
        content_type="application/rss+xml",
        raw_text="<rss><channel><item /></channel></rss>",
        parser_warnings=(),
        parsed_items=(
            ParsedSourceItem(
                external_id_raw=external_id,
                external_id_norm=external_id,
                source_url="https://example.test/items/durable",
                source_url_norm="https://example.test/items/durable",
                canonical_url_candidate="https://example.test/items/durable",
                title=title,
                summary="Durable summary",
                content_html="<p>Durable content body with enough detail for classification.</p>",
                content_text="Durable content body with enough detail for classification.",
                author="Desk",
                categories=["news"],
                published_raw="2026-08-05T08:00:00+00:00",
                published_at=datetime(2026, 8, 5, 8, tzinfo=UTC),
                date_parse_status="parsed",
            ),
        ),
    )


async def _request(session: AsyncSession, method: str, path: str, **kwargs):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.clear()
