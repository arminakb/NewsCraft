from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.models import AutomationNodeRun, AutomationRun
from app.automations.definitions.schedule_execution import build_scheduled_automation_handler
from app.automations.definitions.schemas import AutomationCreate
from app.automations.definitions.service import AutomationDefinitionService
from app.db.models import (
    ArticleCollection,
    ArticleCollectionItem,
    ContentItem,
    MediaAsset,
)
from app.db.session import get_session
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution
from app.main import app
from app.retention.service import RetentionPolicyInput, RetentionService
from app.security.auth import TEST_ADMIN

NOW = datetime(2026, 7, 21, 8, tzinfo=UTC)


async def test_collection_names_are_trimmed_unique_and_renameable(
    db_session: AsyncSession,
):
    created = await _request(
        db_session,
        "POST",
        "/article-collections",
        json={"name": "  Reading Queue  "},
    )

    assert created.status_code == 201
    collection = created.json()
    assert set(collection) == {
        "id",
        "name",
        "article_count",
        "created_at",
        "updated_at",
    }
    assert collection["name"] == "Reading Queue"
    assert collection["article_count"] == 0

    duplicate = await _request(
        db_session,
        "POST",
        "/article-collections",
        json={"name": "reading queue"},
    )
    assert duplicate.status_code == 409

    other = await _create_collection(db_session, "Research")
    rename_collision = await _request(
        db_session,
        "PATCH",
        f"/article-collections/{other['id']}",
        json={"name": "READING QUEUE"},
    )
    assert rename_collision.status_code == 409

    renamed = await _request(
        db_session,
        "PATCH",
        f"/article-collections/{collection['id']}",
        json={"name": "  Long Reads  "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Long Reads"
    assert renamed.json()["article_count"] == 0

    listed = await _request(db_session, "GET", "/article-collections")
    assert listed.status_code == 200
    assert [row["name"] for row in listed.json()] == ["Long Reads", "Research"]

    for invalid_name in ("   ", "x" * 61):
        invalid = await _request(
            db_session,
            "POST",
            "/article-collections",
            json={"name": invalid_name},
        )
        assert invalid.status_code == 422


async def test_membership_is_idempotent_supports_multiple_collections_and_never_deletes_article(
    db_session: AsyncSession,
):
    article = _article(title="Saved article")
    db_session.add(article)
    await db_session.commit()
    first = await _create_collection(db_session, "Reading")
    second = await _create_collection(db_session, "Research")

    for collection_id in (first["id"], second["id"]):
        for _ in range(2):
            saved = await _request(
                db_session,
                "PUT",
                f"/article-collections/{collection_id}/articles/{article.id}",
            )
            assert saved.status_code == 204

    collections = (await _request(db_session, "GET", "/article-collections")).json()
    assert {row["name"]: row["article_count"] for row in collections} == {
        "Reading": 1,
        "Research": 1,
    }

    summary = (await _request(db_session, "GET", "/articles?limit=10")).json()["items"][0]
    assert summary["saved"] is True
    assert set(summary["saved_collection_ids"]) == {first["id"], second["id"]}

    for _ in range(2):
        removed = await _request(
            db_session,
            "DELETE",
            f"/article-collections/{first['id']}/articles/{article.id}",
        )
        assert removed.status_code == 204

    detail = await _request(db_session, "GET", f"/articles/{article.id}")
    assert detail.status_code == 200
    assert detail.json()["saved"] is True
    assert detail.json()["saved_collection_ids"] == [second["id"]]

    deleted = await _request(db_session, "DELETE", f"/article-collections/{second['id']}")
    assert deleted.status_code == 204
    surviving_article = await _request(db_session, "GET", f"/articles/{article.id}")
    assert surviving_article.status_code == 200
    assert surviving_article.json()["saved"] is False
    assert surviving_article.json()["saved_collection_ids"] == []


async def test_collection_article_trigger_starts_one_durable_run_and_preserves_article_output(
    db_session: AsyncSession,
):
    article = _article(title="Trigger article")
    collection = ArticleCollection(name="Trigger queue", normalized_name="trigger queue")
    db_session.add_all([article, collection])
    await db_session.flush()
    graph = {
        "schema_version": 1,
        "entry_node_id": "collection-trigger-1",
        "nodes": [
            {
                "id": "collection-trigger-1",
                "type": "collection_article_added",
                "config": {"collection_id": str(collection.id)},
            }
        ],
        "edges": [],
        "output_node_ids": ["collection-trigger-1"],
        "metadata": {"layout": {}},
    }
    created = await AutomationDefinitionService(db_session).create_automation(
        AutomationCreate(name="Collection trigger", graph=graph),
        principal=TEST_ADMIN,
        idempotency_key="collection-trigger-create",
    )
    activated = await AutomationDefinitionService(db_session).activate(
        created.id,
        expected_revision=1,
        principal=TEST_ADMIN,
        capability_status=None,
        idempotency_key="collection-trigger-activate",
    )
    await db_session.commit()

    first = await _request(
        db_session,
        "PUT",
        f"/article-collections/{collection.id}/articles/{article.id}",
    )
    second = await _request(
        db_session,
        "PUT",
        f"/article-collections/{collection.id}/articles/{article.id}",
    )
    assert first.status_code == second.status_code == 204
    jobs = list(
        await db_session.scalars(
            select(WorkflowJob).where(WorkflowJob.job_type == "automation.run.start")
        )
    )
    assert len(jobs) == 1
    assert jobs[0].payload["collection_id"] == str(collection.id)
    assert jobs[0].payload["article_id"] == str(article.id)
    assert jobs[0].payload["automation_version_id"] == str(activated.active_version_id)
    events = list(
        await db_session.scalars(
            select(WorkflowEvent).where(WorkflowEvent.event_type == "collection.article_added")
        )
    )
    assert len(events) == 1
    assert events[0].event_data["article_id"] == str(article.id)
    assert events[0].event_data["collection_id"] == str(collection.id)
    assert events[0].event_data["added_at"]
    assert events[0].event_data["actor_id"] == "test_harness:pytest"

    job = await JobRepository(db_session).claim_next_job(
        worker_id="collection-trigger-test",
        lease_seconds=300,
        allowed_job_types=("automation.run.start",),
    )
    assert job is not None
    execution = JobExecution.from_job(job)
    await db_session.commit()
    result = await build_scheduled_automation_handler(None)(
        execution,
        JobContext(session=db_session, providers=build_default_provider_registry()),
    )
    await JobRepository(db_session).finish_job(
        job_id=execution.id,
        worker_id="collection-trigger-test",
        result=result,
    )
    await db_session.commit()

    run = await db_session.scalar(select(AutomationRun).where(AutomationRun.automation_id == created.id))
    assert run is not None
    node = await db_session.scalar(
        select(AutomationNodeRun).where(AutomationNodeRun.automation_run_id == run.id)
    )
    assert run.status == "succeeded"
    assert run.trigger_metadata["article_id"] == str(article.id)
    assert run.trigger_metadata["collection_id"] == str(collection.id)
    assert run.trigger_metadata["workflow_version"] == 1
    assert run.trigger_metadata["trigger_node_id"] == "collection-trigger-1"
    assert node is not None and node.status == "succeeded"
    assert result["output"] == {
        "article": {
            "id": str(article.id),
            "title": "Trigger article",
            "content": "Body",
            "url": "https://example.com/trigger-article",
            "source_id": None,
            "published_at": None,
            "primary_media": None,
        },
        "trigger": {
            "type": "collection_article_added",
            "event_type": "collection.article_added",
            "collection_id": str(collection.id),
            "article_id": str(article.id),
            "occurred_at": result["output"]["trigger"]["occurred_at"],
        },
        "collection": {
            "id": str(collection.id),
            "name": "Trigger queue",
        },
    }


async def test_articles_collection_filter_preserves_pagination_and_rejects_unknown_ids(
    db_session: AsyncSession,
):
    articles = [_article(title=f"Collected {index}", sort_at=NOW - timedelta(minutes=index)) for index in range(4)]
    db_session.add_all(articles)
    await db_session.commit()
    selected = await _create_collection(db_session, "Selected")
    other = await _create_collection(db_session, "Other")
    for article in articles[:3]:
        response = await _request(
            db_session,
            "PUT",
            f"/article-collections/{selected['id']}/articles/{article.id}",
        )
        assert response.status_code == 204
    await _request(
        db_session,
        "PUT",
        f"/article-collections/{other['id']}/articles/{articles[3].id}",
    )

    first = await _request(
        db_session,
        "GET",
        f"/articles?collection_id={selected['id']}&limit=1",
    )
    assert first.status_code == 200
    assert first.json()["result_count"] == 3
    assert [row["id"] for row in first.json()["items"]] == [str(articles[0].id)]
    cursor = first.json()["next_cursor"]
    assert cursor

    second = await _request(
        db_session,
        "GET",
        f"/articles?collection_id={selected['id']}&limit=1&cursor={cursor}",
    )
    assert second.status_code == 200
    assert second.json()["result_count"] == 3
    assert [row["id"] for row in second.json()["items"]] == [str(articles[1].id)]
    assert second.json()["items"][0]["saved"] is True
    assert second.json()["items"][0]["saved_collection_ids"] == [selected["id"]]

    changed_filter = await _request(
        db_session,
        "GET",
        f"/articles?collection_id={other['id']}&cursor={cursor}",
    )
    assert changed_filter.status_code == 422

    missing_collection_id = uuid4()
    missing_article_id = uuid4()
    assert (
        await _request(
            db_session,
            "GET",
            f"/articles?collection_id={missing_collection_id}",
        )
    ).status_code == 404
    for method, collection_id, article_id in (
        ("PUT", missing_collection_id, articles[0].id),
        ("DELETE", missing_collection_id, articles[0].id),
        ("PUT", UUID(selected["id"]), missing_article_id),
        ("DELETE", UUID(selected["id"]), missing_article_id),
    ):
        response = await _request(
            db_session,
            method,
            f"/article-collections/{collection_id}/articles/{article_id}",
        )
        assert response.status_code == 404

    assert (
        await _request(
            db_session,
            "DELETE",
            f"/article-collections/{missing_collection_id}",
        )
    ).status_code == 404


async def test_saved_article_primary_media_is_protected_from_retention(
    db_session: AsyncSession,
    tmp_path: Path,
):
    saved_path = tmp_path / "saved.webp"
    unreferenced_path = tmp_path / "unreferenced.webp"
    saved_path.write_bytes(b"saved")
    unreferenced_path.write_bytes(b"unreferenced")
    old_at = NOW - timedelta(days=90)
    saved_media = _stored_media(saved_path, created_at=old_at)
    unreferenced_media = _stored_media(unreferenced_path, created_at=old_at)
    db_session.add_all([saved_media, unreferenced_media])
    await db_session.flush()
    article = _article(title="Retention protected", primary_image_id=saved_media.id)
    collection = ArticleCollection(name="Protected", normalized_name="protected")
    db_session.add_all([article, collection])
    await db_session.flush()
    db_session.add(
        ArticleCollectionItem(
            collection_id=collection.id,
            content_item_id=article.id,
        )
    )
    await db_session.commit()

    preview = await RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path,
    ).preview(RetentionPolicyInput(unreferenced_media_days=30))
    candidate_ids = {
        candidate.record_id for candidate in preview.candidates if candidate.category == "unreferenced_media"
    }

    assert unreferenced_media.id in candidate_ids
    assert saved_media.id not in candidate_ids


async def _create_collection(session: AsyncSession, name: str) -> dict:
    response = await _request(
        session,
        "POST",
        "/article-collections",
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()


async def _request(
    session: AsyncSession,
    method: str,
    path: str,
    **kwargs,
):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.clear()


def _article(*, title: str, primary_image_id: UUID | None = None, sort_at: datetime = NOW) -> ContentItem:
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
        primary_image_id=primary_image_id,
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


def _stored_media(path: Path, *, created_at: datetime) -> MediaAsset:
    return MediaAsset(
        original_url=f"https://media.example/{path.name}",
        normalized_url=f"https://media.example/{path.name}",
        url_hash=f"hash-{path.name}",
        kind="image",
        mime_type="image/webp",
        width=1200,
        height=675,
        source_field="body",
        fetch_status="fetched",
        storage_path=path.name,
        byte_length=path.stat().st_size,
        media_quality="good",
        media_confidence=Decimal("1"),
        is_primary_candidate=True,
        is_primary=True,
        media_source_type="downloaded",
        asset_role="primary_image",
        raw_metadata={},
        created_at=created_at,
    )
