"""Re-ingestion must not discard a primary image the previous parse resolved."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Update
from sqlalchemy.dialects import postgresql

from app.db.models import ContentItem, MediaAsset
from app.ingestion.repository import IngestionRepository
from app.sources.base import MediaCandidate, ParsedSourceItem


class _RecordingSession:
    """Minimal async session double that records the statements it is handed."""

    def __init__(self, live_assets: list[MediaAsset]) -> None:
        self._live_assets = live_assets
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> None:
        self.statements.append(statement)

    async def scalars(self, statement: Any) -> list[MediaAsset]:
        self.statements.append(statement)
        return list(self._live_assets)

    async def flush(self) -> None:
        return None


def _asset(url: str, source_field: str) -> MediaAsset:
    return MediaAsset(
        id=uuid4(),
        original_url=url,
        normalized_url=url,
        url_hash=url,
        kind="image",
        source_field=source_field,
        width=1200,
        height=630,
        fetch_status="remote_only",
        media_quality="good",
        is_primary_candidate=True,
    )


def _parsed_item(candidates: list[MediaCandidate]) -> ParsedSourceItem:
    return ParsedSourceItem(
        external_id_raw="guid-1",
        external_id_norm="guid-1",
        source_url="https://example.com/a",
        source_url_norm="https://example.com/a",
        canonical_url_candidate="https://example.com/a",
        title="AI News",
        summary="summary",
        content_html=None,
        content_text="body",
        author=None,
        categories=[],
        published_raw=None,
        published_at=None,
        date_parse_status="missing",
        media_candidates=candidates,
    )


def _content_item_updates(session: _RecordingSession) -> list[Any]:
    return [
        statement
        for statement in session.statements
        if isinstance(statement, Update) and statement.table.name == ContentItem.__tablename__
    ]


def _primary_image_values(statement: Update) -> dict[str, Any]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return dict(compiled.params)


@pytest.mark.asyncio
async def test_reparse_without_media_keeps_the_stored_primary_image() -> None:
    session = _RecordingSession([])
    repository = IngestionRepository(session)  # type: ignore[arg-type]

    await repository.attach_item_media(uuid4(), [], _parsed_item([]))

    assert _content_item_updates(session) == [], "an empty re-parse must not touch primary_image_id"


@pytest.mark.asyncio
async def test_reparse_with_only_non_primary_media_does_not_null_an_unrelated_primary() -> None:
    asset = _asset("https://e.test/tracker.gif", "inline_img")
    asset.kind = "video"
    session = _RecordingSession([asset])
    repository = IngestionRepository(session)  # type: ignore[arg-type]

    await repository.attach_item_media(uuid4(), [asset], _parsed_item([]))

    updates = _content_item_updates(session)
    assert len(updates) == 1
    values = _primary_image_values(updates[0])
    assert values["primary_image_id"] is None
    # The clear is scoped to the assets this parse re-planned, so a primary that
    # this parse never mentioned survives.
    assert "primary_image_id IN" in str(updates[0].compile(dialect=postgresql.dialect()))
    bound = [item for value in values.values() for item in (value if isinstance(value, list) else [value])]
    assert asset.id in bound


@pytest.mark.asyncio
async def test_reparse_with_a_primary_candidate_publishes_it() -> None:
    asset = _asset("https://e.test/lead.jpg", "media_content")
    session = _RecordingSession([asset])
    repository = IngestionRepository(session)  # type: ignore[arg-type]

    await repository.attach_item_media(
        uuid4(),
        [asset],
        _parsed_item([MediaCandidate(asset.original_url, asset.normalized_url, "image", "media_content")]),
    )

    updates = _content_item_updates(session)
    assert len(updates) == 1
    assert _primary_image_values(updates[0])["primary_image_id"] == asset.id
