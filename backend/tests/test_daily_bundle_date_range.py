from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.daily_bundle.date_range import default_yesterday, parse_date_range


def test_parse_date_range_returns_timezone_aware_midnights():
    start, end = parse_date_range("2026-07-05", "2026-07-06", "Asia/Tehran")

    assert start == datetime(2026, 7, 5, tzinfo=ZoneInfo("Asia/Tehran"))
    assert end == datetime(2026, 7, 6, tzinfo=ZoneInfo("Asia/Tehran"))


def test_default_yesterday_uses_local_timezone_midnights():
    now = datetime(2026, 7, 6, 10, tzinfo=ZoneInfo("Asia/Tehran"))

    start, end = default_yesterday("Asia/Tehran", now=now)

    assert start == datetime(2026, 7, 5, tzinfo=ZoneInfo("Asia/Tehran"))
    assert end == datetime(2026, 7, 6, tzinfo=ZoneInfo("Asia/Tehran"))


def test_parse_date_range_rejects_start_after_end():
    with pytest.raises(ValueError, match="start must be before end"):
        parse_date_range("2026-07-06", "2026-07-05", "Asia/Tehran")
