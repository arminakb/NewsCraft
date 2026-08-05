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
    assert first.parser_meta["content_origin"] == "source_provided"
    assert "views" in first.parser_meta
    assert first.media_candidates
    assert first.media_candidates[0].kind == "image"
    assert all(candidate.source_field != "channel_avatar" for candidate in first.media_candidates)


def test_public_telegram_parser_keeps_album_ids_media_and_entities_ordered():
    html = Path("tests/fixtures/telegram_public_album.html").read_text(encoding="utf-8")

    parsed = parse_public_telegram_page(html, channel="example_channel")

    assert [item.parser_meta["message_id"] for item in parsed.items] == [41, 44]
    album = parsed.items[1]
    assert album.parser_meta["message_ids"] == [42, 43, 44]
    assert album.parser_meta["grouped_id"] == "album-900"
    assert [candidate.source_field for candidate in album.media_candidates] == [
        "message_photo",
        "message_video",
        "message_document",
    ]
    assert album.parser_meta["entities"] == [
        {"type": "link", "text": "Source", "url": "https://example.com/story"},
        {"type": "bold", "text": "Album caption"},
    ]
