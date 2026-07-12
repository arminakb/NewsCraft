from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.automations.telegram.route_policy import (
    ContentFilterDecision,
    evaluate_content_filter,
    next_allowed_at,
    retry_at,
)

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)


def test_content_filter_normalizes_text_and_exclusion_wins():
    decision = evaluate_content_filter(
        text="  خبر فوری درباره اقتصاد  ",
        has_media=True,
        policy={
            "include_terms": ["اقتصاد"],
            "exclude_terms": ["خبر فوری"],
            "min_text_characters": 1,
            "require_media": False,
        },
    )
    assert decision == ContentFilterDecision(accepted=False, reason="excluded_term:خبر فوری")


def test_content_filter_applies_nfkc_casefold_whitespace_length_include_and_media_rules():
    assert evaluate_content_filter(
        text="  ＡI\n  NEWS  ",
        has_media=True,
        policy={"include_terms": ["ai news"], "exclude_terms": [], "min_text_characters": 7},
    ).accepted
    assert evaluate_content_filter(
        text="ordinary text", has_media=True, policy={"include_terms": ["required"]}
    ).reason == "missing_included_term"
    assert evaluate_content_filter(
        text=" a   b ", has_media=True, policy={"min_text_characters": 4}
    ).reason == "text_too_short"
    assert evaluate_content_filter(
        text="long enough", has_media=False, policy={"require_media": True}
    ).reason == "media_required"
    assert evaluate_content_filter(text="anything", has_media=False, policy={}).accepted


def test_overnight_quiet_hours_returns_first_allowed_instant():
    now = datetime(2026, 7, 11, 21, 30, tzinfo=ZoneInfo("Asia/Tehran"))
    assert next_allowed_at(
        now, {"timezone": "Asia/Tehran", "start": "21:00", "end": "07:00"}
    ) == datetime(2026, 7, 12, 7, 0, tzinfo=ZoneInfo("Asia/Tehran"))


def test_quiet_hours_are_start_inclusive_end_exclusive_and_reject_empty_window():
    policy = {"timezone": "Asia/Tehran", "start": "09:00", "end": "17:00"}
    zone = ZoneInfo("Asia/Tehran")
    start = datetime(2026, 7, 11, 9, 0, tzinfo=zone)
    end = datetime(2026, 7, 11, 17, 0, tzinfo=zone)
    before = datetime(2026, 7, 11, 8, 59, tzinfo=zone)

    assert next_allowed_at(start, policy) == end
    assert next_allowed_at(end, policy) == end
    assert next_allowed_at(before, policy) == before
    with pytest.raises(ValueError, match="identical"):
        next_allowed_at(start, {"timezone": "UTC", "start": "09:00", "end": "09:00"})


def test_retry_policy_uses_capped_exponential_larger_rate_limit_and_exhaustion():
    policy = {"max_attempts": 4, "base_delay_seconds": 30, "max_delay_seconds": 90}
    assert retry_at(policy, attempt_number=3, now=NOW, jitter_ratio=0) == NOW + timedelta(seconds=90)
    assert retry_at(
        policy,
        attempt_number=2,
        now=NOW,
        retry_after_seconds=120,
        jitter_ratio=0,
    ) == NOW + timedelta(seconds=120)
    assert retry_at(policy, attempt_number=4, now=NOW, jitter_ratio=0) is None
    assert retry_at(policy, attempt_number=2, now=NOW, jitter_ratio=10) == NOW + timedelta(
        seconds=75
    )
