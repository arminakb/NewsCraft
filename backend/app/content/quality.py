from __future__ import annotations

import re

from app.db.models import Source
from app.normalization.text import fingerprint_text
from app.sources.base import ParsedSourceItem

MISSING_BODY = "missing_body"
NAVIGATION_OR_PROMOTIONAL_TEXT = "navigation_or_promotional_text"
EXTRACTION_FAILED = "extraction_failed"
DUPLICATE_FRAGMENT = "duplicate_fragment"
INSUFFICIENT_FACTS = "insufficient_facts"
UNSUPPORTED_CONTENT = "unsupported_content"

QUALITY_REASON_ORDER = (
    MISSING_BODY,
    EXTRACTION_FAILED,
    NAVIGATION_OR_PROMOTIONAL_TEXT,
    DUPLICATE_FRAGMENT,
    INSUFFICIENT_FACTS,
    UNSUPPORTED_CONTENT,
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

_WORD_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)
_FRAGMENT_RE = re.compile(r"(?:\n+|(?<=[.!؟?])\s+)")
_NAVIGATION_TERMS = {
    "about",
    "archive",
    "contact",
    "home",
    "login",
    "menu",
    "privacy",
    "subscribe",
    "درباره",
    "خانه",
    "عضویت",
    "منو",
}


def content_quality_reasons(source: Source, item: ParsedSourceItem) -> list[str]:
    body = " ".join((item.content_text or "").split())
    reasons: list[str] = []
    if not body:
        reasons.append(MISSING_BODY)
    if str(item.parser_meta.get("extraction_status", "")).casefold() == "failed":
        reasons.append(EXTRACTION_FAILED)
    if body and _looks_like_navigation_or_promotion(body):
        reasons.append(NAVIGATION_OR_PROMOTIONAL_TEXT)
    if body and _contains_duplicate_fragment(item.content_text):
        reasons.append(DUPLICATE_FRAGMENT)
    minimum_words = 8 if source.platform == "telegram_public" else 16
    if body and len(_WORD_RE.findall(body)) < minimum_words:
        reasons.append(INSUFFICIENT_FACTS)
    return reasons


def with_content_support_reason(reasons: list[str], content_type: str) -> list[str]:
    values = list(reasons)
    if content_type == "promo" and NAVIGATION_OR_PROMOTIONAL_TEXT not in values:
        values.append(NAVIGATION_OR_PROMOTIONAL_TEXT)
    if content_type == "video":
        values.append(UNSUPPORTED_CONTENT)
    return [reason for reason in QUALITY_REASON_ORDER if reason in values]


def has_meaningful_content(item: ParsedSourceItem) -> bool:
    return len(_WORD_RE.findall(f"{item.title} {item.content_text}")) >= 4


def _looks_like_navigation_or_promotion(body: str) -> bool:
    normalized = body.casefold()
    if any(keyword in normalized for keyword in PROMO_KEYWORDS):
        return True
    words = [word.casefold() for word in _WORD_RE.findall(normalized)]
    navigation_count = sum(word in _NAVIGATION_TERMS for word in words)
    return bool(words) and len(words) <= 20 and navigation_count >= max(3, len(words) // 2)


def _contains_duplicate_fragment(body: str) -> bool:
    seen: set[str] = set()
    for raw_fragment in _FRAGMENT_RE.split(body):
        fragment = fingerprint_text(raw_fragment)
        if len(fragment) < 30:
            continue
        if fragment in seen:
            return True
        seen.add(fragment)
    return False
