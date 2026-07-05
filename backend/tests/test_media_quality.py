from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.api.schemas import MediaAssetOut
from app.db.models import MediaAsset
from app.ingestion.repository import _apply_media_candidate, _media_asset_values, plan_item_media_rows
from app.sources.base import MediaCandidate, ParsedSourceItem


def test_media_asset_values_marks_good_image_as_primary_candidate():
    candidate = MediaCandidate(
        "https://cdn.example.com/story.jpg",
        "https://cdn.example.com/story.jpg",
        "image",
        "media_content",
        mime_type="image/jpeg",
        width=1200,
        height=630,
        confidence=0.95,
    )

    values = _media_asset_values(candidate, "hash")

    assert values.get("media_quality") == "good"
    assert values.get("media_confidence") == Decimal("0.95")
    assert values.get("media_source_type") == "external"
    assert values.get("asset_role") == "inline_image"
    assert values.get("is_primary_candidate") is True
    assert values.get("is_primary") is False


def test_media_asset_values_marks_medium_tracking_pixel_as_weak():
    candidate = MediaCandidate(
        "https://medium.com/_/stat?event=post.clientViewed",
        "https://medium.com/_/stat?event=post.clientViewed",
        "image",
        "inline_img",
        width=1,
        height=1,
        confidence=1.0,
    )

    values = _media_asset_values(candidate, "hash")

    assert values.get("media_quality") == "tracking"
    assert values.get("media_confidence") == Decimal("0.05")
    assert values.get("asset_role") == "tracking_pixel"
    assert values.get("is_primary_candidate") is False


def test_media_asset_values_marks_telegram_cdn_as_temporary_external():
    candidate = MediaCandidate(
        "https://cdn4.cdn-telegram.org/file/photo.jpg?token=secret",
        "https://cdn4.cdn-telegram.org/file/photo.jpg?token=secret",
        "image",
        "media_content",
        width=900,
        height=600,
        confidence=0.9,
    )

    values = _media_asset_values(candidate, "hash")

    assert values.get("media_source_type") == "temporary_external"
    assert values.get("fetch_status") == "remote_only"
    assert values.get("media_quality") == "good"


def test_downloaded_telegram_media_stays_stored_on_reingest():
    asset = _asset(
        "https://cdn4.cdn-telegram.org/file/photo.jpg?token=old",
        quality="good",
        role="inline_image",
    )
    asset.fetch_status = "downloaded"
    asset.storage_path = "/data/media/photo.jpg"
    asset.media_source_type = "stored"
    candidate = MediaCandidate(
        "https://cdn4.cdn-telegram.org/file/photo.jpg?token=new",
        "https://cdn4.cdn-telegram.org/file/photo.jpg?token=new",
        "image",
        "media_content",
        width=900,
        height=600,
        confidence=0.9,
    )

    _apply_media_candidate(asset, candidate, "hash")

    assert asset.fetch_status == "downloaded"
    assert asset.storage_path == "/data/media/photo.jpg"
    assert asset.media_source_type == "stored"


def test_plan_item_media_rows_excludes_tracking_pixel_from_primary():
    content_item_id = uuid4()
    tracking = _asset(
        "https://medium.com/_/stat?event=post.clientViewed",
        quality="tracking",
        role="tracking_pixel",
        width=1,
        height=1,
        primary_candidate=False,
    )
    image = _asset("https://cdn.example.com/story.jpg", quality="good", role="inline_image")
    parsed_item = _parsed_item(
        [
            MediaCandidate(tracking.original_url, tracking.normalized_url, "image", "inline_img", width=1, height=1),
            MediaCandidate(image.original_url, image.normalized_url, "image", "media_content", width=1200, height=630),
        ]
    )

    rows = plan_item_media_rows(content_item_id, [tracking, image], parsed_item)

    assert [row["role"] for row in rows] == ["tracking_pixel", "primary_image"]


def test_plan_item_media_rows_allows_youtube_thumbnail_as_primary():
    content_item_id = uuid4()
    thumbnail = _asset(
        "https://i.ytimg.com/vi/abc123/hqdefault.jpg",
        quality="good",
        role="thumbnail",
        width=480,
        height=360,
    )
    parsed_item = _parsed_item(
        [
            MediaCandidate(
                thumbnail.original_url,
                thumbnail.normalized_url,
                "image",
                "media_thumbnail",
                width=480,
                height=360,
            )
        ]
    )

    rows = plan_item_media_rows(content_item_id, [thumbnail], parsed_item)

    assert rows[0]["role"] == "primary_image"


def test_plan_item_media_rows_has_no_primary_for_only_weak_media():
    content_item_id = uuid4()
    tracking = _asset(
        "https://medium.com/_/stat?event=post.clientViewed",
        quality="tracking",
        role="tracking_pixel",
        width=1,
        height=1,
        primary_candidate=False,
    )
    low_confidence = _asset(
        "https://cdn.example.com/unknown.bin",
        kind="document",
        quality="low",
        role="unknown",
        primary_candidate=False,
    )
    parsed_item = _parsed_item(
        [
            MediaCandidate(tracking.original_url, tracking.normalized_url, "image", "inline_img", width=1, height=1),
            MediaCandidate(
                low_confidence.original_url,
                low_confidence.normalized_url,
                "document",
                "enclosure",
                confidence=0.2,
            ),
        ]
    )

    rows = plan_item_media_rows(content_item_id, [tracking, low_confidence], parsed_item)

    assert "primary_image" not in {row["role"] for row in rows}


def test_media_schema_exposes_quality_metadata():
    media = SimpleNamespace(
        id=uuid4(),
        normalized_url="https://cdn.example.com/story.jpg",
        kind="image",
        mime_type="image/jpeg",
        width=1200,
        height=630,
        storage_path=None,
        fetch_status="remote_only",
        media_quality="good",
        media_confidence=Decimal("0.95"),
        is_primary_candidate=True,
        is_primary=True,
        media_source_type="external",
        asset_role="inline_image",
    )

    payload = MediaAssetOut.model_validate(media).model_dump()

    assert payload.get("media_quality") == "good"
    assert payload.get("media_confidence") == Decimal("0.95")
    assert payload.get("is_primary") is True
    assert payload.get("asset_role") == "inline_image"


def _asset(
    url: str,
    *,
    kind: str = "image",
    quality: str,
    role: str,
    width: int | None = 1200,
    height: int | None = 630,
    primary_candidate: bool = True,
) -> MediaAsset:
    return MediaAsset(
        id=uuid4(),
        original_url=url,
        normalized_url=url,
        url_hash=url,
        kind=kind,
        source_field="media_content",
        width=width,
        height=height,
        fetch_status="remote_only",
        media_quality=quality,
        media_confidence=Decimal("0.9") if primary_candidate else Decimal("0.05"),
        is_primary_candidate=primary_candidate,
        is_primary=False,
        media_source_type="external",
        asset_role=role,
    )


def _parsed_item(media_candidates: list[MediaCandidate]) -> ParsedSourceItem:
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
        published_raw="2026-07-03",
        published_at=datetime(2026, 7, 3, tzinfo=UTC),
        date_parse_status="parsed",
        media_candidates=media_candidates,
    )
