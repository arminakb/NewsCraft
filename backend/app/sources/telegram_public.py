from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from app.normalization.dates import normalize_source_datetime
from app.normalization.media import infer_media_kind, is_http_media_url
from app.normalization.text import infer_direction
from app.normalization.urls import normalize_url
from app.sources.base import MediaCandidate, ParsedSourceItem, ParsedSourcePayload

CSS_URL_RE = re.compile(r"background-image:\s*url\((?P<quote>['\"]?)(?P<url>.*?)(?P=quote)\)")
COUNT_RE = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<suffix>[KMB])?", re.IGNORECASE)


def parse_public_telegram_page(html: str, channel: str) -> ParsedSourcePayload:
    soup = BeautifulSoup(html, "lxml")
    warnings: list[str] = []
    parsed_items = [
        _parse_message(block, channel=channel, warnings=warnings)
        for block in soup.select(".tgme_widget_message[data-post]")
    ]
    items = [item for item in parsed_items if item is not None]
    return ParsedSourcePayload(items=items, warnings=warnings, feed_meta={"channel": channel})


def _parse_message(block: Tag, channel: str, warnings: list[str]) -> ParsedSourceItem | None:
    data_post = block.get("data-post")
    if not isinstance(data_post, str) or "/" not in data_post:
        warnings.append("missing_data_post")
        return None
    post_channel, raw_message_id = data_post.rsplit("/", 1)
    if post_channel != channel:
        return None
    try:
        data_post_message_id = int(raw_message_id)
    except ValueError:
        warnings.append(f"invalid_message_id:{data_post}")
        return None

    message_ids = _message_ids(block, data_post_message_id)
    message_id = max(message_ids)
    grouped_id = _grouped_id(block)

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
        external_id_raw=f"{channel}/{message_id}",
        external_id_norm=f"{channel}/{message_id}",
        source_url=source_url,
        source_url_norm=normalize_url(source_url),
        canonical_url_candidate=normalize_url(source_url),
        title="",
        summary=content_text,
        content_html=content_html,
        content_text=content_text,
        author=_select_text(block, ".tgme_widget_message_owner_name"),
        categories=[],
        published_raw=published_raw,
        published_at=published_at,
        date_parse_status=date_parse_status,
        media_candidates=_extract_media_candidates(block),
        parser_meta={
            "channel": channel,
            "content_origin": "source_provided" if content_text else "unavailable",
            "message_id": message_id,
            "message_ids": message_ids,
            "grouped_id": grouped_id,
            "views": views,
            "reactions": _extract_reactions(block),
            "entities": _extract_entities(text_node),
            "direction": infer_direction(content_text),
        },
    )


def _message_datetime(block: Tag) -> tuple[str | None, datetime | None, str]:
    time_node = block.select_one("time[datetime]")
    if not time_node:
        return None, None, "missing"
    raw_value = time_node.get("datetime")
    raw = str(raw_value) if raw_value else None
    parsed, status = normalize_source_datetime(raw)
    return raw, parsed, status


def _extract_media_candidates(block: Tag) -> list[MediaCandidate]:
    candidates: list[MediaCandidate] = []
    selector = (
        ".tgme_widget_message_photo_wrap, .tgme_widget_message_video_wrap, "
        ".tgme_widget_message_document_wrap, .tgme_widget_message_document"
    )
    for media_node in block.select(selector):
        classes = set(media_node.get("class") or ())
        if "tgme_widget_message_photo_wrap" in classes:
            url = _background_image_url(media_node)
            source_field, kind = "message_photo", "image"
        elif "tgme_widget_message_video_wrap" in classes:
            url = _background_image_url(media_node) or _first_attr(media_node, "video", "src")
            source_field, kind = "message_video", "video"
        else:
            raw_url = media_node.get("href")
            url = str(raw_url) if raw_url else _first_attr(media_node, "a", "href")
            source_field, kind = "message_document", "document"
        if url:
            _append_media(candidates, str(url), source_field=source_field, kind=kind)
    for preview in block.select(".tgme_widget_message_link_preview"):
        url = _background_image_url(preview)
        if url:
            _append_media(candidates, url, source_field="link_preview_image", kind="image")
    return candidates


def _append_media(candidates: list[MediaCandidate], url: str, source_field: str, kind: str) -> None:
    normalized_url = normalize_url(url)
    if not is_http_media_url(normalized_url):
        return
    if any(candidate.normalized_url == normalized_url for candidate in candidates):
        return
    candidates.append(
        MediaCandidate(
            original_url=url,
            normalized_url=normalized_url,
            kind=kind if kind else infer_media_kind(normalized_url),
            source_field=source_field,
        )
    )


def _background_image_url(node: Tag) -> str | None:
    style = node.get("style")
    if not isinstance(style, str):
        return None
    match = CSS_URL_RE.search(style)
    if not match:
        return None
    return match.group("url")


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
    reactions: dict[str, int] = {}
    for reaction in block.select(".tgme_reaction"):
        text = reaction.get_text(" ", strip=True)
        match = COUNT_RE.search(text)
        if not match:
            continue
        label = text[: match.start()].strip() or "reaction"
        reactions[label] = parse_compact_count(match.group(0)) or 0
    return reactions


def _message_ids(block: Tag, data_post_message_id: int) -> list[int]:
    message_ids: list[int] = []
    for node in block.select("[data-message-id]"):
        value = node.get("data-message-id")
        try:
            message_id = int(str(value))
        except TypeError, ValueError:
            continue
        if message_id not in message_ids:
            message_ids.append(message_id)
    if data_post_message_id not in message_ids:
        message_ids.append(data_post_message_id)
    return message_ids


def _grouped_id(block: Tag) -> str | None:
    value = block.get("data-grouped-id")
    if value:
        return str(value)
    wrapper = block.select_one("[data-grouped-id]")
    return str(wrapper.get("data-grouped-id")) if wrapper and wrapper.get("data-grouped-id") else None


def _extract_entities(text_node: Tag | None) -> list[dict]:
    if text_node is None:
        return []
    entities: list[dict] = []
    tag_types = {
        "b": "bold",
        "strong": "bold",
        "i": "italic",
        "em": "italic",
        "u": "underline",
        "s": "strikethrough",
        "code": "code",
    }
    for node in text_node.find_all(["a", *tag_types]):
        text_value = _node_text(node)
        if not text_value:
            continue
        if node.name == "a":
            href = node.get("href")
            if href:
                entities.append({"type": "link", "text": text_value, "url": str(href)})
        else:
            entities.append({"type": tag_types[node.name], "text": text_value})
    return entities


def parse_compact_count(value: str | None) -> int | None:
    if not value:
        return None
    match = COUNT_RE.search(value.replace(",", "").strip())
    if not match:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    suffix = (match.group("suffix") or "").upper()
    return int(float(match.group("number")) * multiplier[suffix])
