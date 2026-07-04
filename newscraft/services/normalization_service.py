import html
import re
from datetime import date, datetime, timezone
from time import struct_time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dateutil import parser as date_parser

TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "igshid", "ref"}


def normalize_article(item):
    raw = dict(item or {})
    title = _clean_text(raw.get("title"))
    url = _canonical_url(raw.get("url"))
    if not title or not url:
        return None

    metadata = dict(raw.get("metadata") or {})
    metrics = raw.get("metrics")
    if metrics is not None:
        metadata["metrics"] = metrics
    tags = raw.get("tags") or raw.get("topics")
    if tags:
        metadata["tags"] = list(tags)
    metadata["canonical_url"] = url
    if raw.get("url") != url:
        metadata["original_url"] = raw.get("url")

    return {
        "title": title,
        "url": url,
        "external_id": _clean_text(raw.get("external_id")),
        "source": _clean_text(raw.get("source")) or "Unknown",
        "source_type": _clean_text(raw.get("source_type")),
        "connector": _clean_text(raw.get("connector") or raw.get("source_type")),
        "source_group": _clean_text(raw.get("source_group")),
        "author": _clean_text(raw.get("author")),
        "summary": _clean_text(raw.get("summary") or raw.get("description")),
        "content": _clean_text(raw.get("content") or raw.get("text")),
        "published_at": _parse_datetime(raw.get("published_at")),
        "collected_at": _parse_datetime(raw.get("collected_at")),
        "category": _clean_text(raw.get("category")),
        "score": raw.get("score") or 0,
        "status": _clean_text(raw.get("status")) or "new",
        "language": _clean_text(raw.get("language")).lower() if raw.get("language") else None,
        "metadata": metadata,
        "raw_data": raw,
    }


def _clean_text(value):
    if value is None:
        return None
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip() or None


def _canonical_url(value):
    text = _clean_text(value)
    if not text:
        return None
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return None
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "", "", urlencode(sorted(query)), ""))


def _parse_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, struct_time) or (isinstance(value, tuple) and len(value) >= 6):
        parsed = datetime(*value[:6])
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, timezone.utc)
    else:
        try:
            parsed = date_parser.parse(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
