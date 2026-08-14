from datetime import UTC, datetime
from uuid import uuid4

from app.content.readiness import evaluate_rewrite_readiness
from app.db.models import ContentItem, Source
from app.ingestion.repository import _content_item_values
from app.sources.base import ParsedSourceItem


def test_good_news_item_is_rewrite_ready():
    result = evaluate_rewrite_readiness(
        _content_item(content_type="news", rewrite_bucket="daily_news", title="Fresh AI news", score=40)
    )

    assert result.is_ready is True
    assert result.reason == "ready"


def test_tutorial_is_ready_but_not_daily_news():
    result = evaluate_rewrite_readiness(
        _content_item(content_type="tutorial", rewrite_bucket="tutorial", title="How to build RAG", score=35)
    )

    assert result.is_ready is True
    assert "not_daily_news" in result.blockers


def test_promo_and_low_signal_are_blocked():
    promo = evaluate_rewrite_readiness(_content_item(content_type="promo", rewrite_bucket="promo_review", score=20))
    low_signal = evaluate_rewrite_readiness(
        _content_item(content_type="low_signal", rewrite_bucket="low_signal_review", score=20)
    )

    assert promo.is_ready is False
    assert "navigation_or_promotional_text" in promo.blockers
    assert low_signal.is_ready is False
    assert "insufficient_facts" in low_signal.blockers


def test_stale_archive_blocked_from_daily_news():
    result = evaluate_rewrite_readiness(
        _content_item(content_type="news", rewrite_bucket="daily_news", freshness_bucket="archive", score=20)
    )

    assert result.is_ready is False
    assert "stale_or_archive" in result.blockers


def test_longform_allowed_only_in_longform_bucket():
    allowed = evaluate_rewrite_readiness(
        _content_item(content_type="longform", rewrite_bucket="longform_analysis", freshness_bucket="archive", score=20)
    )
    blocked = evaluate_rewrite_readiness(
        _content_item(content_type="longform", rewrite_bucket="daily_news", freshness_bucket="archive", score=20)
    )

    assert allowed.is_ready is True
    assert blocked.is_ready is False
    assert "wrong_longform_bucket" in blocked.blockers


def test_missing_title_url_or_text_is_blocked():
    assert "missing_title" in evaluate_rewrite_readiness(_content_item(title="")).blockers
    assert "missing_source_url" in evaluate_rewrite_readiness(_content_item(canonical_url=None)).blockers
    assert "insufficient_facts" in evaluate_rewrite_readiness(_content_item(content_text="tiny")).blockers


def test_missing_durable_quality_reasons_uses_source_platform_threshold():
    rss_item = _content_item(content_text="one two three four five six seven eight nine ten")
    rss_item.classification_metadata = {"source_platform": "rss"}
    telegram_item = _content_item(content_text="one two three four five six seven eight nine ten")
    telegram_item.classification_metadata = {"source_platform": "telegram_public"}

    assert "insufficient_facts" in evaluate_rewrite_readiness(rss_item).blockers
    assert "insufficient_facts" not in evaluate_rewrite_readiness(telegram_item).blockers


def test_repository_stores_rewrite_readiness_fields():
    values = _content_item_values(
        Source(
            id=uuid4(),
            platform="rss",
            name="AI News",
            source_group="ai",
            language_hint="en",
            default_timezone="UTC",
            active=True,
        ),
        ParsedSourceItem(
            external_id_raw="guid-1",
            external_id_norm="guid-1",
            source_url="https://example.com/story",
            source_url_norm="https://example.com/story",
            canonical_url_candidate="https://example.com/story",
            title="OpenAI announces new model today",
            summary="The company announced a fresh AI model for developers today.",
            content_html=None,
            content_text=(
                "The company announced a fresh AI model for developers today. "
                "Independent reviewers measured faster responses in three published trials. "
                "The release notes identify the supported regions and known limitations."
            ),
            author=None,
            categories=[],
            published_raw="2026-07-05T10:00:00+00:00",
            published_at=datetime(2026, 7, 5, 10, tzinfo=UTC),
            date_parse_status="parsed",
            parser_meta={},
        ),
    )

    assert values["is_rewrite_ready"] is True
    assert values["rewrite_ready_reason"] == "ready"
    assert values["rewrite_blockers"] == []


def _content_item(
    content_type: str = "news",
    rewrite_bucket: str = "daily_news",
    title: str | None = "Fresh AI news",
    canonical_url: str | None = "https://example.com/story",
    content_text: str = "Useful source text with enough meaningful detail for rewriting.",
    freshness_bucket: str = "fresh",
    score: int = 30,
) -> ContentItem:
    return ContentItem(
        id=uuid4(),
        item_type="article",
        canonical_url=canonical_url,
        title=title,
        content_text=content_text,
        sort_at=datetime(2026, 7, 6, tzinfo=UTC),
        date_parse_status="parsed",
        content_type=content_type,
        rewrite_bucket=rewrite_bucket,
        freshness_bucket=freshness_bucket,
        score=score,
        classification_metadata={"source_domain": "example.com"},
    )
