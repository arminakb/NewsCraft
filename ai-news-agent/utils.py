"""Date helpers for article collection and filtering."""

from datetime import date, datetime, timezone
from time import struct_time

from dateutil import parser as date_parser


def parse_article_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, struct_time) or (isinstance(value, tuple) and len(value) >= 6):
        return datetime(*value[:6])
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        parsed = date_parser.parse(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed.replace(tzinfo=None)


def is_within_date_range(date_value, start_date=None, end_date=None):
    parsed = parse_article_date(date_value)
    if parsed is None:
        return start_date is None and end_date is None
    article_date = parsed.date()
    if start_date and article_date < parse_article_date(start_date).date():
        return False
    if end_date and article_date > parse_article_date(end_date).date():
        return False
    return True


def normalize_date_for_storage(date_value):
    parsed = parse_article_date(date_value)
    return parsed.isoformat(timespec="seconds") if parsed else ""
