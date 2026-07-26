import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.content.classification import classify_content_item, classify_content_taxonomy
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
    assert "insufficient_facts" in result.quality_reasons


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


def test_content_taxonomy_prioritizes_ai_category_and_tags():
    result = classify_content_taxonomy(
        _source(name="Example", source_group="ai"),
        _item(
            title="OpenAI launches new multimodal agent platform",
            body="The new AI system improves developer automation workflows.",
        ),
    )

    assert result.category == "AI"
    assert "ai" in result.tags
    assert "agent" in result.signals["matched_keywords"]


def test_content_taxonomy_uses_telegram_engagement_signals():
    result = classify_content_taxonomy(
        _source(
            platform="telegram_public",
            name="Telegram",
            telegram_username="example",
            source_group="farsi_news",
            language_hint="fa",
        ),
        _item(
            title="خبر فوری درباره اقتصاد ایران",
            body="بازار و اقتصاد ایران امروز با تغییرات مهم روبرو شد.",
            url="https://t.me/example/1",
            parser_meta={"views": 2300, "reactions": {"like": 7, "fire": 2}},
        ),
    )

    assert result.category == "Economy"
    assert result.signals["views"] == 2300
    assert result.signals["reactions"] == 9


def test_content_taxonomy_preserves_source_categories_as_tags():
    result = classify_content_taxonomy(
        _source(name="Example", source_group="tech"),
        _item(
            title="Database framework adds open source security tooling",
            body="Developers get a new API for secure cloud deployments.",
            categories=["Security", "Open Source"],
        ),
    )

    assert result.category == "Tech"
    assert result.tags[:2] == ["security", "open-source"]


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
    assert values["classification_metadata"]["quality_reasons"]


def test_bilingual_quality_corpus_has_stable_visible_reasons():
    corpus = json.loads((Path(__file__).parent / "fixtures/content-quality-corpus.json").read_text())

    for case in corpus:
        media = (
            [MediaCandidate("https://example.com/video.mp4", "https://example.com/video.mp4", "video", "enclosure")]
            if case.get("media") == "video"
            else []
        )
        item = _item(
            title=case["title"],
            body=case["body"],
            url=f"https://example.com/{case['id']}",
            media=media,
            parser_meta=case.get("parser_meta"),
        )
        item.date_parse_status = case["date_parse_status"]
        item.published_at = None if case["date_parse_status"] == "failed" else item.published_at
        source = _source(
            platform=case["platform"],
            telegram_username="quality" if case["platform"] == "telegram_public" else None,
            language_hint=case["language"],
        )

        classification = classify_content_item(source, item)
        values = _content_item_values(source, item)

        assert classification.quality_reasons == case["expected_reasons"], case["id"]
        assert values["classification_metadata"]["quality_reasons"] == case["expected_reasons"], case["id"]
        for reason in case["expected_reasons"]:
            assert reason in values["rewrite_blockers"], case["id"]
            assert reason in values["rewrite_ready_reason"], case["id"]


def _source(
    platform: str = "rss",
    name: str = "Example",
    feed_url: str | None = None,
    homepage_url: str | None = None,
    telegram_username: str | None = None,
    language_hint: str = "en",
    source_group: str = "ai",
) -> Source:
    return Source(
        id=uuid4(),
        platform=platform,
        name=name,
        feed_url=feed_url,
        homepage_url=homepage_url,
        telegram_username=telegram_username,
        source_group=source_group,
        language_hint=language_hint,
        default_timezone="UTC",
        active=True,
    )


def _item(
    title: str,
    body: str = "Useful technical article text with enough detail for classification.",
    url: str = "https://example.com/story",
    media: list[MediaCandidate] | None = None,
    categories: list[str] | None = None,
    parser_meta: dict | None = None,
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
        categories=categories or [],
        published_raw="2026-07-05T10:00:00+00:00",
        published_at=datetime(2026, 7, 5, 10, tzinfo=UTC),
        date_parse_status="parsed",
        media_candidates=media or [],
        parser_meta=parser_meta or {},
    )
