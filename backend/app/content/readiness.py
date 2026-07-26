from __future__ import annotations

from dataclasses import dataclass

from app.content.quality import (
    DUPLICATE_FRAGMENT,
    INSUFFICIENT_FACTS,
    MISSING_BODY,
    NAVIGATION_OR_PROMOTIONAL_TEXT,
    QUALITY_REASON_ORDER,
    UNSUPPORTED_CONTENT,
)
from app.db.models import ContentItem


@dataclass(frozen=True)
class RewriteReadiness:
    is_ready: bool
    reason: str
    blockers: list[str]


def evaluate_rewrite_readiness(content_item: ContentItem) -> RewriteReadiness:
    blockers: list[str] = []
    content_type = content_item.content_type
    rewrite_bucket = content_item.rewrite_bucket
    metadata = content_item.classification_metadata or {}
    durable_quality_reasons = metadata.get("quality_reasons", [])

    if not (content_item.title or "").strip():
        blockers.append("missing_title")
    if not content_item.canonical_url:
        blockers.append("missing_source_url")
    if not (content_item.content_text or "").strip():
        blockers.append(MISSING_BODY)
    elif not durable_quality_reasons and len((content_item.content_text or "").split()) < 8:
        blockers.append(INSUFFICIENT_FACTS)
    if isinstance(durable_quality_reasons, list):
        blockers.extend(reason for reason in QUALITY_REASON_ORDER if reason in durable_quality_reasons)
    if content_type == "promo":
        blockers.append(NAVIGATION_OR_PROMOTIONAL_TEXT)
    if content_type == "low_signal" and not any(reason in blockers for reason in QUALITY_REASON_ORDER):
        blockers.append(INSUFFICIENT_FACTS)
    if content_type == "video":
        blockers.append(UNSUPPORTED_CONTENT)
    if content_type == "longform" and rewrite_bucket != "longform_analysis":
        blockers.append("wrong_longform_bucket")
    if content_type != "longform" and content_item.freshness_bucket in {"stale", "archive"}:
        blockers.append("stale_or_archive")
    if (content_item.score or 0) <= 0:
        blockers.append("non_positive_score")
    if not content_item.classification_metadata:
        blockers.append("missing_classification_metadata")
    if content_item.duplicate_of_id:
        blockers.append(DUPLICATE_FRAGMENT)
    if content_type == "tutorial" and rewrite_bucket != "daily_news":
        blockers.append("not_daily_news")

    blockers = list(dict.fromkeys(blockers))
    blocking = [blocker for blocker in blockers if blocker != "not_daily_news"]
    return RewriteReadiness(
        is_ready=not blocking,
        reason="ready" if not blocking else ", ".join(blocking),
        blockers=blockers,
    )
