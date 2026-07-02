"""Date helpers for article collection and filtering."""

import re
from datetime import date, datetime, timezone
from time import struct_time

from dateutil import parser as date_parser


def clean_token(value):
    if not value:
        return None
    value = str(value).strip()
    return value or None


def redact_sensitive_text(value):
    text = str(value or "")
    text = re.sub(r"(github_pat_|ghp_|hf_)[A-Za-z0-9_]+", "[redacted-token]", text)
    return re.sub(r"Bearer\s+[^'\"\s]+", "Bearer [redacted-token]", text)


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
    start = parse_article_date(start_date) if start_date else None
    end = parse_article_date(end_date) if end_date else None
    if isinstance(start_date, datetime) or isinstance(end_date, datetime):
        if start and parsed < start:
            return False
        if end and parsed > end:
            return False
        return True
    article_date = parsed.date()
    if start and article_date < start.date():
        return False
    if end and article_date > end.date():
        return False
    return True


def normalize_date_for_storage(date_value):
    parsed = parse_article_date(date_value)
    return parsed.isoformat(timespec="seconds") if parsed else ""


def humanize_time_ago(published_at, now=None):
    published = parse_article_date(published_at)
    if not published:
        return "Unknown publish time"
    now = parse_article_date(now) or datetime.now()
    seconds = int((now - published).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return "Published just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"Published {minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"Published {hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"Published {days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"Published {months} month{'s' if months != 1 else ''} ago"
    years = months // 12
    return f"Published {years} year{'s' if years != 1 else ''} ago"
