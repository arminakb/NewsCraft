from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    ArticleCollection,
    ArticleCollectionItem,
    ContentItem,
    ItemIdentity,
    Source,
    SourceItem,
)
from app.db.session import get_session
from app.feed.service import clear_active_feed
from app.ingestion.repository import IngestionRepository, build_item_identities
from app.main import app
from app.source_collections.models import SourceCollection, SourceCollectionMembership
from app.sources.base import ParsedSourceItem
from app.stories.models import Story, StoryEvidenceSnapshot

NOW = datetime(2026, 7, 21, 8, tzinfo=UTC)


async def test_clear_hides_feed_items_and_preserves_sources_collections_and_references(
    db_session: AsyncSession,
):
    source = Source(
        platform="rss",
        name="Clearable Wire",
        feed_url="https://clearable.example/feed",
        homepage_url="https://clearable.example",
        source_group="news",
        language_hint="en",
        active=True,
    )
    source_collection = SourceCollection(name="Monitored", normalized_name="monitored")
    article_collection = ArticleCollection(name="Saved", normalized_name="saved")
    item = _article(source_id=None)
    db_session.add_all([source, source_collection, article_collection, item])
    await db_session.flush()

    item.primary_source_id = source.id
    source_membership = SourceCollectionMembership(collection_id=source_collection.id, source_id=source.id)
    saved_membership = ArticleCollectionItem(collection_id=article_collection.id, content_item_id=item.id)
    source_item = SourceItem(
        source_id=source.id,
        content_item_id=item.id,
        external_id_raw="guid-1",
        external_id_norm="guid-1",
        source_url=item.canonical_url,
        source_url_norm=item.canonical_url,
    )
    db_session.add_all([source_membership, saved_membership, source_item])
    await db_session.flush()
    identity = ItemIdentity(
        content_item_id=item.id,
        source_item_id=source_item.id,
        identity_type="rss_guid",
        identity_value="guid-1",
        identity_hash="guid-hash-1",
        scope="source",
        source_id=source.id,
        confidence=Decimal("1"),
        is_strong=True,
    )
    story = Story(title="Durable downstream story", status="inbox", primary_language="en")
    db_session.add(story)
    await db_session.flush()
    evidence = StoryEvidenceSnapshot(
        story_id=story.id,
        content_item_id=item.id,
        evidence_key="url:durable",
        source_url=item.canonical_url,
        title=item.title,
        content_text="Durable evidence body",
        authors=[],
        published_at=NOW,
        content_sha256="a" * 64,
        snapshot_metadata={"is_primary": True},
    )
    db_session.add_all([identity, evidence])
    await db_session.commit()

    before = await _request(db_session, "GET", "/feed/summary")
    assert before.status_code == 200
    assert before.json() == {"article_count": 1}
    assert (await _request(db_session, "GET", "/articles")).json()["result_count"] == 1

    cleared = await _request(db_session, "POST", "/feed/clear")
    assert cleared.status_code == 200
    assert cleared.json() == {"cleared_count": 1}

    assert (await _request(db_session, "GET", "/feed/summary")).json() == {"article_count": 0}
    assert (await _request(db_session, "GET", "/articles")).json() == {
        "items": [],
        "next_cursor": None,
        "result_count": 0,
    }
    facets = (await _request(db_session, "GET", "/articles/facets")).json()
    assert facets == {"languages": [], "topics": [], "content_types": [], "sources": [], "coverage": []}
    assert (await _request(db_session, "GET", f"/articles/{item.id}")).status_code == 200

    assert await db_session.get(Source, source.id) is not None
    assert await db_session.get(SourceCollection, source_collection.id) is not None
    assert await db_session.get(ArticleCollection, article_collection.id) is not None
    assert await db_session.get(ArticleCollectionItem, (article_collection.id, item.id)) is not None
    assert await db_session.get(SourceCollectionMembership, (source_collection.id, source.id)) is not None
    assert await db_session.get(SourceItem, source_item.id) is not None
    assert await db_session.get(ItemIdentity, identity.id) is not None
    assert await db_session.get(StoryEvidenceSnapshot, evidence.id) is not None
    refreshed_item = await db_session.get(ContentItem, item.id)
    assert refreshed_item is not None
    await db_session.refresh(refreshed_item)
    assert refreshed_item.feed_cleared_at is not None

    assert (await _request(db_session, "POST", "/feed/clear")).json() == {"cleared_count": 0}


async def test_clear_preserves_identity_and_reingestion_does_not_resurface_old_item(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        source = Source(
            platform="rss",
            name="Replay Wire",
            feed_url="https://replay.example/feed",
            source_group="news",
            language_hint="en",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async def ingest(parsed: ParsedSourceItem) -> tuple:
        async with session_factory() as session, session.begin():
            source = await session.get(Source, source_id)
            assert source is not None
            repository = IngestionRepository(session)
            source_item = await repository.upsert_source_item(
                run_id=None,
                source_id=source_id,
                raw_payload_id=None,
                parsed_item=parsed,
            )
            identities = build_item_identities(source, parsed)
            item = await repository.upsert_content_item(source, source_item, parsed, identities)
            await repository.attach_identities(item.id, source_item.id, source_id, identities)
            return source_item.id, item.id

    first = await ingest(_parsed_item("stable-guid"))
    async with session_factory() as session:
        result = await clear_active_feed(session)
        await session.commit()
        assert result.cleared_count == 1

    replayed = await ingest(_parsed_item("stable-guid", title="Edited after clear"))
    assert replayed == first

    fresh = await ingest(
        replace(
            _parsed_item(
                "fresh-guid",
                title="Fresh report",
                body="This is a genuinely new report with a different set of independently useful facts. " * 2,
            ),
            source_url="https://news.example.test/reports/fresh?utm_source=feed",
            source_url_norm="https://news.example.test/reports/fresh",
            canonical_url_candidate="https://news.example.test/reports/fresh",
        )
    )
    assert fresh[1] != first[1]

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ContentItem)) == 2
        hidden = await session.get(ContentItem, first[1])
        visible = await session.get(ContentItem, fresh[1])
        assert hidden is not None and hidden.feed_cleared_at is not None
        assert visible is not None and visible.feed_cleared_at is None
        visible_page = await _request(session, "GET", "/articles")
        assert visible_page.status_code == 200
        assert visible_page.json()["result_count"] == 1
        assert visible_page.json()["items"][0]["id"] == str(fresh[1])


async def _request(session: AsyncSession, method: str, path: str):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path)
    finally:
        app.dependency_overrides.clear()


def _article(*, source_id) -> ContentItem:
    return ContentItem(
        item_type="article",
        canonical_url="https://clearable.example/article",
        title="Clearable article",
        summary="Summary",
        content_text="Durable body",
        content_html_sanitized="<p>Durable body</p>",
        language_code="en",
        script_code="Latn",
        direction="ltr",
        authors=[],
        tags=[],
        published_at=NOW,
        sort_at=NOW,
        date_source="source",
        date_parse_status="parsed",
        primary_source_id=source_id,
        status="new",
        score=10,
        metrics={"classification": {"category": "AI"}},
        content_type="article",
        content_type_confidence=Decimal("1"),
        classification_reasons=[],
        classification_metadata={"source_domain": "clearable.example"},
        rewrite_bucket="technical_article",
        freshness_bucket="fresh",
        source_tier="A",
        quality_status="needs_review",
        is_rewrite_ready=False,
        rewrite_ready_reason="missing evidence",
        rewrite_blockers=["missing_evidence"],
        score_breakdown={},
        ranking_metadata={},
        title_quality="meaningful",
        title_was_generated=False,
        content_intent=None,
    )


def _parsed_item(
    external_id: str,
    *,
    title: str = "Replay report",
    body: str | None = None,
) -> ParsedSourceItem:
    body = body or "This is a sufficiently detailed replay report body with independently useful facts. " * 2
    return ParsedSourceItem(
        external_id_raw=external_id,
        external_id_norm=external_id,
        source_url="https://news.example.test/reports/shared?utm_source=feed",
        source_url_norm="https://news.example.test/reports/shared",
        canonical_url_candidate="https://news.example.test/reports/shared",
        title=title,
        summary=body,
        content_html=None,
        content_text=body,
        author=None,
        categories=[],
        published_raw="2026-07-26T08:00:00+00:00",
        published_at=datetime(2026, 7, 26, 8, tzinfo=UTC),
        date_parse_status="parsed",
    )
