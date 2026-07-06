from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def parse_date_range(start: str, end: str, timezone_name: str) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    start_at = datetime.combine(datetime.fromisoformat(start).date(), time.min, timezone)
    end_at = datetime.combine(datetime.fromisoformat(end).date(), time.min, timezone)
    if start_at >= end_at:
        raise ValueError("start must be before end")
    return start_at, end_at


def default_yesterday(timezone_name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    local_now = now.astimezone(timezone) if now else datetime.now(timezone)
    end_at = datetime.combine(local_now.date(), time.min, timezone)
    start_at = end_at - timedelta(days=1)
    return start_at, end_at
