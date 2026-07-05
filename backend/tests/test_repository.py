from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.db.models import MediaAsset, Source
from app.ingestion.repository import (
    IngestionRepository,
    _identity_insert_statement,
    build_item_identities,
    plan_item_media_rows,
)
from app.sources.base import MediaCandidate, ParsedSourceItem


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
    source_sql = str(
        _identity_insert_statement({**values, "scope": "source"}).compile(dialect=postgresql.dialect())
    )

    assert "ON CONFLICT (identity_type, identity_hash) WHERE scope = 'global' AND is_strong" in global_sql
    assert (
        "ON CONFLICT (source_id, identity_type, identity_hash) WHERE scope = 'source' AND is_strong" in source_sql
    )


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
