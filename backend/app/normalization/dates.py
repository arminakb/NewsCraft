from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from dateutil import parser


def parse_source_datetime(value: str, default_timezone: str = "UTC") -> tuple[datetime, str]:
    parsed = parser.parse(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(default_timezone))
        status = "assumed_timezone"
    else:
        status = "parsed"
    return parsed.astimezone(UTC), status


def normalize_source_datetime(
    value: str | None,
    default_timezone: str = "UTC",
) -> tuple[datetime | None, str]:
    if not value or not value.strip():
        return None, "missing"
    try:
        return parse_source_datetime(value, default_timezone=default_timezone)
    except TypeError, ValueError, OverflowError:
        return None, "failed"
