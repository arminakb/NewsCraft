from datetime import UTC, datetime
from uuid import uuid4

from app.db.models import Source
from app.ingestion.repository import _content_item_values
from app.normalization.titles import normalize_telegram_title
from app.sources.base import ParsedSourceItem


def test_generates_persian_title_from_emoji_only_title():
    result = normalize_telegram_title("✅", "آموزش ساخت بات هوش مصنوعی با پایتون\nادامه متن")

    assert result.title == "آموزش ساخت بات هوش مصنوعی با پایتون"
    assert result.quality == "generated"
    assert result.was_generated is True


def test_generates_english_title_from_emoji_only_title():
    result = normalize_telegram_title("🔥", "OpenAI releases a new API for developers.\nMore details follow.")

    assert result.title == "OpenAI releases a new API for developers"
    assert result.was_generated is True


def test_generates_title_for_empty_or_symbol_only_title():
    assert normalize_telegram_title("", "A useful update about vector databases.").title.startswith("A useful update")
    assert normalize_telegram_title("!!!", "A useful update about vector databases.").title.startswith(
        "A useful update"
    )


def test_keeps_meaningful_title_unchanged():
    result = normalize_telegram_title("AI funding round announced", "Body text")

    assert result.title == "AI funding round announced"
    assert result.quality == "good"
    assert result.was_generated is False


def test_generated_title_is_limited_to_100_characters():
    result = normalize_telegram_title("✅", "This is a very long Telegram post title candidate " * 5)

    assert len(result.title) <= 100
    assert result.was_generated is True


def test_low_signal_when_no_meaningful_title_can_be_generated():
    result = normalize_telegram_title("✅", "🔥 ✅ !!!")

    assert result.quality == "low_signal"
    assert result.low_signal is True


def test_repository_stores_generated_telegram_title_before_classification():
    values = _content_item_values(
        Source(
            id=uuid4(),
            platform="telegram_public",
            name="Persian AI",
            telegram_username="persian_ai",
            source_group="ai",
            language_hint="fa",
            default_timezone="UTC",
            active=True,
        ),
        ParsedSourceItem(
            external_id_raw="persian_ai/10",
            external_id_norm="persian_ai/10",
            source_url="https://t.me/persian_ai/10",
            source_url_norm="https://t.me/persian_ai/10",
            canonical_url_candidate="https://t.me/persian_ai/10",
            title="✅",
            summary="آموزش ساخت بات هوش مصنوعی با پایتون",
            content_html=None,
            content_text="آموزش ساخت بات هوش مصنوعی با پایتون\nدر این راهنما پیاده سازی را توضیح می دهیم.",
            author=None,
            categories=[],
            published_raw="2026-07-05T10:00:00+00:00",
            published_at=datetime(2026, 7, 5, 10, tzinfo=UTC),
            date_parse_status="parsed",
            parser_meta={},
        ),
    )

    assert values["title"] == "آموزش ساخت بات هوش مصنوعی با پایتون"
    assert values["title_quality"] == "generated"
    assert values["title_was_generated"] is True
    assert values["content_type"] == "tutorial"
