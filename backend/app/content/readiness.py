from __future__ import annotations

from dataclasses import dataclass

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

    if not (content_item.title or "").strip():
        blockers.append("missing_title")
    if not content_item.canonical_url:
        blockers.append("missing_source_url")
    if len((content_item.content_text or "").strip()) < 40:
        blockers.append("not_enough_text")
    if content_type in {"promo", "low_signal"}:
        blockers.append(content_type)
    if content_type == "longform" and rewrite_bucket != "longform_analysis":
        blockers.append("wrong_longform_bucket")
    if content_type != "longform" and content_item.freshness_bucket in {"stale", "archive"}:
        blockers.append("stale_or_archive")
    if (content_item.score or 0) <= 0:
        blockers.append("non_positive_score")
    if not content_item.classification_metadata:
        blockers.append("missing_classification_metadata")
    if content_item.duplicate_of_id:
        blockers.append("duplicate")
    if content_type == "tutorial" and rewrite_bucket != "daily_news":
        blockers.append("not_daily_news")

    blocking = [blocker for blocker in blockers if blocker != "not_daily_news"]
    return RewriteReadiness(
        is_ready=not blocking,
        reason="ready" if not blocking else ", ".join(blocking),
        blockers=blockers,
    )
