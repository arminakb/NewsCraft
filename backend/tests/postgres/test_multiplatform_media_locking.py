from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ContentItem, ItemMedia, MediaAsset
from app.generation.platform_media import trusted_story_media
from app.ingestion.repository import IngestionRepository
from app.normalization.urls import hash_value
from app.sources.base import MediaCandidate, ParsedSourceItem


@pytest.mark.asyncio
async def test_generation_media_revalidation_does_not_invert_ingestion_asset_link_order(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
):
    now = datetime.now(UTC)
    content_item = ContentItem(
        id=uuid4(),
        item_type="article",
        title="Shared media",
        content_text="Grounded",
        sort_at=now,
        date_parse_status="parsed",
    )
    normalized_url = "https://example.com/shared.jpg"
    asset = MediaAsset(
        id=uuid4(),
        original_url=normalized_url,
        normalized_url=normalized_url,
        url_hash=hash_value(normalized_url),
        kind="image",
        mime_type="image/jpeg",
        width=1200,
        height=800,
        byte_length=1234,
        alt_text="Shared",
        title="Shared",
        source_field="content_image",
        checksum_sha256="a" * 64,
        storage_path="/data/media/shared.jpg",
        fetch_status="downloaded",
        media_quality="high",
        media_confidence=Decimal("1"),
        is_primary_candidate=True,
        is_primary=True,
        media_source_type="stored",
        asset_role="inline_image",
        raw_metadata={},
    )
    link = ItemMedia(
        content_item_id=content_item.id,
        media_asset_id=asset.id,
        role="primary_image",
        sort_order=0,
        confidence=Decimal("1"),
        extracted_from="content_image",
    )
    db_session.add_all([content_item, asset, link])
    await db_session.commit()

    candidate = MediaCandidate(
        original_url=normalized_url,
        normalized_url=normalized_url,
        kind="image",
        source_field="content_image",
        mime_type="image/jpeg",
        width=1200,
        height=800,
        alt_text="Updated shared media",
        confidence=1.0,
        storage_path="/data/media/shared.jpg",
        checksum_sha256="a" * 64,
        byte_length=1234,
        fetch_status="downloaded",
    )
    parsed = ParsedSourceItem(
        external_id_raw="shared-media",
        external_id_norm="shared-media",
        source_url="https://example.com/story",
        source_url_norm="https://example.com/story",
        canonical_url_candidate="https://example.com/story",
        title="Shared media",
        summary="Grounded",
        content_html=None,
        content_text="Grounded",
        author=None,
        categories=[],
        published_raw=None,
        published_at=now,
        date_parse_status="parsed",
        media_candidates=[candidate],
    )
    evidence = {uuid4(): SimpleNamespace(content_item_id=content_item.id)}

    generation_task = None
    async with (
        session_factory() as ingesting,
        session_factory() as generating,
        session_factory() as observer,
    ):
        try:
            await ingesting.execute(text("SET LOCAL lock_timeout = '750ms'"))
            repository = IngestionRepository(ingesting)
            media_assets = await repository.upsert_media_assets(parsed)
            assert [item.id for item in media_assets] == [asset.id]

            generation_pid = await generating.scalar(text("SELECT pg_backend_pid()"))
            generation_task = asyncio.create_task(
                trusted_story_media(generating, evidence, lock_rows=True)
            )

            deadline = asyncio.get_running_loop().time() + 2
            while True:
                wait_type = await observer.scalar(
                    text(
                        "SELECT wait_event_type FROM pg_stat_activity "
                        "WHERE pid = :pid"
                    ),
                    {"pid": generation_pid},
                )
                if wait_type == "Lock":
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("generation did not wait on the ingestion asset lock")
                await asyncio.sleep(0.01)

            # Real ingestion now upserts the shared ItemMedia link. This must
            # not wait on generation while generation waits on MediaAsset.
            await repository.attach_item_media(content_item.id, media_assets, parsed)
            await ingesting.commit()

            authorized, projection = await asyncio.wait_for(generation_task, timeout=2)
            assert set(authorized) == {asset.id}
            assert projection[0]["id"] == str(asset.id)
            await generating.rollback()
        finally:
            if generation_task is not None and not generation_task.done():
                generation_task.cancel()
            if generation_task is not None:
                await asyncio.gather(generation_task, return_exceptions=True)
            await ingesting.rollback()
            await generating.rollback()
