from datetime import UTC, datetime
from uuid import uuid4

from app.content.classification import classify_content_item
from app.db.models import Source
from app.ingestion.repository import _content_item_values
from app.sources.base import MediaCandidate, ParsedSourceItem


def test_classifies_tutorial_content():
    result = classify_content_item(
        _source(name="Machine Learning Mastery Blog", homepage_url="https://machinelearningmastery.com"),
        _item(
            title="How to build a RAG pipeline in Python",
            body="A step by step tutorial with code examples and implementation details.",
        ),
    )

    assert result.content_type == "tutorial"
    assert result.confidence >= 0.8
    assert result.reasons


def test_classifies_news_content():
    result = classify_content_item(
        _source(name="AI News", homepage_url="https://example.com"),
        _item(title="OpenAI announces new multimodal model today", body="The company announced the launch today."),
    )

    assert result.content_type == "news"


def test_classifies_research_content():
    result = classify_content_item(
        _source(name="arXiv AI", homepage_url="https://arxiv.org"),
        _item(
            title="New research paper introduces benchmark for language agents",
            url="https://arxiv.org/abs/2607.12345",
            body="The paper reports experiments, benchmark results, and ablation studies.",
        ),
    )

    assert result.content_type == "research"


def test_classifies_youtube_feed_as_video():
    result = classify_content_item(
        _source(name="AI2 YouTube", feed_url="https://www.youtube.com/feeds/videos.xml?channel_id=abc"),
        _item(
            title="Understanding retrieval augmented generation",
            url="https://www.youtube.com/watch?v=abc",
            media=[
                MediaCandidate("https://youtu.be/thumb.jpg", "https://youtu.be/thumb.jpg", "image", "media_thumbnail")
            ],
        ),
    )

    assert result.content_type == "video"


def test_classifies_vendor_update_content():
    result = classify_content_item(
        _source(name="DeepMind Blog", homepage_url="https://deepmind.google"),
        _item(
            title="DeepMind shares Gemini product update",
            body="The company announced availability and roadmap updates for Gemini.",
        ),
    )

    assert result.content_type == "vendor_update"


def test_classifies_tool_update_content():
    result = classify_content_item(
        _source(name="OpenAI Blog", homepage_url="https://openai.com"),
        _item(
            title="OpenAI releases new Responses API and SDK tools",
            body="Developers can use the new API, SDK, model controls, and tool calling features.",
        ),
    )

    assert result.content_type == "tool_update"


def test_classifies_longform_content():
    result = classify_content_item(
        _source(name="Medium Strategy", homepage_url="https://medium.com"),
        _item(
            title="A strategic analysis of autonomous AI agents",
            body="This longform analysis explores implications, tradeoffs, and strategy. " * 70,
        ),
    )

    assert result.content_type == "longform"


def test_classifies_promo_content():
    result = classify_content_item(
        _source(name="Tool Sales", homepage_url="https://tools.example"),
        _item(title="Limited time discount on our AI automation tool", body="Buy now and use coupon code SAVE50."),
    )

    assert result.content_type == "promo"


def test_classifies_low_signal_content():
    result = classify_content_item(
        _source(platform="telegram_public", name="Weak Telegram", telegram_username="weak"),
        _item(title="✅", body="✅🔥", url="https://t.me/weak/1"),
    )

    assert result.content_type == "low_signal"
    assert "weak_text" in result.quality_flags


def test_classifies_persian_telegram_tutorial():
    result = classify_content_item(
        _source(platform="telegram_public", name="Persian AI", telegram_username="persian_ai", language_hint="fa"),
        _item(
            title="آموزش ساخت بات هوش مصنوعی با پایتون",
            body="در این راهنما به صورت مرحله به مرحله پیاده سازی و کدنویسی را توضیح می دهیم.",
            url="https://t.me/persian_ai/10",
        ),
    )

    assert result.content_type == "tutorial"


def test_classifies_english_rss_article_by_default():
    result = classify_content_item(
        _source(name="Engineering Blog", homepage_url="https://engineering.example"),
        _item(
            title="A practical overview of vector search systems",
            body="This article explains architecture, indexing, ranking, and operational tradeoffs.",
        ),
    )

    assert result.content_type == "article"


def test_content_item_values_store_classification_metadata():
    values = _content_item_values(
        _source(name="Machine Learning Mastery Blog", homepage_url="https://machinelearningmastery.com"),
        _item(
            title="How to train a classifier in Python",
            body="This tutorial walks through implementation code and evaluation step by step.",
        ),
    )

    assert values["content_type"] == "tutorial"
    assert values["content_type_confidence"] > 0
    assert values["classification_reasons"]
    assert values["classification_metadata"]["quality_flags"]


def _source(
    platform: str = "rss",
    name: str = "Example",
    feed_url: str | None = None,
    homepage_url: str | None = None,
    telegram_username: str | None = None,
    language_hint: str = "en",
) -> Source:
    return Source(
        id=uuid4(),
        platform=platform,
        name=name,
        feed_url=feed_url,
        homepage_url=homepage_url,
        telegram_username=telegram_username,
        source_group="ai",
        language_hint=language_hint,
        default_timezone="UTC",
        active=True,
    )


def _item(
    title: str,
    body: str = "Useful technical article text with enough detail for classification.",
    url: str = "https://example.com/story",
    media: list[MediaCandidate] | None = None,
) -> ParsedSourceItem:
    return ParsedSourceItem(
        external_id_raw="guid-1",
        external_id_norm="guid-1",
        source_url=url,
        source_url_norm=url,
        canonical_url_candidate=url,
        title=title,
        summary=body,
        content_html=None,
        content_text=body,
        author=None,
        categories=[],
        published_raw="2026-07-05T10:00:00+00:00",
        published_at=datetime(2026, 7, 5, 10, tzinfo=UTC),
        date_parse_status="parsed",
        media_candidates=media or [],
        parser_meta={},
    )
