from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ContentFilterDecision:
    accepted: bool
    reason: str | None = None


def _normalized(value: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).casefold()).strip()


def evaluate_content_filter(
    text: str,
    has_media: bool,
    policy: Mapping[str, Any],
) -> ContentFilterDecision:
    normalized_text = _normalized(text)
    excluded = [(str(term), _normalized(str(term))) for term in policy.get("exclude_terms", [])]
    included = [(str(term), _normalized(str(term))) for term in policy.get("include_terms", [])]
    for original, term in excluded:
        if term and term in normalized_text:
            return ContentFilterDecision(False, f"excluded_term:{original}")
    if included and not any(term and term in normalized_text for _, term in included):
        return ContentFilterDecision(False, "missing_included_term")
    if len(normalized_text) < int(policy.get("min_text_characters", 1)):
        return ContentFilterDecision(False, "text_too_short")
    if bool(policy.get("require_media", False)) and not has_media:
        return ContentFilterDecision(False, "media_required")
    return ContentFilterDecision(True)


def _clock(value: str) -> time:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        raise ValueError("quiet-hours time must use HH:MM") from None
    if parsed.strftime("%H:%M") != value:
        raise ValueError("quiet-hours time must use zero-padded HH:MM")
    return parsed.time()


def next_allowed_at(now: datetime, quiet_hours: Mapping[str, Any] | None) -> datetime:
    if not quiet_hours:
        return now
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    zone = ZoneInfo(str(quiet_hours.get("timezone", "Asia/Tehran")))
    start = _clock(str(quiet_hours["start"]))
    end = _clock(str(quiet_hours["end"]))
    if start == end:
        raise ValueError("quiet-hours start and end cannot be identical")
    local_now = now.astimezone(zone)
    local_time = local_now.timetz().replace(tzinfo=None)
    if start < end:
        inside = start <= local_time < end
        end_date = local_now.date()
    else:
        inside = local_time >= start or local_time < end
        end_date = local_now.date() + timedelta(days=1) if local_time >= start else local_now.date()
    if not inside:
        return now
    return datetime.combine(end_date, end, tzinfo=zone)


def retry_at(
    policy: Mapping[str, Any],
    *,
    attempt_number: int,
    now: datetime,
    retry_after_seconds: int | float | None = None,
    jitter_ratio: float | None = None,
) -> datetime | None:
    max_attempts = int(policy.get("max_attempts", 3))
    if attempt_number >= max_attempts:
        return None
    base = int(policy.get("base_delay_seconds", 30))
    maximum = int(policy.get("max_delay_seconds", 1800))
    delay = min(maximum, base * (2 ** max(0, attempt_number - 1)))
    if retry_after_seconds is not None:
        delay = max(delay, float(retry_after_seconds))
    adjustment = max(-0.25, min(0.25, float(jitter_ratio or 0)))
    return now + timedelta(seconds=delay * (1 + adjustment))
