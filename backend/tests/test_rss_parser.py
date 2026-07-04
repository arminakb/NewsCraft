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
