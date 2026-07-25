from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.discovery.models import DiscoveryItem, ExtractedArticle
from app.normalization.dates import parse_source_datetime

try:
    import trafilatura
except ModuleNotFoundError:  # pragma: no cover - exercised in environments without optional install
    trafilatura = None

GOOGLE_NEWS_BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
GOOGLE_NEWS_HEADERS = {"User-Agent": "curl/8.17.0", "Accept": "*/*"}
GOOGLE_NEWS_DECODE_HEADERS = {
    **GOOGLE_NEWS_HEADERS,
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
}


async def extract_article(client: httpx.AsyncClient, item: DiscoveryItem) -> ExtractedArticle:
    if not item.url:
        return _failed_article(item, "missing_url")

    request_url = item.url
    warnings: list[str] = []
    if _is_google_news_article_url(item.url):
        resolved_url = await _resolve_google_news_url(client, item.url)
        if resolved_url:
            request_url = resolved_url
            warnings.append("google_news_resolved")
        else:
            warnings.append("google_news_resolve_failed")

    try:
        response = await client.get(request_url, follow_redirects=True, headers=_request_headers(request_url))
        if response.status_code >= 400:
            return _failed_article(item, f"http_{response.status_code}")
    except httpx.HTTPError as exc:
        return _failed_article(item, exc.__class__.__name__)

    final_url = str(response.url)
    html = response.text
    soup = BeautifulSoup(html, "lxml")
    metadata = _html_metadata(soup, final_url)
    extracted = _extract_with_trafilatura(html, final_url) or {}
    content_text = str(extracted.get("content_text") or _fallback_text(soup) or item.summary or item.title).strip()
    summary = str(extracted.get("summary") or metadata.get("summary") or item.summary or "").strip()
    title = str(extracted.get("title") or metadata.get("title") or item.title or "").strip()
    image_url = _first_present(
        extracted.get("image_url"),
        metadata.get("image_url"),
        item.image_url,
    )
    published_at = metadata.get("published_at") or extracted.get("published_at") or item.published_at
    author = extracted.get("author") or metadata.get("author") or item.author
    if item.summary and len(content_text) < len(item.summary.strip()):
        warnings.append("short_extraction")
    extraction_status = "ok"
    if _is_weak_google_news_wrapper(item, final_url, title, summary, content_text):
        fallback_text = _html_to_text(item.summary) or item.title
        title = _fallback_title(item, fallback_text)
        summary = _html_to_text(item.summary)
        content_text = fallback_text
        image_url = item.image_url
        extraction_status = "fallback"
        warnings.append("weak_extraction")

    return ExtractedArticle(
        url=item.url,
        final_url=final_url,
        title=title,
        summary=summary,
        content_text=content_text,
        content_html=None,
        author=author,
        published_at=published_at,
        image_url=image_url,
        extraction_status=extraction_status,
        extraction_warnings=warnings,
    )


async def _resolve_google_news_url(client: httpx.AsyncClient, source_url: str) -> str | None:
    article_id = _google_news_article_id(source_url)
    if not article_id:
        return None
    params = await _google_news_decode_params(client, source_url, article_id)
    if not params:
        return None
    return await _decode_google_news_url(client, article_id, params["signature"], params["timestamp"])


async def _google_news_decode_params(
    client: httpx.AsyncClient,
    source_url: str,
    article_id: str,
) -> dict[str, str] | None:
    candidates = [
        source_url,
        f"https://news.google.com/articles/{article_id}",
        f"https://news.google.com/rss/articles/{article_id}",
    ]
    seen: set[str] = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            response = await client.get(url, follow_redirects=False, headers=GOOGLE_NEWS_HEADERS)
        except httpx.HTTPError:
            continue
        if response.status_code >= 300:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        data_element = soup.select_one("c-wiz > div[jscontroller]") or soup.find(
            attrs={"data-n-a-sg": True, "data-n-a-ts": True}
        )
        if not data_element:
            continue
        signature = data_element.get("data-n-a-sg")
        timestamp = data_element.get("data-n-a-ts")
        if signature and timestamp:
            return {"signature": str(signature), "timestamp": str(timestamp)}
    return None


async def _decode_google_news_url(
    client: httpx.AsyncClient,
    article_id: str,
    signature: str,
    timestamp: str,
) -> str | None:
    payload = [
        "Fbv4je",
        (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
            'null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            f'"{article_id}",{timestamp},"{signature}"]'
        ),
    ]
    body = "f.req=" + quote(json.dumps([[payload]], separators=(",", ":")))
    try:
        response = await client.post(GOOGLE_NEWS_BATCH_URL, headers=GOOGLE_NEWS_DECODE_HEADERS, content=body)
        if response.status_code >= 400:
            return None
    except httpx.HTTPError:
        return None
    return _parse_google_news_decode_response(response.text)


def _parse_google_news_decode_response(value: str) -> str | None:
    try:
        payload_text = value.split("\n\n", 1)[1] if "\n\n" in value else value.removeprefix(")]}'\n")
        rows = json.loads(payload_text)
    except IndexError, json.JSONDecodeError:
        return None
    for row in rows:
        if not isinstance(row, list) or len(row) < 3 or row[0] != "wrb.fr" or not isinstance(row[2], str):
            continue
        try:
            decoded = json.loads(row[2])
        except json.JSONDecodeError:
            continue
        if len(decoded) >= 2 and decoded[0] == "garturlres" and isinstance(decoded[1], str):
            return decoded[1]
    return None


def _is_google_news_article_url(value: str) -> bool:
    return _google_news_article_id(value) is not None


def _google_news_article_id(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.hostname != "news.google.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2] not in {"articles", "read"}:
        return None
    return parts[-1]


def _request_headers(url: str) -> dict[str, str] | None:
    if (urlsplit(url).hostname or "").endswith("news.google.com"):
        return GOOGLE_NEWS_HEADERS
    return None


def _extract_with_trafilatura(html: str, url: str) -> dict[str, Any] | None:
    if trafilatura is None:
        return None
    extracted = trafilatura.extract(html, url=url, output_format="json", with_metadata=True)
    if not extracted:
        return None
    try:
        payload = json.loads(extracted)
    except json.JSONDecodeError:
        return None
    return {
        "title": payload.get("title"),
        "summary": payload.get("description"),
        "content_text": payload.get("text"),
        "author": payload.get("author"),
        "published_at": _parse_datetime(payload.get("date")),
        "image_url": payload.get("image"),
    }


def _html_metadata(soup: BeautifulSoup, final_url: str) -> dict[str, Any]:
    image_url = _first_present(
        _meta_content(soup, "property", "og:image"),
        _meta_content(soup, "name", "twitter:image"),
    )
    if image_url:
        image_url = urljoin(final_url, image_url)
    return {
        "title": _first_present(
            _meta_content(soup, "property", "og:title"),
            _meta_content(soup, "name", "twitter:title"),
            soup.title.string.strip() if soup.title and soup.title.string else None,
        ),
        "summary": _first_present(
            _meta_content(soup, "property", "og:description"),
            _meta_content(soup, "name", "description"),
            _meta_content(soup, "name", "twitter:description"),
        ),
        "image_url": image_url,
        "author": _first_present(
            _meta_content(soup, "name", "author"),
            _meta_content(soup, "property", "article:author"),
        ),
        "published_at": _parse_datetime(
            _first_present(
                _meta_content(soup, "property", "article:published_time"),
                _meta_content(soup, "name", "pubdate"),
                _meta_content(soup, "name", "date"),
            )
        ),
    }


def _meta_content(soup: BeautifulSoup, attr: str, value: str) -> str | None:
    tag = soup.find("meta", attrs={attr: value})
    content = tag.get("content") if tag else None
    return str(content).strip() if content else None


def _fallback_text(soup: BeautifulSoup) -> str:
    container = soup.find("article") or soup.find("main") or soup.body or soup
    for unwanted in container.find_all(["script", "style", "noscript"]):
        unwanted.decompose()
    return container.get_text("\n", strip=True)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parse_source_datetime(value)[0]
    except ValueError, TypeError, OverflowError:
        return None


def _failed_article(item: DiscoveryItem, warning: str) -> ExtractedArticle:
    fallback_text = item.summary or item.title
    return ExtractedArticle(
        url=item.url or item.external_id,
        final_url=item.url or item.external_id,
        title=item.title,
        summary=item.summary,
        content_text=fallback_text,
        content_html=None,
        author=item.author,
        published_at=item.published_at,
        image_url=item.image_url,
        extraction_status="failed",
        extraction_warnings=[warning],
    )


def _is_weak_google_news_wrapper(
    item: DiscoveryItem,
    final_url: str,
    title: str,
    summary: str,
    content_text: str,
) -> bool:
    if item.source_platform != "google_news":
        return False
    host = urlsplit(final_url).hostname or ""
    if not host.endswith("news.google.com"):
        return False
    generic_phrase = "comprehensive up-to-date news coverage"
    return (
        title.strip().casefold() == "google news"
        or generic_phrase in summary.casefold()
        or generic_phrase in content_text.casefold()
    )


def _html_to_text(value: str) -> str:
    if not value:
        return ""
    return BeautifulSoup(value, "lxml").get_text(" ", strip=True)


def _fallback_title(item: DiscoveryItem, fallback_text: str) -> str:
    if item.title.strip().casefold() != "google news":
        return item.title
    soup = BeautifulSoup(item.summary or "", "lxml")
    anchor = soup.find("a")
    if anchor:
        text = anchor.get_text(" ", strip=True)
        if text:
            return text
    return fallback_text.splitlines()[0] if fallback_text else item.title


def _first_present(*values: Any) -> Any:
    for value in values:
        if value:
            return value
    return None
