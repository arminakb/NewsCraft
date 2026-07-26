from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import feedparser
from bs4 import BeautifulSoup

from app.normalization.dates import normalize_source_datetime
from app.normalization.fingerprints import title_date_fingerprint
from app.normalization.media import infer_media_kind, is_http_media_url, parse_int
from app.normalization.text import fingerprint_text
from app.normalization.titles import normalize_title
from app.normalization.urls import normalize_url
from app.sources.base import MediaCandidate, ParsedSourceItem, ParsedSourcePayload


def parse_rss_feed(
    xml: str,
    source_name: str,
    source_url: str,
    default_timezone: str = "UTC",
) -> ParsedSourcePayload:
    feed = feedparser.parse(xml)
    warnings: list[str] = []
    if getattr(feed, "bozo", False):
        warnings.append(f"bozo_feed:{getattr(feed, 'bozo_exception', 'unknown')}")

    items = [
        _parse_entry(entry, source_url=source_url, default_timezone=default_timezone, warnings=warnings)
        for entry in feed.entries
    ]

    feed_title = feed.feed.get("title") if getattr(feed, "feed", None) else None
    return ParsedSourcePayload(
        items=items,
        warnings=warnings,
        feed_meta={
            "source_name": source_name,
            "source_url": source_url,
            "feed_title": feed_title,
            "feed_version": feed.get("version"),
        },
    )


def _parse_entry(
    entry: Any,
    source_url: str,
    default_timezone: str,
    warnings: list[str],
) -> ParsedSourceItem:
    link = _entry_link(entry)
    source_url_norm = normalize_url(link, source_url) if link else None
    title = _entry_title(entry)
    summary_html = entry.get("summary") or entry.get("description") or ""
    content_html = _entry_content_html(entry) or summary_html or None
    summary = _html_to_text(summary_html)
    content_text = _html_to_text(content_html) if content_html else summary or title
    published_raw, published_at, date_parse_status = _entry_date(entry, default_timezone)
    categories = [tag.get("term") for tag in entry.get("tags", []) if tag.get("term")]
    external_id_raw = entry.get("id") or entry.get("guid") or link
    external_id_norm = _external_id_norm(
        external_id_raw,
        source_url,
        title,
        content_text,
        published_raw,
    )

    if not title:
        warnings.append("missing_title")
    if not link:
        warnings.append("missing_link")
    if published_at is None:
        warnings.append("missing_date")

    return ParsedSourceItem(
        external_id_raw=external_id_raw,
        external_id_norm=external_id_norm,
        source_url=link,
        source_url_norm=source_url_norm,
        canonical_url_candidate=source_url_norm,
        title=title,
        summary=summary,
        content_html=content_html,
        content_text=content_text,
        author=_entry_author(entry),
        categories=categories,
        published_raw=published_raw,
        published_at=published_at,
        date_parse_status=date_parse_status,
        media_candidates=_extract_media_candidates(entry, content_html, source_url),
        parser_meta={"feedparser_keys": sorted(entry.keys())},
    )


def _entry_link(entry: Any) -> str | None:
    if entry.get("link"):
        return entry.get("link")
    for link in entry.get("links", []):
        if link.get("rel") == "alternate" and link.get("href"):
            return link.get("href")
    return None


def _entry_title(entry: Any) -> str:
    title = entry.get("title")
    if title:
        return str(title).strip()
    title_detail = entry.get("title_detail") or {}
    if title_detail.get("value"):
        return str(title_detail["value"]).strip()
    return ""


def _entry_content_html(entry: Any) -> str | None:
    contents = entry.get("content") or []
    if contents and contents[0].get("value"):
        return contents[0]["value"]
    return None


def _entry_author(entry: Any) -> str | None:
    if entry.get("author"):
        return str(entry.get("author")).strip()
    authors = entry.get("authors") or []
    if authors and authors[0].get("name"):
        return str(authors[0]["name"]).strip()
    return None


def _entry_date(entry: Any, default_timezone: str) -> tuple[str | None, datetime | None, str]:
    raw = entry.get("published") or entry.get("updated") or entry.get("created")
    if raw:
        parsed, status = normalize_source_datetime(raw, default_timezone=default_timezone)
        return raw, parsed, status

    parsed_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_tuple:
        return None, datetime(*parsed_tuple[:6], tzinfo=UTC), "parsed_struct_time"
    return None, None, "missing"


def _external_id_norm(
    external_id_raw: str | None,
    source_url: str,
    title: str,
    content_text: str,
    published_raw: str | None,
) -> str:
    if external_id_raw:
        value = external_id_raw.strip()
        if value.startswith(("http://", "https://", "/")):
            return normalize_url(value, source_url)
        return fingerprint_text(value)
    normalized_title = normalize_title(title, content_text).title
    return title_date_fingerprint(normalized_title, published_raw or "")


def _extract_media_candidates(entry: Any, content_html: str | None, source_url: str) -> list[MediaCandidate]:
    candidates: list[MediaCandidate] = []
    seen: set[tuple[str, str]] = set()

    for media in entry.get("media_content") or []:
        _append_media_candidate(candidates, seen, media, source_url, "media_content", confidence=1.0)
    for media in entry.get("media_thumbnail") or []:
        _append_media_candidate(candidates, seen, media, source_url, "media_thumbnail", confidence=0.95)
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure":
            _append_media_candidate(candidates, seen, link, source_url, "enclosure", confidence=0.9)
    for enclosure in entry.get("enclosures") or []:
        _append_media_candidate(candidates, seen, enclosure, source_url, "enclosure", confidence=0.9)

    if content_html:
        soup = BeautifulSoup(content_html, "lxml")
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue
            _append_media_candidate(
                candidates,
                seen,
                {"url": src, "medium": "image", "alt": img.get("alt"), "title": img.get("title")},
                source_url,
                "inline_img",
                confidence=0.7,
            )

    return candidates


def _append_media_candidate(
    candidates: list[MediaCandidate],
    seen: set[tuple[str, str]],
    media: dict,
    base_url: str,
    source_field: str,
    confidence: float,
) -> None:
    original_url = media.get("url") or media.get("href")
    if not original_url:
        return
    normalized_url = normalize_url(original_url, base_url)
    if not is_http_media_url(normalized_url):
        return
    dedupe_key = (normalized_url, source_field)
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)

    mime_type = media.get("type")
    medium = media.get("medium")
    candidates.append(
        MediaCandidate(
            original_url=original_url,
            normalized_url=normalized_url,
            kind=infer_media_kind(normalized_url, mime_type=mime_type, medium=medium),
            source_field=source_field,
            mime_type=mime_type,
            width=parse_int(media.get("width")),
            height=parse_int(media.get("height")),
            alt_text=media.get("alt") or media.get("description"),
            title=media.get("title"),
            confidence=confidence,
        )
    )


def _html_to_text(html: str) -> str:
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)
