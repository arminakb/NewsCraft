from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.validation.report import (
    DEFAULT_REPORT_PATH,
    build_content_intelligence_report,
    write_content_intelligence_report,
)

CHECKED_AT = datetime(2026, 7, 6, tzinfo=UTC)


def test_validation_report_includes_required_sections_and_summaries():
    report = build_content_intelligence_report(
        sources=[
            _source("Healthy RSS", "healthy", parse_count=3, suitable_count=2, media_count=4),
            _source("Broken RSS", "broken", error_type="http_403", error_message="HTTP 403"),
            _source("Disabled RSS", "disabled", active=False, error_message="manual disable"),
        ],
        content_items=[
            _item("Fresh AI news", "news", "daily_news", score=91, primary_image_id=uuid4()),
            _item("Vector tutorial", "tutorial", "tutorial", score=80, score_breakdown={"final_score": 80}),
            _item("Research paper", "research", "research", score=78),
            _item("Vendor launch", "vendor_update", "vendor_update", score=70),
            _item("Long analysis", "longform", "longform_analysis", score=65),
            _item("Discount tool", "promo", "promo_review", quality_status="blocked", score=10),
            _item(
                "Parser problem",
                "low_signal",
                "low_signal_review",
                quality_status="low_signal",
                score=1,
                is_ready=False,
            ),
            _item(
                "Old archive",
                "news",
                "daily_news",
                score=5,
                freshness_bucket="archive",
                score_breakdown={"archive_penalty": 18, "final_score": 5},
            ),
            _item("Duplicate story", "news", "daily_news", duplicate=True),
        ],
        media_assets=[
            _media("image", "good", is_primary=True),
            _media("image", "tracking"),
            _media("video", "good"),
        ],
        rewrite_candidates=[
            _candidate("daily_news", "pending", 91),
            _candidate("promo_review", "excluded", 10),
            _candidate("low_signal_review", "blocked", 1),
        ],
    )

    for section in [
        "Source Health Summary",
        "Content Type Distribution",
        "Rewrite Bucket Summary",
        "Top Daily News Candidates",
        "Top Technical Articles",
        "Top Tutorials",
        "Top Research Items",
        "Top Videos",
        "Vendor Updates",
        "Longform / Deep Analysis",
        "Promo / Excluded Items",
        "Low Signal / Parser Problems",
        "Media Quality Summary",
        "Scoring Warnings",
        "Final Recommendations",
    ]:
        assert f"## {section}" in report

    assert "- Total sources: 3" in report
    assert "- healthy: 1" in report
    assert "- broken: 1" in report
    assert "- disabled: 1" in report
    assert "- unknown: 0" in report
    assert "| Healthy RSS | healthy | 3 | 2 | 4 |" in report
    assert "| news | 3 |" in report
    assert "| daily_news | 3 |" in report
    assert "- Primary media coverage: 1/9" in report
    assert "- Promo count: 1" in report
    assert "- Low-signal count: 1" in report
    assert "- Duplicate count: 1" in report
    assert "Discount tool" in report
    assert "Parser problem" in report
    assert "Old archive" in report
    assert "archive_penalty=18" in report


def test_validation_report_marks_never_checked_sources_unknown():
    report = build_content_intelligence_report(
        sources=[_source("Never Checked", "healthy", last_fetch_at=None)],
        content_items=[],
        media_assets=[],
    )

    assert "- unknown: 1" in report
    assert "| Never Checked | unknown | 0 | 0 | 0 | not checked yet |" in report


def test_validation_report_writes_to_predictable_path(tmp_path):
    output_path = tmp_path / DEFAULT_REPORT_PATH

    written = write_content_intelligence_report(output_path, sources=[], content_items=[], media_assets=[])

    assert written == output_path
    assert output_path.exists()
    assert "# NewsCraft Content Intelligence Validation Report" in output_path.read_text(encoding="utf-8")


def _source(
    name: str,
    health_status: str,
    *,
    active: bool = True,
    parse_count: int = 0,
    suitable_count: int = 0,
    media_count: int = 0,
    error_type: str | None = None,
    error_message: str | None = None,
    last_fetch_at: datetime | None = CHECKED_AT,
):
    return SimpleNamespace(
        name=name,
        health_status=health_status,
        active=active,
        last_parse_count=parse_count,
        last_suitable_count=suitable_count,
        last_media_count=media_count,
        last_error_type=error_type,
        last_error_message=error_message,
        disabled_reason=None if active else error_message,
        last_fetch_at=last_fetch_at,
    )


def _item(
    title: str,
    content_type: str,
    rewrite_bucket: str,
    *,
    score: int = 25,
    quality_status: str = "good",
    freshness_bucket: str = "fresh",
    score_breakdown: dict | None = None,
    primary_image_id=None,
    is_ready: bool = True,
    duplicate: bool = False,
):
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        content_type=content_type,
        rewrite_bucket=rewrite_bucket,
        score=score,
        quality_status=quality_status,
        freshness_bucket=freshness_bucket,
        score_breakdown=score_breakdown or {"final_score": score},
        primary_image_id=primary_image_id,
        is_rewrite_ready=is_ready,
        rewrite_ready_reason="ready" if is_ready else "blocked",
        duplicate_of_id=uuid4() if duplicate else None,
    )


def _media(kind: str, quality: str, *, is_primary: bool = False):
    return SimpleNamespace(kind=kind, media_quality=quality, is_primary=is_primary)


def _candidate(bucket: str, status: str, priority_score: int):
    return SimpleNamespace(bucket_type=bucket, status=status, priority_score=priority_score)
