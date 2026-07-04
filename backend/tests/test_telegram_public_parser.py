from pathlib import Path

from app.sources.telegram_public import parse_public_telegram_page


def test_public_telegram_parser_extracts_posts_and_images():
    html = Path("tests/fixtures/telegram_public_sample.html").read_text(encoding="utf-8")

    parsed = parse_public_telegram_page(html, channel="iran_jahan_darlahze")

    assert parsed.items
    first = parsed.items[0]
    assert first.external_id_norm.startswith("iran_jahan_darlahze/")
    assert first.source_url_norm.startswith("https://t.me/iran_jahan_darlahze/")
    assert first.content_text
    assert "views" in first.parser_meta
    assert first.media_candidates
    assert first.media_candidates[0].kind == "image"
    assert all(candidate.source_field != "channel_avatar" for candidate in first.media_candidates)
