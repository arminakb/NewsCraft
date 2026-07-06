from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.db.models import Source
from app.sources.base import ParsedSourceItem

AI_KEYWORDS = (
    "ai",
    "artificial intelligence",
    "openai",
    "anthropic",
    "deepmind",
    "llm",
    "large language model",
    "chatgpt",
    "claude",
    "gemini",
    "machine learning",
    "deep learning",
    "neural",
    "agent",
    "agents",
    "automation",
    "robotics",
    "computer vision",
    "generative ai",
    "multimodal",
    "model",
)

TECH_KEYWORDS = (
    "startup",
    "github",
    "developer",
    "software",
    "api",
    "cloud",
    "cybersecurity",
    "security",
    "chip",
    "nvidia",
    "apple",
    "meta",
    "microsoft",
    "google",
    "database",
    "framework",
    "open source",
)

ECONOMY_KEYWORDS = (
    "economy",
    "market",
    "markets",
    "finance",
    "inflation",
    "rates",
    "fed",
    "treasury",
    "bank",
    "gdp",
    "employment",
    "اقتصاد",
    "بازار",
    "بورس",
    "دلار",
    "تورم",
    "بانک",
)

FARSI_NEWS_KEYWORDS = (
    "ایران",
    "خبر",
    "فوری",
    "دولت",
    "مجلس",
    "وزارت",
)

TAG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    score: int
    tags: list[str]
    signals: dict[str, Any]
    score_breakdown: dict[str, Any] | None = None
    ranking_metadata: dict[str, Any] | None = None


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
    text = _searchable_text(parsed_item)
    url = parsed_item.canonical_url_candidate or parsed_item.source_url_norm or parsed_item.source_url or ""
    text_length = len(parsed_item.content_text or "")
    media_count = len(parsed_item.media_candidates)
    source_tier = _source_tier(source)
    freshness_bucket = _freshness_bucket(parsed_item.published_at, now)
    is_archive = _is_archive_url(url)

    relevance_score = min(_keyword_score(text, (*AI_KEYWORDS, *TECH_KEYWORDS)) * 3, 24) + min(text_length // 120, 10)
    source_tier_bonus = {"A": 12, "B": 6}.get(source_tier, 0)
    freshness_score = {"fresh": 16, "recent": 10, "evergreen": 5, "unknown": 3, "stale": 0, "archive": 0}[
        freshness_bucket
    ]
    capped_media_quality_bonus = min(media_count, 3) * 2
    engagement_bonus, engagement_signals = _engagement_score((source.platform or "").lower(), parsed_item.parser_meta)
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


def classify_and_score(source: Source, parsed_item: ParsedSourceItem) -> ClassificationResult:
    text = _searchable_text(parsed_item)
    source_group = (source.source_group or "").lower()
    platform = (source.platform or "").lower()

    keyword_scores = {
        "AI": _keyword_score(text, AI_KEYWORDS),
        "Tech": _keyword_score(text, TECH_KEYWORDS),
        "Economy": _keyword_score(text, ECONOMY_KEYWORDS),
        "News": _keyword_score(text, FARSI_NEWS_KEYWORDS),
    }
    category = _category_for_scores(keyword_scores, source_group)
    matched_keywords = _matched_keywords(text)
    engagement_score, engagement_signals = _engagement_score(platform, parsed_item.parser_meta)
    group_bonus = _source_group_bonus(source_group, category)
    category_score = keyword_scores.get(category, 0)
    secondary_score = sum(value for key, value in keyword_scores.items() if key != category)
    score = max(0, category_score * 3 + secondary_score + engagement_score + group_bonus)

    return ClassificationResult(
        category=category,
        score=score,
        tags=_build_tags(parsed_item.categories, category, matched_keywords),
        signals={
            "category": category,
            "keyword_scores": keyword_scores,
            "matched_keywords": matched_keywords,
            "source_group": source_group,
            **engagement_signals,
        },
    )


def _searchable_text(parsed_item: ParsedSourceItem) -> str:
    return " ".join(
        value
        for value in (
            parsed_item.title,
            parsed_item.summary,
            parsed_item.content_text,
            " ".join(parsed_item.categories or []),
        )
        if value
    ).lower()


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


def _keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(text.count(keyword) for keyword in keywords)


def _category_for_scores(keyword_scores: dict[str, int], source_group: str) -> str:
    if source_group.startswith("farsi_economy") or source_group == "economy":
        return "Economy"
    if source_group.startswith("farsi_news") and keyword_scores["Economy"] > 0:
        return "Economy"
    if source_group.startswith("farsi_news") and keyword_scores["Economy"] <= 0:
        return "News"

    category, score = max(keyword_scores.items(), key=lambda item: item[1])
    if score > 0:
        return category
    if source_group in {"ai", "company_news", "ai_industry_news"}:
        return "AI"
    if source_group in {"tech", "startup_news", "developer_trends"}:
        return "Tech"
    return "General"


def _matched_keywords(text: str) -> list[str]:
    matches: list[str] = []
    for keyword in (*AI_KEYWORDS, *TECH_KEYWORDS, *ECONOMY_KEYWORDS, *FARSI_NEWS_KEYWORDS):
        if keyword in text and keyword not in matches:
            matches.append(keyword)
    return matches[:12]


def _engagement_score(platform: str, parser_meta: dict[str, Any]) -> tuple[int, dict[str, int]]:
    if platform != "telegram_public":
        return 0, {}

    views = _int_value(parser_meta.get("views"))
    reactions_raw = parser_meta.get("reactions") or {}
    reactions = sum(_int_value(value) for value in reactions_raw.values()) if isinstance(reactions_raw, dict) else 0
    score = views // 500 + reactions
    return score, {"views": views, "reactions": reactions}


def _source_group_bonus(source_group: str, category: str) -> int:
    if category == "AI" and "ai" in source_group:
        return 3
    if category == "Tech" and any(value in source_group for value in ("tech", "developer", "startup")):
        return 3
    if category == "Economy" and "economy" in source_group:
        return 3
    return 0


def _build_tags(source_categories: list[str], category: str, matched_keywords: list[str]) -> list[str]:
    tags: list[str] = []
    for value in [*source_categories, category, *matched_keywords[:5]]:
        slug = _slug(value)
        if slug and slug not in tags:
            tags.append(slug)
    return tags[:10]


def _slug(value: str) -> str:
    normalized = TAG_RE.sub("-", str(value).strip().lower()).strip("-")
    return normalized or str(value).strip().lower()


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
