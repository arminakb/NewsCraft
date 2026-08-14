from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.automations.telegram.handlers import dispatch_media, media_decision
from app.db.models import ContentItem, ItemMedia, MediaAsset
from app.jobs.errors import NeedsReviewJobError


@pytest.mark.asyncio
async def test_revision_media_lock_refreshes_a_stale_tombstoned_asset(
    session_factory: async_sessionmaker[AsyncSession],
):
    content_item = ContentItem(
        id=uuid4(),
        item_type="telegram_post",
        title="Stale media",
        content_text="Grounded",
        direction="rtl",
        sort_at=datetime.now(UTC),
        date_parse_status="parsed",
    )
    media = MediaAsset(
        id=uuid4(),
        original_url="https://example.com/stale.jpg",
        normalized_url="https://example.com/stale.jpg",
        url_hash="a" * 64,
        kind="image",
        source_field="content_image",
        storage_path="/data/media/stale.jpg",
        checksum_sha256="b" * 64,
        fetch_status="downloaded",
    )
    link = ItemMedia(
        content_item_id=content_item.id,
        media_asset_id=media.id,
        role="inline",
        sort_order=0,
        confidence=Decimal("1"),
        extracted_from="test",
    )
    async with session_factory() as seed_session:
        seed_session.add_all([content_item, media])
        await seed_session.flush()
        seed_session.add(link)
        await seed_session.commit()

    async with session_factory() as stale_session:
        stale_media = await stale_session.get(MediaAsset, media.id)
        assert stale_media is not None
        assert stale_media.fetch_status == "downloaded"

        async with session_factory() as retention_session:
            expired = await retention_session.get(MediaAsset, media.id)
            assert expired is not None
            expired.fetch_status = "expired"
            expired.storage_path = None
            await retention_session.commit()

        _, refreshed_media = await dispatch_media(
            stale_session,
            SimpleNamespace(content_item_id=content_item.id),
        )

        assert refreshed_media == (stale_media,)
        assert stale_media.fetch_status == "expired"
        assert stale_media.storage_path is None
        with pytest.raises(NeedsReviewJobError) as caught:
            media_decision(SimpleNamespace(media_policy="preserve"), refreshed_media)
        assert caught.value.code == "telegram_media_expired"
