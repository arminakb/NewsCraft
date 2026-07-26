from __future__ import annotations

CONTENT_TYPES = frozenset(
    {
        "article",
        "longform",
        "low_signal",
        "news",
        "promo",
        "research",
        "tool_update",
        "tutorial",
        "vendor_update",
        "video",
    }
)
TOPICS = {
    "ai": "AI",
    "economy": "Economy",
    "news": "News",
    "tech": "Tech",
}


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def canonical_content_type(value: str | None) -> str | None:
    normalized = _normalized_text(value)
    return normalized.lower() if normalized is not None else None


def canonical_topic(value: str | None) -> str | None:
    normalized = _normalized_text(value)
    if normalized is None:
        return None
    folded = normalized.lower()
    if folded == "general":
        return None
    return TOPICS.get(folded, folded)


def canonical_language(value: str | None) -> str | None:
    normalized = _normalized_text(value)
    return normalized.lower() if normalized is not None else None
