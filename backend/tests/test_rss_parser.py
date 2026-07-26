from pathlib import Path

from app.sources.rss import parse_rss_feed


def test_rss_parser_extracts_items_and_media():
    xml = Path("tests/fixtures/rss_google_ai.xml").read_text(encoding="utf-8")

    parsed = parse_rss_feed(
        xml,
        source_name="Google AI Blog",
        source_url="https://blog.google/technology/ai/rss/",
        default_timezone="UTC",
    )

    assert parsed.items
    first = parsed.items[0]
    assert first.title
    assert first.external_id_norm
    assert first.source_url_norm.startswith("https://")
    assert first.media_candidates
    assert first.media_candidates[0].kind == "image"


def test_rss_parser_keeps_missing_title_explicit_and_normalizes_fallback_identity():
    parsed = parse_rss_feed(
        """\
        <rss version="2.0"><channel><title>Example</title>
          <item>
            <description>A substantive source update with enough detail for a generated title.</description>
            <pubDate>10 May 2026 14:39:34</pubDate>
          </item>
        </channel></rss>
        """,
        source_name="Example",
        source_url="https://example.test/feed",
        default_timezone="Asia/Tehran",
    )

    item = parsed.items[0]
    assert item.title == ""
    assert item.external_id_norm
    assert item.date_parse_status == "assumed_timezone"
    assert "missing_title" in parsed.warnings


def test_rss_parser_reports_malformed_date_without_parser_fallback():
    parsed = parse_rss_feed(
        """\
        <rss version="2.0"><channel><title>Example</title>
          <item><title>Update</title><description>Body</description><pubDate>not-a-date</pubDate></item>
        </channel></rss>
        """,
        source_name="Example",
        source_url="https://example.test/feed",
    )

    item = parsed.items[0]
    assert item.published_at is None
    assert item.date_parse_status == "failed"
