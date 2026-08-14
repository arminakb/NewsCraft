from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.content.classification import (
    AI_KEYWORDS,
    TECH_KEYWORDS,
    score_keywords,
    taxonomy_searchable_text,
    telegram_engagement_score,
)
from app.db.models import Source
from app.sources.base import ParsedSourceItem


@dataclass(frozen=True)
class ScoreResult:
    score: int
    breakdown: dict[str, Any]
    ranking_metadata: dict[str, Any]
    freshness_bucket: str
    source_tier: str


def score_content_item(
    source: Source,
    parsed_item: ParsedSourceItem,
    content_type: str,
    title_quality: str = "good",
    now: datetime | None = None,
) -> ScoreResult:
    now = now or datetime.now(UTC)
    text = taxonomy_searchable_text(parsed_item)
    url = parsed_item.canonical_url_candidate or parsed_item.source_url_norm or parsed_item.source_url or ""
    text_length = len(parsed_item.content_text or "")
    media_count = len(parsed_item.media_candidates)
    source_tier = _source_tier(source)
    freshness_bucket = _freshness_bucket(parsed_item.published_at, now)
    is_archive = _is_archive_url(url)

    relevance_score = min(score_keywords(text, (*AI_KEYWORDS, *TECH_KEYWORDS)) * 3, 24) + min(text_length // 120, 10)
    source_tier_bonus = {"A": 12, "B": 6}.get(source_tier, 0)
    freshness_score = {"fresh": 16, "recent": 10, "evergreen": 5, "unknown": 3, "stale": 0, "archive": 0}[
        freshness_bucket
    ]
    capped_media_quality_bonus = min(media_count, 3) * 2
    engagement_bonus, engagement_signals = telegram_engagement_score(
        (source.platform or "").lower(), parsed_item.parser_meta
    )
    content_type_bonus = {
        "news": 8,
        "article": 5,
        "tutorial": 7,
        "research": 8,
        "video": 5,
        "tool_update": 6,
        "vendor_update": 6,
        "longform": 3,
        "promo": 0,
        "low_signal": 0,
    }.get(content_type, 0)
    stale_penalty = 12 if freshness_bucket == "stale" else 0
    archive_penalty = 18 if is_archive or freshness_bucket == "archive" else 0
    promotional_penalty = 25 if content_type == "promo" else 0
    low_signal_penalty = 35 if content_type == "low_signal" else 0
    emoji_title_penalty = 8 if title_quality == "low_signal" else 2 if title_quality == "generated" else 0
    overlong_penalty = 10 if text_length > 5000 and content_type != "longform" else 0

    final_score = max(
        0,
        relevance_score
        + source_tier_bonus
        + freshness_score
        + capped_media_quality_bonus
        + engagement_bonus
        + content_type_bonus
        - stale_penalty
        - archive_penalty
        - promotional_penalty
        - low_signal_penalty
        - emoji_title_penalty
        - overlong_penalty,
    )
    breakdown = {
        "relevance_score": relevance_score,
        "source_tier_bonus": source_tier_bonus,
        "freshness_score": freshness_score,
        "capped_media_quality_bonus": capped_media_quality_bonus,
        "engagement_bonus": engagement_bonus,
        "content_type_bonus": content_type_bonus,
        "stale_penalty": stale_penalty,
        "archive_penalty": archive_penalty,
        "promotional_penalty": promotional_penalty,
        "low_signal_penalty": low_signal_penalty,
        "emoji_title_penalty": emoji_title_penalty,
        "overlong_penalty": overlong_penalty,
        "final_score": int(final_score),
    }
    return ScoreResult(
        score=int(final_score),
        breakdown=breakdown,
        ranking_metadata={
            "content_type": content_type,
            "title_quality": title_quality,
            "media_count": media_count,
            "text_length": text_length,
            "is_archive": is_archive,
            **engagement_signals,
        },
        freshness_bucket=freshness_bucket,
        source_tier=source_tier,
    )


def _freshness_bucket(published_at: datetime | None, now: datetime) -> str:
    if published_at is None:
        return "unknown"
    days_old = (now - published_at).days
    if days_old <= 2:
        return "fresh"
    if days_old <= 14:
        return "recent"
    if days_old <= 90:
        return "evergreen"
    if days_old <= 365:
        return "stale"
    return "archive"


def _source_tier(source: Source) -> str:
    text = f"{source.name} {source.homepage_url} {source.feed_url}".casefold()
    if any(
        value in text
        for value in (
            "cvision",
            "llm hugging face",
            "huggingface",
            "aws machine learning blog",
            "deepmind",
            "ai2 youtube",
            "machine learning mastery",
        )
    ):
        return "A"
    if any(value in text for value in ("zarinacc", "recomender system 2023", "ai roadmap institute")):
        return "B"
    return "unknown"


def _is_archive_url(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return any(part in path for part in ("/archive", "/archives", "/2020/", "/2019/", "/2018/"))
