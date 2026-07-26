from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ContentItem, ItemIdentity, Source, SourceItem
from app.ingestion.repository import IngestionRepository, build_item_identities
from app.sources.base import ParsedSourceItem


def _parsed_item(
    *,
    external_id: str,
    title: str = "Shared report",
    body: str = "This is a sufficiently detailed report body with several independently useful facts. " * 2,
) -> ParsedSourceItem:
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


@pytest.mark.asyncio
async def test_concurrent_shared_identity_creates_one_content_item(
    session_factory: async_sessionmaker[AsyncSession],
):
    sources = [
        Source(
            platform="rss",
            name=f"Source {suffix}",
            feed_url=f"https://{suffix}.example.test/feed",
            source_group="news",
            language_hint="en",
        )
        for suffix in ("a", "b")
    ]
    async with session_factory() as session:
        session.add_all(sources)
        await session.flush()
        source_items = [
            SourceItem(source_id=source.id, external_id_norm=f"guid-{index}") for index, source in enumerate(sources)
        ]
        session.add_all(source_items)
        await session.commit()
        work = [
            (source.id, source_item.id, f"guid-{index}")
            for index, (source, source_item) in enumerate(zip(sources, source_items, strict=True))
        ]

    async def ingest(source_id, source_item_id, external_id):
        async with session_factory() as session, session.begin():
            source = await session.get(Source, source_id)
            source_item = await session.get(SourceItem, source_item_id)
            assert source is not None
            assert source_item is not None
            parsed = _parsed_item(external_id=external_id)
            repository = IngestionRepository(session)
            identities = build_item_identities(source, parsed)
            content_item = await repository.upsert_content_item(source, source_item, parsed, identities)
            await asyncio.sleep(0.05)
            await repository.attach_identities(
                content_item.id,
                source_item.id,
                source.id,
                identities,
            )
            return content_item.id

    content_ids = await asyncio.gather(*(ingest(*item) for item in work))

    assert content_ids[0] == content_ids[1]
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ContentItem)) == 1
        owners = set(await session.scalars(select(ItemIdentity.content_item_id)))
        assert owners == {content_ids[0]}


@pytest.mark.asyncio
async def test_repeated_edited_source_item_updates_without_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
):
    source = Source(
        platform="rss",
        name="Edited source",
        feed_url="https://edited.example.test/feed",
        source_group="news",
        language_hint="en",
    )
    async with session_factory() as session:
        session.add(source)
        await session.commit()
        source_id = source.id

    async def ingest(parsed: ParsedSourceItem) -> tuple:
        async with session_factory() as session, session.begin():
            persisted_source = await session.get(Source, source_id)
            assert persisted_source is not None
            repository = IngestionRepository(session)
            source_item = await repository.upsert_source_item(
                run_id=None,
                source_id=source_id,
                raw_payload_id=None,
                parsed_item=parsed,
            )
            identities = build_item_identities(persisted_source, parsed)
            content_item = await repository.upsert_content_item(
                persisted_source,
                source_item,
                parsed,
                identities,
            )
            await repository.attach_identities(
                content_item.id,
                source_item.id,
                source_id,
                identities,
            )
            return source_item.id, content_item.id

    first = await ingest(_parsed_item(external_id="stable-guid"))
    edited_body = "The corrected report now contains updated, verified facts for the same source item. " * 2
    second = await ingest(
        _parsed_item(
            external_id="stable-guid",
            title="Shared report corrected",
            body=edited_body,
        )
    )

    assert first == second
    async with session_factory() as session:
        content_item = await session.get(ContentItem, first[1])
        assert content_item is not None
        assert content_item.title == "Shared report corrected"
        assert content_item.content_text == edited_body
        assert await session.scalar(select(func.count()).select_from(SourceItem)) == 1
        assert await session.scalar(select(func.count()).select_from(ContentItem)) == 1
