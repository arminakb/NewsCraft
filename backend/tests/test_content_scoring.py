from datetime import UTC, datetime
from uuid import uuid4

from app.content.scoring import classify_and_score
from app.db.models import Source
from app.sources.base import ParsedSourceItem


def test_classify_and_score_prioritizes_ai_content():
    source = Source(id=uuid4(), platform="rss", name="Example", source_group="ai", language_hint="en")
    item = _parsed_item(
        title="OpenAI launches new multimodal agent platform",
        summary="The new AI system improves developer automation workflows.",
    )

    result = classify_and_score(source, item)

    assert result.category == "AI"
    assert result.score >= 10
    assert "ai" in result.tags
    assert "agent" in result.signals["matched_keywords"]


def test_classify_and_score_uses_telegram_engagement_signals():
    source = Source(
        id=uuid4(),
        platform="telegram_public",
        name="Telegram",
        telegram_username="example",
        source_group="farsi_news",
        language_hint="fa",
    )
    item = _parsed_item(
        title="خبر فوری درباره اقتصاد ایران",
        summary="بازار و اقتصاد ایران امروز با تغییرات مهم روبرو شد.",
        parser_meta={"views": 2300, "reactions": {"like": 7, "fire": 2}},
    )

    result = classify_and_score(source, item)

    assert result.category == "Economy"
    assert result.score >= 6
    assert result.signals["views"] == 2300
    assert result.signals["reactions"] == 9


def test_classify_and_score_preserves_source_categories_as_tags():
    source = Source(id=uuid4(), platform="rss", name="Example", source_group="tech", language_hint="en")
    item = _parsed_item(
        title="Database framework adds open source security tooling",
        summary="Developers get a new API for secure cloud deployments.",
        categories=["Security", "Open Source"],
    )

    result = classify_and_score(source, item)

    assert result.category == "Tech"
    assert result.score > 0
    assert result.tags[:2] == ["security", "open-source"]


def _parsed_item(
    title: str,
    summary: str,
    categories: list[str] | None = None,
    parser_meta: dict | None = None,
) -> ParsedSourceItem:
    return ParsedSourceItem(
        external_id_raw="guid-1",
        external_id_norm="guid-1",
        source_url="https://example.com/story",
        source_url_norm="https://example.com/story",
        canonical_url_candidate="https://example.com/story",
        title=title,
        summary=summary,
        content_html=None,
        content_text=f"{title}\n{summary}",
        author=None,
        categories=categories or [],
        published_raw="2026-07-05T10:00:00+00:00",
        published_at=datetime(2026, 7, 5, 10, tzinfo=UTC),
        date_parse_status="parsed",
        parser_meta=parser_meta or {},
    )
