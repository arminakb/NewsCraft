from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models import MediaAsset, Source
from app.ingestion.repository import (
    IngestionRepository,
    _apply_media_candidate,
    _identity_insert_statement,
    _media_asset_values,
    build_item_identities,
    dedupe_media_candidates,
    plan_item_media_rows,
)
from app.sources.base import MediaCandidate, ParsedSourceItem
from app.sources.rss import _extract_media_candidates


def test_build_item_identities_marks_strong_and_weak_scopes():
    source = Source(id=uuid4(), platform="rss", name="Example", source_group="ai", language_hint="en")
    parsed_item = ParsedSourceItem(
        external_id_raw="guid-1",
        external_id_norm="guid-1",
        source_url="https://example.com/a?utm_source=x",
        source_url_norm="https://example.com/a",
        canonical_url_candidate="https://example.com/a",
        title="AI News",
        summary="summary",
        content_html=None,
        content_text="This is a long enough body for a strong content hash identity. " * 2,
        author=None,
        categories=[],
        published_raw="2026-07-03",
        published_at=datetime(2026, 7, 3, tzinfo=UTC),
        date_parse_status="parsed",
    )

    identities = build_item_identities(source, parsed_item)
    by_type = {identity["identity_type"]: identity for identity in identities}

    assert by_type["canonical_url"]["scope"] == "global"
    assert by_type["canonical_url"]["is_strong"] is True
    assert by_type["normalized_url"]["scope"] == "global"
    assert by_type["rss_guid"]["scope"] == "source"
    assert by_type["rss_guid"]["source_id"] == source.id
    assert by_type["content_hash"]["scope"] == "global"
    assert by_type["title_date_fingerprint"]["is_strong"] is False


def test_build_item_identities_uses_telegram_post_identity():
    source = Source(
        id=uuid4(),
        platform="telegram_public",
        name="Telegram",
        telegram_username="iran_jahan_darlahze",
        source_group="farsi_news",
        language_hint="fa",
    )
    parsed_item = ParsedSourceItem(
        external_id_raw="iran_jahan_darlahze/41318",
        external_id_norm="iran_jahan_darlahze/41318",
        source_url="https://t.me/iran_jahan_darlahze/41318",
        source_url_norm="https://t.me/iran_jahan_darlahze/41318",
        canonical_url_candidate="https://t.me/iran_jahan_darlahze/41318",
        title="خبر فوری",
        summary="خبر فوری",
        content_html=None,
        content_text="خبر فوری درباره اقتصاد ایران",
        author=None,
        categories=[],
        published_raw="2026-07-03T18:30:28+00:00",
        published_at=datetime(2026, 7, 3, 18, 30, tzinfo=UTC),
        date_parse_status="parsed",
    )

    identities = build_item_identities(source, parsed_item)

    assert any(
        identity["identity_type"] == "telegram_post"
        and identity["identity_value"] == "iran_jahan_darlahze/41318"
        and identity["scope"] == "global"
        and identity["is_strong"]
        for identity in identities
    )


def test_plan_item_media_rows_marks_first_image_primary():
    content_item_id = uuid4()
    image_1_id = uuid4()
    image_2_id = uuid4()
    media_assets = [
        MediaAsset(
            id=image_1_id,
            original_url="https://e.test/1.jpg",
            normalized_url="https://e.test/1.jpg",
            url_hash="1",
            kind="image",
            source_field="media_content",
            fetch_status="remote_only",
        ),
        MediaAsset(
            id=image_2_id,
            original_url="https://e.test/2.jpg",
            normalized_url="https://e.test/2.jpg",
            url_hash="2",
            kind="image",
            source_field="inline_img",
            fetch_status="remote_only",
        ),
    ]
    parsed_item = ParsedSourceItem(
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
        media_candidates=[
            MediaCandidate("https://e.test/1.jpg", "https://e.test/1.jpg", "image", "media_content"),
            MediaCandidate("https://e.test/2.jpg", "https://e.test/2.jpg", "image", "inline_img"),
        ],
    )

    rows = plan_item_media_rows(content_item_id, media_assets, parsed_item)

    assert rows[0]["role"] == "primary_image"
    assert rows[0]["sort_order"] == 0
    assert rows[1]["role"] == "inline_image"
    assert rows[1]["sort_order"] == 1


def test_identity_upserts_match_partial_unique_indexes():
    content_item_id = uuid4()
    source_item_id = uuid4()
    source_id = uuid4()
    values = {
        "content_item_id": content_item_id,
        "source_item_id": source_item_id,
        "identity_type": "canonical_url",
        "identity_value": "https://example.com/a",
        "identity_hash": "hash",
        "scope": "global",
        "source_id": source_id,
        "confidence": Decimal("1.0"),
        "is_strong": True,
    }

    global_sql = str(_identity_insert_statement(values).compile(dialect=postgresql.dialect()))
    source_sql = str(_identity_insert_statement({**values, "scope": "source"}).compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (identity_type, identity_hash) WHERE scope = 'global' AND is_strong" in global_sql
    assert "ON CONFLICT (source_id, identity_type, identity_hash) WHERE scope = 'source' AND is_strong" in source_sql


def test_weak_source_identity_upsert_targets_the_weak_unique_index():
    values = {
        "content_item_id": uuid4(),
        "source_item_id": uuid4(),
        "identity_type": "title_date_fingerprint",
        "identity_value": "headline|2026-08-13",
        "identity_hash": "hash",
        "scope": "source",
        "source_id": uuid4(),
        "confidence": Decimal("0.55"),
        "is_strong": False,
    }

    weak_sql = str(_identity_insert_statement(values).compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (source_id, identity_type, identity_hash) WHERE scope = 'source' AND NOT is_strong" in weak_sql
    assert "DO UPDATE" in weak_sql


def test_identity_upsert_rejects_scopes_without_a_unique_index():
    values = {
        "content_item_id": uuid4(),
        "source_item_id": uuid4(),
        "identity_type": "title_date_fingerprint",
        "identity_value": "headline|2026-08-13",
        "identity_hash": "hash",
        "scope": "global",
        "source_id": None,
        "confidence": Decimal("0.55"),
        "is_strong": False,
    }

    with pytest.raises(ValueError, match="Unsupported identity scope"):
        _identity_insert_statement(values)


def test_repository_exposes_plan_methods():
    expected_methods = {
        "create_run",
        "finish_run",
        "get_active_sources",
        "save_raw_payload",
        "upsert_source_item",
        "find_content_item_by_identities",
        "upsert_content_item",
        "attach_identities",
        "upsert_media_assets",
        "attach_item_media",
    }

    assert expected_methods.issubset(set(dir(IngestionRepository)))


def test_stored_media_candidate_values_are_copied_to_asset():
    candidate = MediaCandidate(
        "telegram-media:one",
        "telegram-media:one",
        "photo",
        "telegram_capture",
        mime_type="image/jpeg",
        storage_path="/media/ab/checksum.jpg",
        checksum_sha256="a" * 64,
        byte_length=123,
        fetch_status="downloaded",
    )

    values = _media_asset_values(candidate, "url-hash")

    assert values["storage_path"] == "/media/ab/checksum.jpg"
    assert values["checksum_sha256"] == "a" * 64
    assert values["byte_length"] == 123
    assert values["fetch_status"] == "downloaded"


def test_remote_reingest_does_not_erase_downloaded_media_metadata():
    asset = MediaAsset(
        id=uuid4(),
        original_url="https://example.test/photo.jpg",
        normalized_url="https://example.test/photo.jpg",
        url_hash="old-hash",
        kind="photo",
        source_field="telegram_capture",
        storage_path="/media/ab/checksum.jpg",
        checksum_sha256="b" * 64,
        byte_length=456,
        fetch_status="downloaded",
    )
    remote = MediaCandidate(
        "https://example.test/photo.jpg",
        "https://example.test/photo.jpg",
        "photo",
        "media_content",
    )

    _apply_media_candidate(asset, remote, "new-hash")

    assert asset.storage_path == "/media/ab/checksum.jpg"
    assert asset.checksum_sha256 == "b" * 64
    assert asset.byte_length == 456
    assert asset.fetch_status == "downloaded"
    assert asset.source_field == "telegram_capture"
    assert asset.media_source_type == "stored"


def test_duplicate_urls_resolve_to_the_strongest_candidate():
    lead = MediaCandidate(
        "https://e.test/lead.jpg",
        "https://e.test/lead.jpg",
        "image",
        "media_content",
        width=1200,
        height=630,
        confidence=1.0,
    )
    inline = MediaCandidate(
        "https://e.test/lead.jpg",
        "https://e.test/lead.jpg",
        "image",
        "inline_img",
        confidence=0.7,
    )

    deduped = dedupe_media_candidates([lead, inline])

    assert len(deduped) == 1
    assert deduped[0].source_field == "media_content"
    assert deduped[0].width == 1200


def test_plan_item_media_rows_uses_the_strongest_duplicate_candidate():
    content_item_id = uuid4()
    asset = MediaAsset(
        id=uuid4(),
        original_url="https://e.test/lead.jpg",
        normalized_url="https://e.test/lead.jpg",
        url_hash="lead",
        kind="image",
        source_field="media_content",
        width=1200,
        height=630,
        fetch_status="remote_only",
        media_quality="good",
        is_primary_candidate=True,
    )
    parsed_item = ParsedSourceItem(
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
        media_candidates=[
            MediaCandidate(
                "https://e.test/lead.jpg",
                "https://e.test/lead.jpg",
                "image",
                "media_content",
                width=1200,
                height=630,
                confidence=1.0,
            ),
            MediaCandidate(
                "https://e.test/lead.jpg",
                "https://e.test/lead.jpg",
                "image",
                "inline_img",
                confidence=0.7,
            ),
        ],
    )

    rows = plan_item_media_rows(content_item_id, [asset], parsed_item)

    assert len(rows) == 1
    assert rows[0]["extracted_from"] == "media_content"


def test_rss_media_extraction_emits_one_candidate_per_url():
    entry = {
        "media_content": [{"url": "https://e.test/lead.jpg", "medium": "image", "width": "1200", "height": "630"}],
        "links": [],
        "enclosures": [],
    }
    html = '<p>text</p><img src="https://e.test/lead.jpg" alt="lead"/>'

    candidates = _extract_media_candidates(entry, html, "https://example.com/a")

    assert [candidate.source_field for candidate in candidates] == ["media_content"]
    assert candidates[0].width == 1200
