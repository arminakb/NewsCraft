from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ContentItem, ItemIdentity, MediaAsset, Source
from app.ingestion.repository import IngestionRepository, build_item_identities
from app.sources.base import MediaCandidate, ParsedSourceItem

BODY = "This is a sufficiently detailed report body with several independently useful facts. " * 2


def _parsed_item(
    *,
    external_id: str = "guid-1",
    media: bool = False,
    url: str = "https://news.example.test/reports/shared",
    body: str = BODY,
) -> ParsedSourceItem:
    return ParsedSourceItem(
        external_id_raw=external_id,
        external_id_norm=external_id,
        source_url=url,
        source_url_norm=url,
        canonical_url_candidate=url,
        title="Shared report",
        summary=body,
        content_html=None,
        content_text=body,
        author=None,
        categories=[],
        published_raw="2026-08-13T08:00:00+00:00",
        published_at=datetime(2026, 8, 13, 8, tzinfo=UTC),
        date_parse_status="parsed",
        media_candidates=(
            [
                MediaCandidate(
                    original_url="https://cdn.example.test/hero.jpg?utm=1",
                    normalized_url="https://cdn.example.test/hero.jpg",
                    kind="image",
                    source_field="content_image",
                    mime_type="image/jpeg",
                    width=800,
                    height=600,
                )
            ]
            if media
            else []
        ),
    )


async def _create_source(session_factory: async_sessionmaker[AsyncSession], name: str) -> Source:
    source = Source(
        platform="rss",
        name=name,
        feed_url=f"https://{name}.example.test/feed",
        source_group="news",
        language_hint="en",
    )
    async with session_factory() as session:
        session.add(source)
        await session.commit()
    return source


async def _ingest(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    parsed: ParsedSourceItem,
) -> ContentItem:
    async with session_factory() as session, session.begin():
        persisted_source = await session.get(Source, source.id)
        assert persisted_source is not None
        repository = IngestionRepository(session)
        source_item = await repository.upsert_source_item(
            run_id=None,
            source_id=persisted_source.id,
            raw_payload_id=None,
            parsed_item=parsed,
        )
        identities = build_item_identities(persisted_source, parsed)
        content_item = await repository.upsert_content_item(persisted_source, source_item, parsed, identities)
        await repository.attach_identities(content_item.id, source_item.id, persisted_source.id, identities)
        return content_item


@pytest.mark.asyncio
async def test_multi_match_binds_the_strongest_item_and_records_the_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
):
    """A parsed item matching two content items must bind deterministically and merge."""
    url_source = await _create_source(session_factory, "urlowner")
    body_source = await _create_source(session_factory, "bodyowner")
    other_body = "A completely separate narrative with its own independently verifiable details. " * 2

    url_item = await _ingest(
        session_factory,
        url_source,
        _parsed_item(external_id="url-1", url="https://news.example.test/reports/one"),
    )
    body_item = await _ingest(
        session_factory,
        body_source,
        _parsed_item(external_id="body-1", url="https://news.example.test/reports/two", body=other_body),
    )
    assert url_item.id != body_item.id

    # Matches url_item by canonical/normalized URL (confidence 1.0) and
    # body_item by content hash (confidence 0.92).
    merged = await _ingest(
        session_factory,
        url_source,
        _parsed_item(external_id="url-2", url="https://news.example.test/reports/one", body=other_body),
    )

    assert merged.id == url_item.id
    async with session_factory() as session:
        loser = await session.get(ContentItem, body_item.id)
        winner = await session.get(ContentItem, url_item.id)
        assert loser is not None and winner is not None
        assert loser.duplicate_of_id == url_item.id
        assert winner.duplicate_of_id is None


@pytest.mark.asyncio
async def test_repeated_ingest_keeps_one_weak_identity_row(
    session_factory: async_sessionmaker[AsyncSession],
):
    source = await _create_source(session_factory, "weakidentity")

    async def ingest() -> None:
        async with session_factory() as session, session.begin():
            persisted_source = await session.get(Source, source.id)
            assert persisted_source is not None
            repository = IngestionRepository(session)
            parsed = _parsed_item()
            source_item = await repository.upsert_source_item(
                run_id=None,
                source_id=persisted_source.id,
                raw_payload_id=None,
                parsed_item=parsed,
            )
            identities = build_item_identities(persisted_source, parsed)
            content_item = await repository.upsert_content_item(persisted_source, source_item, parsed, identities)
            await repository.attach_identities(
                content_item.id,
                source_item.id,
                persisted_source.id,
                identities,
            )

    await ingest()
    await ingest()
    await ingest()

    async with session_factory() as session:
        weak_rows = await session.scalar(
            select(func.count()).select_from(ItemIdentity).where(ItemIdentity.is_strong.is_(False))
        )
        assert weak_rows == 1


@pytest.mark.asyncio
async def test_concurrent_media_upsert_creates_one_asset(
    session_factory: async_sessionmaker[AsyncSession],
):
    for suffix in ("a", "b"):
        await _create_source(session_factory, f"media{suffix}")

    async def ingest_media() -> list:
        async with session_factory() as session, session.begin():
            repository = IngestionRepository(session)
            assets = await repository.upsert_media_assets(_parsed_item(media=True))
            await asyncio.sleep(0.05)
            return [asset.id for asset in assets]

    results = await asyncio.gather(ingest_media(), ingest_media())

    assert results[0] == results[1]
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MediaAsset)) == 1


@pytest.mark.asyncio
async def test_repeated_media_upsert_reuses_the_live_asset(
    session_factory: async_sessionmaker[AsyncSession],
):
    await _create_source(session_factory, "mediarepeat")

    async def ingest_media() -> list:
        async with session_factory() as session, session.begin():
            repository = IngestionRepository(session)
            assets = await repository.upsert_media_assets(_parsed_item(media=True))
            return [asset.id for asset in assets]

    first = await ingest_media()
    second = await ingest_media()

    assert first == second
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MediaAsset)) == 1
