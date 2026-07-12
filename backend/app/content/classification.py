from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.db.models import Source
from app.sources.base import ParsedSourceItem

MEANINGFUL_RE = re.compile(r"[\w\u0600-\u06ff]", re.UNICODE)
TAG_RE = re.compile(r"[^a-z0-9]+")

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

TUTORIAL_KEYWORDS = (
    "tutorial",
    "how to",
    "step by step",
    "guide",
    "walkthrough",
    "implementation",
    "code example",
    "python",
    "آموزش",
    "راهنما",
    "مرحله به مرحله",
    "پیاده سازی",
    "کدنویسی",
)
RESEARCH_KEYWORDS = (
    "research",
    "paper",
    "benchmark",
    "experiment",
    "experiments",
    "ablation",
    "arxiv",
    "study",
    "مطالعه",
    "پژوهش",
    "مقاله",
)
NEWS_KEYWORDS = (
    "announces",
    "announced",
    "launches",
    "launched",
    "today",
    "breaking",
    "خبر",
    "فوری",
    "اعلام",
)
TOOL_KEYWORDS = (
    "api",
    "sdk",
    "tool",
    "tools",
    "release",
    "releases",
    "model",
    "developer",
    "developers",
    "کیت توسعه",
)
VENDOR_KEYWORDS = (
    "product update",
    "availability",
    "roadmap",
    "company announced",
    "gemini",
    "claude",
    "chatgpt",
)
PROMO_KEYWORDS = (
    "discount",
    "coupon",
    "buy now",
    "limited time",
    "sale",
    "promo",
    "save",
    "تخفیف",
    "خرید",
)
LONGFORM_KEYWORDS = (
    "longform",
    "analysis",
    "strategic",
    "strategy",
    "deep dive",
    "implications",
    "تحلیل",
)
VENDOR_DOMAINS = ("openai.com", "deepmind.google", "google", "microsoft.com", "amazon.com", "aws.amazon.com")


@dataclass(frozen=True)
class ContentClassification:
    content_type: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ContentTaxonomy:
    category: str
    tags: list[str]
    signals: dict[str, Any]


def classify_content_item(source: Source, parsed_item: ParsedSourceItem) -> ContentClassification:
    text = _searchable_text(source, parsed_item)
    url = parsed_item.canonical_url_candidate or parsed_item.source_url_norm or parsed_item.source_url or ""
    domain = _domain(url) or _domain(source.homepage_url or source.feed_url or "")
    text_length = len(parsed_item.content_text or "")
    quality_flags = _quality_flags(parsed_item, text_length)

    if "weak_text" in quality_flags:
        return _result("low_signal", 0.95, ["text is too weak for rewrite"], quality_flags, source, parsed_item)
    if _is_youtube(source, url, domain) or any(candidate.kind == "video" for candidate in parsed_item.media_candidates):
        return _result("video", 0.95, ["youtube or video media signal"], quality_flags, source, parsed_item)
    if _has(text, PROMO_KEYWORDS):
        return _result("promo", 0.9, ["promotional language"], quality_flags, source, parsed_item)
    if _has(text, TUTORIAL_KEYWORDS):
        return _result("tutorial", 0.86, ["tutorial or implementation signal"], quality_flags, source, parsed_item)
    if "arxiv.org" in domain or _has(text, RESEARCH_KEYWORDS):
        return _result("research", 0.86, ["research publication signal"], quality_flags, source, parsed_item)
    if text_length >= 3500 or ("medium.com" in domain and _has(text, LONGFORM_KEYWORDS)):
        return _result("longform", 0.82, ["longform analysis signal"], quality_flags, source, parsed_item)
    if _is_vendor(domain, source) and _has(text, TOOL_KEYWORDS):
        return _result("tool_update", 0.84, ["vendor developer/tooling update"], quality_flags, source, parsed_item)
    if _is_vendor(domain, source) and (_has(text, VENDOR_KEYWORDS) or _has(text, NEWS_KEYWORDS)):
        return _result("vendor_update", 0.82, ["vendor product/company update"], quality_flags, source, parsed_item)
    if _has(text, NEWS_KEYWORDS):
        return _result("news", 0.78, ["news language signal"], quality_flags, source, parsed_item)
    return _result("article", 0.62, ["default technical article"], quality_flags, source, parsed_item)


def classify_content_taxonomy(source: Source, parsed_item: ParsedSourceItem) -> ContentTaxonomy:
    text = _taxonomy_searchable_text(parsed_item)
    source_group = (source.source_group or "").lower()
    platform = (source.platform or "").lower()

    keyword_scores = {
        "AI": score_keywords(text, AI_KEYWORDS),
        "Tech": score_keywords(text, TECH_KEYWORDS),
        "Economy": score_keywords(text, ECONOMY_KEYWORDS),
        "News": score_keywords(text, FARSI_NEWS_KEYWORDS),
    }
    category = _category_for_scores(keyword_scores, source_group)
    matched_keywords = _matched_keywords(text)
    _, engagement_signals = telegram_engagement_score(platform, parsed_item.parser_meta)

    return ContentTaxonomy(
        category=category,
        tags=_build_tags(parsed_item.categories, category, matched_keywords),
        signals={
            "category": category,
            "keyword_scores": keyword_scores,
            "matched_keywords": matched_keywords,
            "source_group": source_group,
            **engagement_signals,
        },
    )


def _result(
    content_type: str,
    confidence: float,
    reasons: list[str],
    quality_flags: list[str],
    source: Source,
    parsed_item: ParsedSourceItem,
) -> ContentClassification:
    return ContentClassification(
        content_type=content_type,
        confidence=confidence,
        reasons=reasons,
        quality_flags=quality_flags,
        metadata={
            "source_platform": source.platform,
            "source_name": source.name,
            "source_domain": _domain(parsed_item.canonical_url_candidate or parsed_item.source_url_norm or "")
            or _domain(source.homepage_url or source.feed_url or ""),
            "text_length": len(parsed_item.content_text or ""),
        },
    )


def _searchable_text(source: Source, parsed_item: ParsedSourceItem) -> str:
    return " ".join(
        str(value)
        for value in (
            source.name,
            source.homepage_url,
            source.feed_url,
            parsed_item.source_url,
            parsed_item.title,
            parsed_item.summary,
            parsed_item.content_text,
            " ".join(parsed_item.categories or []),
        )
        if value
    ).casefold()


def _taxonomy_searchable_text(parsed_item: ParsedSourceItem) -> str:
    return " ".join(
        value
        for value in (
            parsed_item.title,
            parsed_item.summary,
            parsed_item.content_text,
            " ".join(parsed_item.categories or []),
        )
        if value
    ).casefold()


def score_keywords(text: str, keywords: tuple[str, ...]) -> int:
    return sum(text.count(keyword) for keyword in keywords)


def telegram_engagement_score(platform: str, parser_meta: dict[str, Any]) -> tuple[int, dict[str, int]]:
    if platform != "telegram_public":
        return 0, {}

    views = _int_value(parser_meta.get("views"))
    reactions_raw = parser_meta.get("reactions") or {}
    reactions = sum(_int_value(value) for value in reactions_raw.values()) if isinstance(reactions_raw, dict) else 0
    score = views // 500 + reactions
    return score, {"views": views, "reactions": reactions}


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


def _quality_flags(parsed_item: ParsedSourceItem, text_length: int) -> list[str]:
    flags: list[str] = []
    title = parsed_item.title or ""
    body = parsed_item.content_text or ""
    if MEANINGFUL_RE.search(title):
        flags.append("meaningful_title")
    if text_length >= 80:
        flags.append("enough_text")
    if len(MEANINGFUL_RE.findall(f"{title} {body}")) < 8:
        flags.append("weak_text")
    return flags


def _has(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _domain(url: str) -> str:
    if not url:
        return ""
    return urlsplit(url).netloc.casefold().removeprefix("www.")


def _is_youtube(source: Source, url: str, domain: str) -> bool:
    source_text = f"{source.name} {source.feed_url} {url}".casefold()
    return "youtube" in source_text or "youtube.com" in domain or "youtu.be" in domain


def _is_vendor(domain: str, source: Source) -> bool:
    source_text = f"{source.name} {source.homepage_url} {source.feed_url}".casefold()
    return any(value in domain or value in source_text for value in VENDOR_DOMAINS)
