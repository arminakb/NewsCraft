from datetime import UTC

from app.normalization.dates import parse_source_datetime
from app.normalization.fingerprints import content_hash, title_date_fingerprint
from app.normalization.text import fingerprint_text, infer_direction
from app.normalization.urls import normalize_url


def test_normalize_url_removes_tracking_and_fragment():
    assert normalize_url("HTTPS://Example.com/a?utm_source=x&b=2&a=1#frag") == "https://example.com/a?a=1&b=2"


def test_persian_fingerprint_normalizes_arabic_variants():
    assert fingerprint_text("علي كاظمي") == fingerprint_text("علی کاظمی")
    assert infer_direction("خبر فوری درباره اقتصاد ایران") == "rtl"


def test_parse_source_datetime_uses_default_timezone():
    parsed, status = parse_source_datetime("10 May 2026 14:39:34", default_timezone="Asia/Tehran")

    assert parsed.tzinfo == UTC
    assert status == "assumed_timezone"


def test_hashes_are_stable():
    assert content_hash("Hello   World") == content_hash("hello world")
    assert title_date_fingerprint("AI News", "2026-07-03") == title_date_fingerprint("ai news", "2026-07-03")
