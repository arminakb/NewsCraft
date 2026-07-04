from datetime import UTC
from pathlib import Path
from unittest.mock import Mock, patch

from newscraft.connectors.public import fetch_public_rss_sources
from newscraft.ingestion.normalization import content_hash, fingerprint_text, infer_direction, normalize_url, parse_source_datetime, title_date_fingerprint
from newscraft.ingestion.rss_public import parse_rss_feed, parsed_rss_items_to_articles
from newscraft.ingestion.seed_sources import SEED_SOURCES
from newscraft.ingestion.telegram_public import parse_public_telegram_page, parsed_telegram_items_to_articles


def test_normalization_helpers_match_public_ingestion_needs():
    assert normalize_url("HTTPS://Example.com/a?utm_source=x&b=2&a=1#frag") == "https://example.com/a?a=1&b=2"
    assert fingerprint_text("علي كاظمي") == fingerprint_text("علی کاظمی")
    assert infer_direction("خبر فوری درباره اقتصاد ایران") == "rtl"

    parsed, status = parse_source_datetime("10 May 2026 14:39:34", default_timezone="Asia/Tehran")

    assert parsed.tzinfo == UTC
    assert status == "assumed_timezone"
    assert content_hash("Hello   World") == content_hash("hello world")
    assert title_date_fingerprint("AI News", "2026-07-03") == title_date_fingerprint("ai news", "2026-07-03")


def test_rss_parser_extracts_media_and_normalizes_to_article():
    xml = Path("tests/fixtures/rss_google_ai.xml").read_text(encoding="utf-8")

    parsed = parse_rss_feed(xml, source_name="Google AI Blog", source_url="https://blog.google/technology/ai/rss/")
    articles = parsed_rss_items_to_articles(parsed)

    first = parsed.items[0]
    assert first.title
    assert first.external_id_norm
    assert first.media_candidates[0].kind == "image"
    assert articles[0]["connector"] == "rss_public"
    assert articles[0]["metadata"]["media_candidates"][0]["kind"] == "image"


def test_public_telegram_parser_extracts_posts_and_images():
    html = Path("tests/fixtures/telegram_public_sample.html").read_text(encoding="utf-8")

    parsed = parse_public_telegram_page(html, channel="iran_jahan_darlahze")
    articles = parsed_telegram_items_to_articles(parsed)

    first = parsed.items[0]
    assert first.external_id_norm.startswith("iran_jahan_darlahze/")
    assert first.source_url_norm.startswith("https://t.me/iran_jahan_darlahze/")
    assert first.media_candidates[0].kind == "image"
    assert "views" in first.parser_meta
    assert articles[0]["connector"] == "telegram_public"
    assert all(candidate.source_field != "channel_avatar" for candidate in first.media_candidates)


def test_seed_catalog_has_expected_groups_and_languages():
    assert len(SEED_SOURCES) == 50
    assert all(source["enabled"] for source in SEED_SOURCES)
    assert {source["language"] for source in SEED_SOURCES} >= {"en", "fa"}
    assert {"ai", "tech", "economy", "farsi_news", "farsi_economy", "farsi_tech"}.issubset(
        {source["category"] for source in SEED_SOURCES}
    )


def test_public_rss_fetcher_uses_seed_source_shape():
    xml = Path("tests/fixtures/rss_google_ai.xml").read_text(encoding="utf-8")
    response = Mock(text=xml)
    response.raise_for_status.return_value = None

    with patch("newscraft.connectors.public.requests.get", return_value=response) as get:
        articles = fetch_public_rss_sources(
            sources=[{"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/", "config": {}}],
            limit_per_source=1,
        )

    get.assert_called_once_with("https://blog.google/technology/ai/rss/", timeout=15)
    assert articles[0]["connector"] == "rss_public"
    assert articles[0]["source"] == "Google AI Blog"
