from datetime import UTC, datetime
from uuid import uuid4

from app.content.scoring import score_content_item
from app.db.models import Source
from app.ingestion.repository import _content_item_values
from app.sources.base import MediaCandidate, ParsedSourceItem


def test_fresh_news_outranks_stale_archive_content():
    source = Source(id=uuid4(), platform="rss", name="AI News", source_group="ai", language_hint="en")
    fresh = _parsed_item(
        title="OpenAI announces new model today",
        summary="A fresh launch for developers.",
        published_at=datetime(2026, 7, 6, tzinfo=UTC),
    )
    stale = _parsed_item(
        title="OpenAI archive announces old model",
        summary="A very long archived article. " * 80,
        url="https://example.com/archive/2020/old-model",
        published_at=datetime(2020, 1, 1, tzinfo=UTC),
        media_count=8,
    )

    assert _score(source, fresh, "news") > _score(source, stale, "news")


def test_overlong_content_has_capped_length_benefit():
    source = Source(id=uuid4(), platform="rss", name="Engineering Blog", source_group="ai", language_hint="en")
    normal = _score(source, _parsed_item("Vector search guide", "Useful body. " * 80), "article")
    overlong = _score(source, _parsed_item("Vector search guide", "Useful body. " * 800), "article")

    assert overlong - normal <= 10


def test_media_bonus_is_capped():
    source = Source(id=uuid4(), platform="rss", name="AI News", source_group="ai", language_hint="en")
    one_media = _score(source, _parsed_item("AI story", "Useful body. " * 30, media_count=1), "news")
    many_media = _score(source, _parsed_item("AI story", "Useful body. " * 30, media_count=9), "news")

    assert many_media - one_media <= 4


def test_penalties_for_promo_archive_and_low_signal():
    source = Source(id=uuid4(), platform="rss", name="Tool Sales", source_group="ai", language_hint="en")
    base = _score(source, _parsed_item("AI update", "Useful body. " * 30), "news")
    promo = _score(source, _parsed_item("Discount on AI tool", "Buy now with coupon SAVE50."), "promo")
    archive = _score(
        source,
        _parsed_item("AI update", "Useful body. " * 30, url="https://example.com/archive/item"),
        "news",
    )
    low_signal = _score(source, _parsed_item("✅", "🔥"), "low_signal")

    assert promo < base
    assert archive < base
    assert low_signal < base


def test_source_tier_bonus_and_breakdown_are_serialized():
    source = Source(
        id=uuid4(),
        platform="rss",
        name="DeepMind Blog",
        homepage_url="https://deepmind.google",
        source_group="ai",
        language_hint="en",
    )
    result = score_content_item(
        source,
        _parsed_item("Gemini research update", "Useful body. " * 30),
        content_type="research",
        now=datetime(2026, 7, 6, tzinfo=UTC),
    )

    assert result.source_tier == "A"
    assert result.breakdown["source_tier_bonus"] > 0
    assert isinstance(result.breakdown["final_score"], int)


def test_repository_stores_score_breakdown_and_ranking_metadata():
    values = _content_item_values(
        Source(
            id=uuid4(),
            platform="rss",
            name="DeepMind Blog",
            homepage_url="https://deepmind.google",
            source_group="ai",
            language_hint="en",
        ),
        _parsed_item("Gemini research update", "Useful body. " * 30),
    )

    assert values["score"] == values["score_breakdown"]["final_score"]
    assert values["source_tier"] == "A"
    assert values["freshness_bucket"]
    assert values["ranking_metadata"]["content_type"]


def _parsed_item(
    title: str,
    summary: str,
    categories: list[str] | None = None,
    parser_meta: dict | None = None,
    url: str = "https://example.com/story",
    published_at: datetime | None = None,
    media_count: int = 0,
) -> ParsedSourceItem:
    return ParsedSourceItem(
        external_id_raw="guid-1",
        external_id_norm="guid-1",
        source_url=url,
        source_url_norm=url,
        canonical_url_candidate=url,
        title=title,
        summary=summary,
        content_html=None,
        content_text=f"{title}\n{summary}",
        author=None,
        categories=categories or [],
        published_raw="2026-07-05T10:00:00+00:00",
        published_at=published_at if published_at is not None else datetime(2026, 7, 5, 10, tzinfo=UTC),
        date_parse_status="parsed",
        media_candidates=[
            MediaCandidate(f"https://example.com/{idx}.jpg", f"https://example.com/{idx}.jpg", "image", "inline_img")
            for idx in range(media_count)
        ],
        parser_meta=parser_meta or {},
    )


def _score(source: Source, item: ParsedSourceItem, content_type: str) -> int:
    return score_content_item(source, item, content_type=content_type, now=datetime(2026, 7, 6, tzinfo=UTC)).score
