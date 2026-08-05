from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.collection_execution import handle_collection_article_added
from app.automations.definitions.models import AutomationRun
from app.db.models import ContentItem
from app.db.session import get_session
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution
from app.main import app

NOW = datetime.now(UTC) + timedelta(minutes=5)


async def test_saving_new_collection_membership_starts_one_durable_trigger_run_and_is_idempotent(
    db_session: AsyncSession,
):
    collection = await _create_collection(db_session, "Reading queue")
    article = _article("First saved article")
    db_session.add(article)
    await db_session.commit()

    created = await _request(
        db_session,
        "POST",
        "/automations",
        headers={"Idempotency-Key": "collection-trigger-create"},
        json={"name": "Saved article workflow", "graph": _graph(collection["id"])},
    )
    assert created.status_code == 201, created.text
    automation_id = created.json()["id"]
    activated = await _request(
        db_session,
        "POST",
        f"/automations/{automation_id}/activate",
        headers={"Idempotency-Key": "collection-trigger-activate"},
        json={"expected_revision": 1},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["lifecycle"] == "active"

    saved = await _request(db_session, "PUT", f"/article-collections/{collection['id']}/articles/{article.id}")
    assert saved.status_code == 204
    repeated = await _request(db_session, "PUT", f"/article-collections/{collection['id']}/articles/{article.id}")
    assert repeated.status_code == 204

    event_count = await db_session.scalar(
        select(func.count()).select_from(WorkflowEvent).where(WorkflowEvent.event_type == "collection.article_added")
    )
    run_count = await db_session.scalar(select(func.count()).select_from(AutomationRun))
    job_count = await db_session.scalar(
        select(func.count()).select_from(WorkflowJob).where(WorkflowJob.job_type == "automation.run.start")
    )
    assert event_count == 1
    assert run_count == 1
    assert job_count == 1

    result = await _run_one_collection_job(db_session)
    assert result["outcome"] == "started"
    run = await db_session.scalar(select(AutomationRun).where(AutomationRun.automation_id == UUID(automation_id)))
    assert run is not None
    assert run.status == "succeeded"
    node_output = (
        await db_session.scalar(select(WorkflowJob.result).where(WorkflowJob.id == run.root_workflow_job_id))
    ) or {}
    assert node_output["output"]["article"]["id"] == str(article.id)
    assert node_output["output"]["article"]["title"] == "First saved article"
    assert node_output["output"]["trigger"]["collection_id"] == collection["id"]


async def test_collection_trigger_uses_stable_id_and_cancels_queued_run_after_collection_delete(
    db_session: AsyncSession,
):
    collection = await _create_collection(db_session, "Rename me")
    article = _article("Rename-safe article")
    later_article = _article("Deleted collection article", sort_at=NOW + timedelta(minutes=1))
    db_session.add_all([article, later_article])
    await db_session.commit()
    automation = await _create_and_activate(db_session, collection["id"])

    renamed = await _request(
        db_session,
        "PATCH",
        f"/article-collections/{collection['id']}",
        json={"name": "Renamed Feed"},
    )
    assert renamed.status_code == 200
    assert (
        await _request(db_session, "PUT", f"/article-collections/{collection['id']}/articles/{article.id}")
    ).status_code == 204
    await _run_one_collection_job(db_session)
    run = await db_session.scalar(
        select(AutomationRun)
        .where(AutomationRun.automation_id == UUID(automation["id"]))
        .order_by(AutomationRun.created_at)
    )
    assert run is not None and run.status == "succeeded"

    assert (
        await _request(db_session, "PUT", f"/article-collections/{collection['id']}/articles/{later_article.id}")
    ).status_code == 204
    deleted = await _request(db_session, "DELETE", f"/article-collections/{collection['id']}")
    assert deleted.status_code == 204
    result = await _run_one_collection_job(db_session)
    assert result["outcome"] == "source_unavailable"
    cancelled = list(
        await db_session.scalars(
            select(AutomationRun).where(
                AutomationRun.automation_id == UUID(automation["id"]),
                AutomationRun.status == "cancelled",
            )
        )
    )
    assert len(cancelled) == 1


async def test_paused_or_inactive_collection_workflows_do_not_create_runs(db_session: AsyncSession):
    collection = await _create_collection(db_session, "Paused collection")
    article = _article("Paused article")
    db_session.add(article)
    await db_session.commit()
    automation = await _create_and_activate(db_session, collection["id"])

    paused = await _request(
        db_session,
        "POST",
        f"/automations/{automation['id']}/pause",
        json={"expected_revision": 2},
    )
    assert paused.status_code == 200, paused.text
    assert (
        await _request(db_session, "PUT", f"/article-collections/{collection['id']}/articles/{article.id}")
    ).status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(AutomationRun)) == 0


def _graph(collection_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "entry_node_id": "collection-trigger-1",
        "nodes": [
            {
                "id": "collection-trigger-1",
                "type": "collection_article_added",
                "config": {"collection_id": collection_id},
            }
        ],
        "edges": [],
        "output_node_ids": ["collection-trigger-1"],
        "metadata": {"layout": {}},
    }


async def _create_and_activate(session: AsyncSession, collection_id: str) -> dict:
    created = await _request(
        session,
        "POST",
        "/automations",
        headers={"Idempotency-Key": f"create-{uuid4()}"},
        json={"name": f"Collection trigger {uuid4()}", "graph": _graph(collection_id)},
    )
    assert created.status_code == 201, created.text
    automation_id = created.json()["id"]
    activated = await _request(
        session,
        "POST",
        f"/automations/{automation_id}/activate",
        headers={"Idempotency-Key": f"activate-{uuid4()}"},
        json={"expected_revision": 1},
    )
    assert activated.status_code == 200, activated.text
    return activated.json()


async def _create_collection(session: AsyncSession, name: str) -> dict:
    response = await _request(session, "POST", "/article-collections", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def _run_one_collection_job(session: AsyncSession) -> dict:
    job = await JobRepository(session).claim_next_job(
        worker_id="collection-trigger-test",
        lease_seconds=60,
        allowed_job_types=("automation.run.start",),
        now=NOW,
    )
    assert job is not None
    execution = JobExecution.from_job(job)
    result = await handle_collection_article_added(execution, JobContext(session=session, providers=None))  # type: ignore[arg-type]
    await JobRepository(session).finish_job(
        job_id=job.id,
        worker_id="collection-trigger-test",
        result=result,
        now=NOW,
    )
    await session.commit()
    return result


async def _request(session: AsyncSession, method: str, path: str, **kwargs):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.clear()


def _article(title: str, *, sort_at: datetime = NOW) -> ContentItem:
    return ContentItem(
        item_type="article",
        canonical_url=f"https://example.com/{title.casefold().replace(' ', '-')}",
        title=title,
        summary="Summary",
        content_text="Body",
        content_html_sanitized="<p>Body</p>",
        language_code="en",
        script_code="Latn",
        direction="ltr",
        authors=[],
        tags=[],
        published_at=None,
        sort_at=sort_at,
        date_source="collected",
        date_parse_status="missing",
        status="new",
        score=10,
        metrics={"classification": {"category": "AI"}},
        content_type="article",
        content_type_confidence=Decimal("1"),
        classification_reasons=["test"],
        classification_metadata={"source_domain": "example.com"},
        freshness_bucket="fresh",
        source_tier="A",
        quality_status="needs_review",
        is_rewrite_ready=False,
        rewrite_blockers=[],
        score_breakdown={},
        ranking_metadata={},
        title_quality="meaningful",
        title_was_generated=False,
    )
