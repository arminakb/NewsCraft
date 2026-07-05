from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RewriteBucketAssignment:
    bucket_type: str
    status: str
    reason: str


def assign_rewrite_bucket(content_type: str, source_domain: str = "", source_name: str = "") -> RewriteBucketAssignment:
    normalized_type = (content_type or "low_signal").casefold()
    source_text = f"{source_domain} {source_name}".casefold()
    if normalized_type == "tool_update":
        bucket_type = "vendor_update" if _is_vendor_source(source_text) else "daily_news"
    else:
        bucket_type = {
            "news": "daily_news",
            "article": "technical_article",
            "tutorial": "tutorial",
            "research": "research",
            "video": "video",
            "vendor_update": "vendor_update",
            "longform": "longform_analysis",
            "promo": "promo_review",
            "low_signal": "low_signal_review",
        }.get(normalized_type, "low_signal_review")
    status = "excluded" if normalized_type in {"promo", "low_signal"} else "pending"
    return RewriteBucketAssignment(
        bucket_type=bucket_type,
        status=status,
        reason=f"{normalized_type} -> {bucket_type}",
    )


def _is_vendor_source(source_text: str) -> bool:
    return any(value in source_text for value in ("openai", "deepmind", "google", "microsoft", "amazon", "aws"))
