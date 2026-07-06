from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.content.buckets import assign_rewrite_bucket
from app.db.models import ContentItem, Source
from app.ingestion.repository import _content_item_values, _rewrite_candidate_insert_statement, plan_rewrite_candidate
from app.sources.base import ParsedSourceItem


def test_assigns_rewrite_buckets_for_content_types():
    assert assign_rewrite_bucket("news").bucket_type == "daily_news"
    assert assign_rewrite_bucket("article").bucket_type == "technical_article"
    assert assign_rewrite_bucket("tutorial").bucket_type == "tutorial"
    assert assign_rewrite_bucket("research").bucket_type == "research"
    assert assign_rewrite_bucket("video").bucket_type == "video"
    assert assign_rewrite_bucket("vendor_update").bucket_type == "vendor_update"
    assert assign_rewrite_bucket("longform").bucket_type == "longform_analysis"


def test_tool_updates_route_by_source():
    assert assign_rewrite_bucket("tool_update", source_domain="openai.com").bucket_type == "vendor_update"
    assert assign_rewrite_bucket("tool_update", source_domain="indie.dev").bucket_type == "daily_news"


def test_promo_and_low_signal_candidates_are_excluded():
    promo = assign_rewrite_bucket("promo")
    low_signal = assign_rewrite_bucket("low_signal")

    assert promo.bucket_type == "promo_review"
    assert promo.status == "excluded"
    assert low_signal.bucket_type == "low_signal_review"
    assert low_signal.status == "excluded"


def test_content_item_values_store_rewrite_bucket():
    values = _content_item_values(
        _source("OpenAI Blog", homepage_url="https://openai.com"),
        _item(
            title="OpenAI releases new Responses API and SDK tools",
            body="Developers can use the new API, SDK, model controls, and tool calling features.",
        ),
    )

    assert values["content_type"] == "tool_update"
    assert values["rewrite_bucket"] == "vendor_update"


def test_rewrite_candidate_plan_uses_bucket_and_score():
    content_item = ContentItem(
        id=uuid4(),
        item_type="article",
        title="AI News",
        sort_at=datetime(2026, 7, 6, tzinfo=UTC),
        date_parse_status="parsed",
        content_type="news",
        rewrite_bucket="daily_news",
        score=42,
    )

    values = plan_rewrite_candidate(content_item)

    assert values["content_item_id"] == content_item.id
    assert values["bucket_type"] == "daily_news"
    assert values["priority_score"] == 42
    assert values["status"] == "pending"


def test_rewrite_candidate_upsert_matches_unique_bucket_constraint():
    values = {
        "content_item_id": uuid4(),
        "bucket_type": "daily_news",
        "priority_score": 10,
        "status": "pending",
        "reason": "news -> daily_news",
    }

    sql = str(_rewrite_candidate_insert_statement(values).compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (content_item_id, bucket_type)" in sql
    assert "priority_score" in sql


def _source(name: str, homepage_url: str | None = None) -> Source:
    return Source(
        id=uuid4(),
        platform="rss",
        name=name,
        homepage_url=homepage_url,
        source_group="ai",
        language_hint="en",
        default_timezone="UTC",
        active=True,
    )


def _item(title: str, body: str) -> ParsedSourceItem:
    return ParsedSourceItem(
        external_id_raw="guid-1",
        external_id_norm="guid-1",
        source_url="https://example.com/story",
        source_url_norm="https://example.com/story",
        canonical_url_candidate="https://example.com/story",
        title=title,
        summary=body,
        content_html=None,
        content_text=body,
        author=None,
        categories=[],
        published_raw="2026-07-05T10:00:00+00:00",
        published_at=datetime(2026, 7, 5, 10, tzinfo=UTC),
        date_parse_status="parsed",
        parser_meta={},
    )
