import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from newscraft.ingestion.normalization import infer_direction, infer_media_kind, is_http_media_url, normalize_url, parse_source_datetime
from newscraft.ingestion.parsed import MediaCandidate, ParsedSourceItem, ParsedSourcePayload
from newscraft.ingestion.rss_public import _parsed_item_to_article

CSS_URL_RE = re.compile(r"background-image:\s*url\((?P<quote>['\"]?)(?P<url>.*?)(?P=quote)\)")
COUNT_RE = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<suffix>[KMB])?", re.IGNORECASE)


def parse_public_telegram_page(html: str, channel: str) -> ParsedSourcePayload:
    soup = BeautifulSoup(html, "lxml")
    warnings = []
    items = [_parse_message(block, channel=channel, warnings=warnings) for block in soup.select(".tgme_widget_message[data-post]")]
    return ParsedSourcePayload(items=[item for item in items if item is not None], warnings=warnings, feed_meta={"channel": channel})


def parsed_telegram_items_to_articles(payload: ParsedSourcePayload) -> list[dict]:
    channel = payload.feed_meta.get("channel") or "telegram"
    return [_parsed_item_to_article(item, source_name=f"Telegram - {channel}", connector="telegram_public", source_type="telegram") for item in payload.items if item.title and item.source_url_norm]


def _parse_message(block: Tag, channel: str, warnings: list[str]) -> ParsedSourceItem | None:
    data_post = block.get("data-post")
    if not data_post or "/" not in data_post:
        warnings.append("missing_data_post")
        return None
    post_channel, message_id = data_post.split("/", 1)
    if post_channel != channel:
        return None
    text_node = block.select_one(".js-message_text")
    content_text = _node_text(text_node) if text_node else ""
    content_html = text_node.decode_contents() if text_node else None
    source_url = f"https://t.me/{data_post}"
    published_raw, published_at, date_parse_status = _message_datetime(block)
    views = parse_compact_count(_select_text(block, ".tgme_widget_message_views"))
    if not content_text:
        warnings.append(f"missing_text:{data_post}")
    if published_at is None:
        warnings.append(f"missing_date:{data_post}")
    return ParsedSourceItem(
        external_id_raw=data_post,
        external_id_norm=data_post,
        source_url=source_url,
        source_url_norm=normalize_url(source_url),
        canonical_url_candidate=normalize_url(source_url),
        title=_message_title(content_text, message_id),
        summary=content_text,
        content_html=content_html,
        content_text=content_text,
        author=_select_text(block, ".tgme_widget_message_owner_name"),
        categories=[],
        published_raw=published_raw,
        published_at=published_at,
        date_parse_status=date_parse_status,
        media_candidates=_extract_media_candidates(block),
        parser_meta={"channel": channel, "message_id": message_id, "views": views, "reactions": _extract_reactions(block), "direction": infer_direction(content_text)},
    )


def _message_title(content_text: str, message_id: str) -> str:
    for line in content_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:140]
    return f"Telegram post {message_id}"


def _message_datetime(block: Tag) -> tuple[str | None, datetime | None, str]:
    time_node = block.select_one("time[datetime]")
    if not time_node:
        return None, None, "missing"
    raw = time_node.get("datetime")
    if not raw:
        return None, None, "missing"
    try:
        parsed, status = parse_source_datetime(raw, default_timezone="UTC")
    except (TypeError, ValueError, OverflowError):
        return raw, None, "failed"
    return raw, parsed, status


def _extract_media_candidates(block: Tag) -> list[MediaCandidate]:
    candidates = []
    for photo in block.select(".tgme_widget_message_photo_wrap"):
        url = _background_image_url(photo)
        if url:
            _append_media(candidates, url, source_field="message_photo", kind="image")
    for video in block.select(".tgme_widget_message_video_wrap"):
        url = _background_image_url(video) or _first_attr(video, "video", "src")
        if url:
            _append_media(candidates, url, source_field="message_video", kind="video")
    for document in block.select(".tgme_widget_message_document_wrap, .tgme_widget_message_document"):
        url = document.get("href") or _first_attr(document, "a", "href")
        if url:
            _append_media(candidates, url, source_field="message_document", kind="document")
    for preview in block.select(".tgme_widget_message_link_preview"):
        url = _background_image_url(preview)
        if url:
            _append_media(candidates, url, source_field="link_preview_image", kind="image")
    return candidates


def _append_media(candidates: list[MediaCandidate], url: str, source_field: str, kind: str) -> None:
    normalized_url = normalize_url(url)
    if not is_http_media_url(normalized_url) or any(candidate.normalized_url == normalized_url for candidate in candidates):
        return
    candidates.append(MediaCandidate(original_url=url, normalized_url=normalized_url, kind=kind if kind else infer_media_kind(normalized_url), source_field=source_field))


def _background_image_url(node: Tag) -> str | None:
    style = node.get("style") or ""
    match = CSS_URL_RE.search(style)
    return match.group("url") if match else None


def _first_attr(node: Tag, selector: str, attr: str) -> str | None:
    child = node.select_one(selector)
    if not child:
        return None
    value = child.get(attr)
    return str(value) if value else None


def _select_text(block: Tag, selector: str) -> str | None:
    node = block.select_one(selector)
    if not node:
        return None
    text = _node_text(node)
    return text or None


def _node_text(node: Tag) -> str:
    return node.get_text("\n", strip=True)


def _extract_reactions(block: Tag) -> dict[str, int]:
    reactions = {}
    for reaction in block.select(".tgme_reaction"):
        text = reaction.get_text(" ", strip=True)
        match = COUNT_RE.search(text)
        if match:
            reactions[text[: match.start()].strip() or "reaction"] = parse_compact_count(match.group(0)) or 0
    return reactions


def parse_compact_count(value: str | None) -> int | None:
    if not value:
        return None
    match = COUNT_RE.search(value.replace(",", "").strip())
    if not match:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(float(match.group("number")) * multiplier[(match.group("suffix") or "").upper()])
