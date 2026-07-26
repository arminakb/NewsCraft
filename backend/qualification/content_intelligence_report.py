from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContentItem, MediaAsset, RewriteCandidate, Source

DEFAULT_REPORT_PATH = Path("validation/content-intelligence-report.md")
SOURCE_HEALTH_STATUSES = ("healthy", "degraded", "broken", "disabled", "unknown")
BUCKET_SECTIONS = {
    "daily_news": "Top Daily News Candidates",
    "technical_article": "Top Technical Articles",
    "tutorial": "Top Tutorials",
    "research": "Top Research Items",
    "video": "Top Videos",
    "vendor_update": "Vendor Updates",
    "longform_analysis": "Longform / Deep Analysis",
}


async def generate_content_intelligence_report(
    session: AsyncSession,
    output_path: str | Path = DEFAULT_REPORT_PATH,
) -> Path:
    sources = list(await session.scalars(select(Source).order_by(Source.name)))
    content_items = list(await session.scalars(select(ContentItem).order_by(ContentItem.score.desc())))
    media_assets = list(await session.scalars(select(MediaAsset)))
    rewrite_candidates = list(await session.scalars(select(RewriteCandidate)))
    return write_content_intelligence_report(
        output_path,
        sources=sources,
        content_items=content_items,
        media_assets=media_assets,
        rewrite_candidates=rewrite_candidates,
    )


def write_content_intelligence_report(
    output_path: str | Path = DEFAULT_REPORT_PATH,
    *,
    sources: list[Any],
    content_items: list[Any],
    media_assets: list[Any],
    rewrite_candidates: list[Any] | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = build_content_intelligence_report(
        sources=sources,
        content_items=content_items,
        media_assets=media_assets,
        rewrite_candidates=rewrite_candidates or [],
    )
    path.write_text(report, encoding="utf-8")
    return path


def build_content_intelligence_report(
    *,
    sources: list[Any],
    content_items: list[Any],
    media_assets: list[Any],
    rewrite_candidates: list[Any] | None = None,
) -> str:
    rewrite_candidates = rewrite_candidates or []
    lines = ["# NewsCraft Content Intelligence Validation Report", ""]
    lines.extend(_source_health_section(sources))
    lines.extend(_content_type_section(content_items))
    lines.extend(_rewrite_bucket_section(content_items, rewrite_candidates))
    for bucket, heading in BUCKET_SECTIONS.items():
        lines.extend(_top_bucket_section(heading, bucket, content_items))
    lines.extend(_promo_section(content_items, rewrite_candidates))
    lines.extend(_low_signal_section(content_items, rewrite_candidates))
    lines.extend(_media_section(content_items, media_assets))
    lines.extend(_scoring_warnings_section(content_items))
    lines.extend(_recommendations_section(sources, content_items, rewrite_candidates))
    return "\n".join(lines).rstrip() + "\n"


def _source_health_section(sources: list[Any]) -> list[str]:
    counts = Counter(_source_status(source) for source in sources)
    lines = [
        "## Source Health Summary",
        "",
        f"- Total sources: {len(sources)}",
    ]
    for status in SOURCE_HEALTH_STATUSES:
        lines.append(f"- {status}: {counts[status]}")
    lines.extend(["", "| Source | Health | Parsed | Suitable | Media | Issue |", "|---|---:|---:|---:|---:|---|"])
    for source in sources:
        issue = _source_issue(source)
        lines.append(
            f"| {_cell(_get(source, 'name', 'unknown'))} | {_source_status(source)} | "
            f"{_get(source, 'last_parse_count', 0)} | {_get(source, 'last_suitable_count', 0)} | "
            f"{_get(source, 'last_media_count', 0)} | {_cell(issue)} |"
        )
    return lines + [""]


def _content_type_section(content_items: list[Any]) -> list[str]:
    counts = Counter(_get(item, "content_type", "unknown") for item in content_items)
    return ["## Content Type Distribution", "", *_table(counts), ""]


def _rewrite_bucket_section(content_items: list[Any], rewrite_candidates: list[Any]) -> list[str]:
    counts = Counter(_get(item, "rewrite_bucket", "unknown") for item in content_items)
    candidate_counts = Counter(_get(candidate, "status", "unknown") for candidate in rewrite_candidates)
    lines = ["## Rewrite Bucket Summary", "", *_table(counts), ""]
    if rewrite_candidates:
        lines.extend(["Candidate status:", ""])
        lines.extend(_table(candidate_counts))
        lines.append("")
    return lines


def _top_bucket_section(heading: str, bucket: str, content_items: list[Any]) -> list[str]:
    rows = sorted(
        [item for item in content_items if _get(item, "rewrite_bucket") == bucket],
        key=lambda item: int(_get(item, "score", 0) or 0),
        reverse=True,
    )[:5]
    lines = [f"## {heading}", "", "| Title | Score | Ready | Reason |", "|---|---:|---:|---|"]
    for item in rows:
        lines.append(
            f"| {_cell(_get(item, 'title', 'untitled'))} | {_get(item, 'score', 0)} | "
            f"{_get(item, 'is_rewrite_ready', False)} | {_cell(_get(item, 'rewrite_ready_reason', ''))} |"
        )
    if not rows:
        lines.append("| None | 0 | False | No candidates |")
    return lines + [""]


def _promo_section(content_items: list[Any], rewrite_candidates: list[Any]) -> list[str]:
    promos = [item for item in content_items if _get(item, "content_type") == "promo"]
    excluded = [candidate for candidate in rewrite_candidates if _get(candidate, "status") == "excluded"]
    lines = [
        "## Promo / Excluded Items",
        "",
        f"- Promo count: {len(promos)}",
        f"- Excluded candidates: {len(excluded)}",
    ]
    lines.extend(["", "| Title | Bucket | Score |", "|---|---|---:|"])
    for item in promos[:10]:
        lines.append(
            f"| {_cell(_get(item, 'title', 'untitled'))} | {_get(item, 'rewrite_bucket', '')} | "
            f"{_get(item, 'score', 0)} |"
        )
    return lines + [""]


def _low_signal_section(content_items: list[Any], rewrite_candidates: list[Any]) -> list[str]:
    lows = [
        item
        for item in content_items
        if _get(item, "content_type") == "low_signal" or _get(item, "quality_status") == "low_signal"
    ]
    blocked = [candidate for candidate in rewrite_candidates if _get(candidate, "status") == "blocked"]
    lines = [
        "## Low Signal / Parser Problems",
        "",
        f"- Low-signal count: {len(lows)}",
        f"- Blocked candidates: {len(blocked)}",
        "",
        "| Title | Quality | Reason |",
        "|---|---|---|",
    ]
    for item in lows[:10]:
        lines.append(
            f"| {_cell(_get(item, 'title', 'untitled'))} | {_get(item, 'quality_status', '')} | "
            f"{_cell(_get(item, 'rewrite_ready_reason', ''))} |"
        )
    return lines + [""]


def _media_section(content_items: list[Any], media_assets: list[Any]) -> list[str]:
    kind_counts = Counter(_get(media, "kind", "unknown") for media in media_assets)
    quality_counts = Counter(_get(media, "media_quality", "unknown") for media in media_assets)
    primary_count = sum(1 for item in content_items if _get(item, "primary_image_id") is not None)
    lines = [
        "## Media Quality Summary",
        "",
        f"- Total media assets: {len(media_assets)}",
        f"- Primary media coverage: {primary_count}/{len(content_items)}",
        "",
        "By type:",
        "",
        *_table(kind_counts),
        "",
        "By quality:",
        "",
        *_table(quality_counts),
        "",
    ]
    return lines


def _scoring_warnings_section(content_items: list[Any]) -> list[str]:
    stale_or_archive = [
        item
        for item in content_items
        if _get(item, "freshness_bucket") in {"stale", "archive"} or _breakdown_value(item, "archive_penalty") > 0
    ]
    duplicates = [item for item in content_items if _get(item, "duplicate_of_id") is not None]
    lines = [
        "## Scoring Warnings",
        "",
        f"- Stale/archive penalized items: {len(stale_or_archive)}",
        f"- Duplicate count: {len(duplicates)}",
        "",
        "| Title | Freshness | Score warnings |",
        "|---|---|---|",
    ]
    for item in stale_or_archive[:10]:
        lines.append(
            f"| {_cell(_get(item, 'title', 'untitled'))} | {_get(item, 'freshness_bucket', '')} | "
            f"{_cell(_score_warning_text(item))} |"
        )
    return lines + [""]


def _recommendations_section(
    sources: list[Any],
    content_items: list[Any],
    rewrite_candidates: list[Any],
) -> list[str]:
    broken_sources = sum(1 for source in sources if _source_status(source) == "broken")
    ready_items = sum(1 for item in content_items if _get(item, "is_rewrite_ready") is True)
    excluded = sum(1 for candidate in rewrite_candidates if _get(candidate, "status") == "excluded")
    return [
        "## Final Recommendations",
        "",
        f"- Review broken sources: {broken_sources}",
        f"- Ready rewrite candidates: {ready_items}",
        f"- Excluded candidates to audit: {excluded}",
        "- Re-run ingestion and regenerate this report after source fixes.",
        "",
    ]


def _table(counts: Counter) -> list[str]:
    lines = ["| Value | Count |", "|---|---:|"]
    if not counts:
        return lines + ["| None | 0 |"]
    for value, count in sorted(counts.items(), key=lambda row: (-row[1], str(row[0]))):
        lines.append(f"| {_cell(value)} | {count} |")
    return lines


def _source_status(source: Any) -> str:
    if not _get(source, "active", True):
        return "disabled"
    if _get(source, "disabled_reason"):
        return "disabled"
    status = _get(source, "health_status", "unknown") or "unknown"
    if status == "healthy" and not _has_health_history(source):
        return "unknown"
    if status not in SOURCE_HEALTH_STATUSES:
        return "degraded"
    return status


def _source_issue(source: Any) -> str:
    if _source_status(source) == "unknown":
        return "not checked yet"
    return (
        _get(source, "disabled_reason") or _get(source, "last_error_type") or _get(source, "last_error_message") or ""
    )


def _has_health_history(source: Any) -> bool:
    if any(
        _get(source, field) is not None
        for field in ("last_fetch_at", "last_success_at", "last_failure_at", "last_http_status")
    ):
        return True
    return any(
        int(_get(source, field, 0) or 0) > 0
        for field in ("last_parse_count", "last_suitable_count", "last_media_count", "failure_count")
    )


def _score_warning_text(item: Any) -> str:
    warnings = []
    for key in ("stale_penalty", "archive_penalty", "low_signal_penalty", "promotional_penalty"):
        value = _breakdown_value(item, key)
        if value:
            warnings.append(f"{key}={value}")
    return ", ".join(warnings) or "none"


def _breakdown_value(item: Any, key: str) -> int:
    breakdown = _get(item, "score_breakdown", {}) or {}
    try:
        return int(breakdown.get(key) or 0)
    except TypeError, ValueError:
        return 0


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|")


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)
