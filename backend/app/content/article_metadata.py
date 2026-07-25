from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, literal

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


@dataclass(frozen=True, slots=True)
class CanonicalArticleClassification:
    content_type: str | None
    topic: str | None
    language: str | None


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


def canonicalize_article_classification(
    *,
    content_type: str | None,
    topic: str | None,
    language: str | None,
) -> CanonicalArticleClassification:
    canonical_type = canonical_content_type(content_type)
    canonical_subject = canonical_topic(topic)
    canonical_language_code = canonical_language(language)

    if canonical_type == "article" and canonical_subject == "News":
        canonical_type = "news"
        canonical_subject = None
    elif (
        canonical_type is not None
        and canonical_subject is not None
        and canonical_type.lower() == canonical_subject.lower()
    ):
        canonical_subject = None

    return CanonicalArticleClassification(
        content_type=canonical_type,
        topic=canonical_subject,
        language=canonical_language_code,
    )


def normalized_text_expression(expression):
    return func.nullif(func.regexp_replace(func.btrim(expression), r"\s+", " ", "g"), "")


def canonical_article_expressions(content_type_expression, topic_expression, language_expression):
    raw_type = func.lower(normalized_text_expression(content_type_expression))
    raw_topic = normalized_text_expression(topic_expression)
    folded_topic = func.lower(raw_topic)
    canonical_subject = case(
        (folded_topic == "ai", literal("AI")),
        (folded_topic == "economy", literal("Economy")),
        (folded_topic == "news", literal("News")),
        (folded_topic == "tech", literal("Tech")),
        (folded_topic == "general", None),
        else_=folded_topic,
    )
    promoted_type = case(
        ((raw_type == "article") & (canonical_subject == "News"), literal("news")),
        else_=raw_type,
    )
    deduplicated_subject = case(
        (
            (promoted_type.is_not(None))
            & (canonical_subject.is_not(None))
            & (func.lower(promoted_type) == func.lower(canonical_subject)),
            None,
        ),
        else_=canonical_subject,
    )
    language = func.lower(normalized_text_expression(language_expression))
    return promoted_type, deduplicated_subject, language
