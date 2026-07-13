from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ContentItem, ItemMedia, MediaAsset
from app.generation.platform_media import trusted_story_media
from app.ingestion.repository import IngestionRepository
from app.normalization.urls import hash_value
from app.sources.base import MediaCandidate, ParsedSourceItem


@pytest.mark.asyncio
async def test_ingestion_does_not_attach_a_stale_expired_media_asset(
    session_factory: async_sessionmaker[AsyncSession],
):
    now = datetime.now(UTC)
    content_item = ContentItem(
        id=uuid4(),
        item_type="article",
        title="Expired media",
        content_text="Grounded",
        sort_at=now,
        date_parse_status="parsed",
    )
    normalized_url = "https://example.com/expired.jpg"
    asset = MediaAsset(
        id=uuid4(),
        original_url=normalized_url,
        normalized_url=normalized_url,
        url_hash=hash_value(normalized_url),
        kind="image",
        source_field="content_image",
        storage_path="/data/media/expired.jpg",
        checksum_sha256="a" * 64,
        fetch_status="downloaded",
    )
    async with session_factory() as seed_session:
        seed_session.add_all([content_item, asset])
        await seed_session.commit()

    parsed = ParsedSourceItem(
        external_id_raw="expired-media",
        external_id_norm="expired-media",
        source_url="https://example.com/story",
        source_url_norm="https://example.com/story",
        canonical_url_candidate="https://example.com/story",
        title="Expired media",
        summary="Grounded",
        content_html=None,
        content_text="Grounded",
        author=None,
        categories=[],
        published_raw=None,
        published_at=now,
        date_parse_status="parsed",
        media_candidates=[
            MediaCandidate(
                original_url=normalized_url,
                normalized_url=normalized_url,
                kind="image",
                source_field="content_image",
                storage_path="/data/media/expired.jpg",
                checksum_sha256="a" * 64,
                fetch_status="downloaded",
            )
        ],
    )

    async with session_factory() as stale_session:
        stale_asset = await stale_session.scalar(select(MediaAsset).where(MediaAsset.id == asset.id))
        assert stale_asset is not None
        assert stale_asset.fetch_status == "downloaded"

        async with session_factory() as retention_session:
            expired = await retention_session.get(MediaAsset, asset.id)
            assert expired is not None
            expired.fetch_status = "expired"
            expired.storage_path = None
            await retention_session.commit()

        await IngestionRepository(stale_session).attach_item_media(
            content_item.id,
            [stale_asset],
            parsed,
        )
        await stale_session.commit()

    async with session_factory() as check_session:
        assert await check_session.scalar(select(ItemMedia).where(ItemMedia.media_asset_id == asset.id)) is None
        refreshed_content = await check_session.get(ContentItem, content_item.id)
        assert refreshed_content is not None
        assert refreshed_content.primary_image_id is None


@pytest.mark.asyncio
async def test_reingestion_creates_a_live_identity_instead_of_reusing_media_tombstone(
    session_factory: async_sessionmaker[AsyncSession],
):
    now = datetime.now(UTC)
    normalized_url = "https://example.com/recaptured.jpg"
    content_item = ContentItem(
        id=uuid4(),
        item_type="telegram_post",
        title="Recaptured media",
        content_text="Grounded",
        sort_at=now,
        date_parse_status="parsed",
    )
    tombstone = MediaAsset(
        id=uuid4(),
        original_url=normalized_url,
        normalized_url=normalized_url,
        url_hash=hash_value(normalized_url),
        kind="image",
        source_field="telegram_capture",
        storage_path=None,
        checksum_sha256="a" * 64,
        byte_length=10,
        fetch_status="expired",
        raw_metadata={"retention": {"state": "expired"}},
    )
    async with session_factory() as seed_session:
        seed_session.add_all([content_item, tombstone])
        await seed_session.commit()

    captured_path = "/data/media/bb/recaptured.jpg"
    parsed = ParsedSourceItem(
        external_id_raw="recaptured-media",
        external_id_norm="recaptured-media",
        source_url="https://example.com/story",
        source_url_norm="https://example.com/story",
        canonical_url_candidate="https://example.com/story",
        title="Recaptured media",
        summary="Grounded",
        content_html=None,
        content_text="Grounded",
        author=None,
        categories=[],
        published_raw=None,
        published_at=now,
        date_parse_status="parsed",
        media_candidates=[
            MediaCandidate(
                original_url=normalized_url,
                normalized_url=normalized_url,
                kind="image",
                source_field="telegram_capture",
                storage_path=captured_path,
                checksum_sha256="b" * 64,
                byte_length=99,
                fetch_status="downloaded",
            )
        ],
    )

    async with session_factory() as ingestion_session:
        repository = IngestionRepository(ingestion_session)
        assets = await repository.upsert_media_assets(parsed)
        await repository.attach_item_media(content_item.id, assets, parsed)
        await ingestion_session.commit()
        assert len(assets) == 1
        live_id = assets[0].id

    async with session_factory() as check_session:
        old = await check_session.get(MediaAsset, tombstone.id)
        live = await check_session.get(MediaAsset, live_id)
        assert old is not None
        assert old.fetch_status == "expired"
        assert old.storage_path is None
        assert live is not None
        assert live.id != old.id
        assert live.fetch_status == "downloaded"
        assert live.storage_path == captured_path
        assert live.checksum_sha256 == "b" * 64
        link = await check_session.scalar(
            select(ItemMedia).where(
                ItemMedia.content_item_id == content_item.id,
                ItemMedia.media_asset_id == live.id,
            )
        )
        assert link is not None


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
    db_session.add_all([content_item, asset])
    await db_session.flush()
    db_session.add(link)
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
            generation_task = asyncio.create_task(trusted_story_media(generating, evidence, lock_rows=True))

            deadline = asyncio.get_running_loop().time() + 2
            while True:
                wait_type = await observer.scalar(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
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


@pytest.mark.asyncio
async def test_ingestion_takes_reference_table_fence_before_media_row_lock(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
):
    now = datetime.now(UTC)
    content_item = ContentItem(
        id=uuid4(),
        item_type="article",
        title="Retention lock order",
        content_text="Grounded",
        sort_at=now,
        date_parse_status="parsed",
    )
    normalized_url = "https://example.com/retention-lock.jpg"
    asset = MediaAsset(
        id=uuid4(),
        original_url=normalized_url,
        normalized_url=normalized_url,
        url_hash=hash_value(normalized_url),
        kind="image",
        source_field="content_image",
        fetch_status="remote_only",
    )
    db_session.add_all([content_item, asset])
    await db_session.commit()
    parsed = ParsedSourceItem(
        external_id_raw="retention-lock",
        external_id_norm="retention-lock",
        source_url="https://example.com/story",
        source_url_norm="https://example.com/story",
        canonical_url_candidate="https://example.com/story",
        title="Retention lock order",
        summary="Grounded",
        content_html=None,
        content_text="Grounded",
        author=None,
        categories=[],
        published_raw=None,
        published_at=now,
        date_parse_status="parsed",
        media_candidates=[
            MediaCandidate(
                original_url=normalized_url,
                normalized_url=normalized_url,
                kind="image",
                source_field="content_image",
                alt_text="Fresh metadata",
            )
        ],
    )

    retention_task = None
    async with (
        session_factory() as ingesting,
        session_factory() as retaining,
        session_factory() as observer,
    ):
        try:
            await ingesting.execute(text("SET LOCAL lock_timeout = '750ms'"))
            repository = IngestionRepository(ingesting)
            media_assets = await repository.upsert_media_assets(parsed)

            retention_pid = await retaining.scalar(text("SELECT pg_backend_pid()"))

            async def lock_for_retention():
                await retaining.execute(text("LOCK TABLE content_items, item_media, media_assets IN SHARE MODE"))
                return await retaining.scalar(select(MediaAsset).where(MediaAsset.id == asset.id).with_for_update())

            retention_task = asyncio.create_task(lock_for_retention())
            deadline = asyncio.get_running_loop().time() + 2
            while True:
                wait_type = await observer.scalar(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": retention_pid},
                )
                if wait_type == "Lock":
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("retention did not wait on the ingestion fence")
                await asyncio.sleep(0.01)

            await repository.attach_item_media(content_item.id, media_assets, parsed)
            await ingesting.commit()
            locked = await asyncio.wait_for(retention_task, timeout=2)
            assert locked is not None
        finally:
            if retention_task is not None and not retention_task.done():
                retention_task.cancel()
            if retention_task is not None:
                await asyncio.gather(retention_task, return_exceptions=True)
            await ingesting.rollback()
            await retaining.rollback()
