import re
import unicodedata
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from dateutil import parser

TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "cmpid", "ref"}
IMAGE_EXTENSIONS = (".apng", ".avif", ".gif", ".jpg", ".jpeg", ".png", ".webp")
VIDEO_EXTENSIONS = (".m4v", ".mov", ".mp4", ".webm")
AUDIO_EXTENSIONS = (".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav")
DOCUMENT_EXTENSIONS = (".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx")
RTL_RANGES = ((0x0590, 0x08FF), (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF))
DIACRITIC_CATEGORIES = {"Mn", "Me"}
WHITESPACE_RE = re.compile(r"\s+")
ARABIC_VARIANTS = str.maketrans({"ك": "ک", "ي": "ی", "ى": "ی", "ئ": "ی", "ة": "ه", "ۀ": "ه", "ؤ": "و", "أ": "ا", "إ": "ا", "آ": "ا"})


def normalize_url(url: str, base_url: str | None = None) -> str:
    absolute = urljoin(base_url, url.strip()) if base_url else url.strip()
    parts = urlsplit(absolute)
    scheme = parts.scheme.lower() or "https"
    host = parts.netloc.lower()
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in TRACKING_PARAMS or any(lowered.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items))
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((scheme, host, path, query, ""))


def hash_value(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def fingerprint_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(ARABIC_VARIANTS)
    without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) not in DIACRITIC_CATEGORIES)
    return WHITESPACE_RE.sub(" ", without_marks.casefold()).strip()


def content_hash(value: str) -> str:
    return hash_value(fingerprint_text(value))


def title_date_fingerprint(title: str, date_key: str) -> str:
    return hash_value(fingerprint_text(f"{title} {date_key}"))


def infer_direction(value: str) -> str:
    rtl_count = 0
    ltr_count = 0
    for ch in value:
        codepoint = ord(ch)
        if any(start <= codepoint <= end for start, end in RTL_RANGES):
            rtl_count += 1
        elif "a" <= ch.lower() <= "z":
            ltr_count += 1
    return "rtl" if rtl_count > ltr_count else "ltr"


def parse_source_datetime(value: str, default_timezone: str = "UTC") -> tuple[datetime, str]:
    parsed = parser.parse(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(default_timezone))
        status = "assumed_timezone"
    else:
        status = "parsed"
    return parsed.astimezone(UTC), status


def is_http_media_url(url: str) -> bool:
    return urlsplit(url).scheme.lower() in {"http", "https"}


def infer_media_kind(url: str, mime_type: str | None = None, medium: str | None = None) -> str:
    normalized_medium = (medium or "").lower()
    normalized_mime = (mime_type or "").lower()
    path = urlsplit(url).path.lower()
    if normalized_medium == "image" or normalized_mime.startswith("image/") or path.endswith(IMAGE_EXTENSIONS):
        return "image"
    if normalized_medium == "video" or normalized_mime.startswith("video/") or path.endswith(VIDEO_EXTENSIONS):
        return "video"
    if normalized_medium == "audio" or normalized_mime.startswith("audio/") or path.endswith(AUDIO_EXTENSIONS):
        return "audio"
    if normalized_mime in {"application/pdf"} or path.endswith(DOCUMENT_EXTENSIONS):
        return "document"
    return "document"


def parse_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except ValueError:
        return None
