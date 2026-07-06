from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from app.discovery.models import DiscoveryItem, ExtractedArticle
from app.ingestion.repository import IngestionRepository, build_item_identities
from app.normalization.fingerprints import title_date_fingerprint
from app.normalization.media import is_http_media_url
from app.normalization.text import fingerprint_text
from app.normalization.urls import normalize_url
from app.sources.base import MediaCandidate, ParsedSourceItem


class DiscoveryIngestionService:
    def __init__(self, session=None, repository: IngestionRepository | None = None):
        if repository is None and session is None:
            raise ValueError("session or repository is required")
        self.repository = repository or IngestionRepository(session)

    async def ingest_discovery_items(
        self,
        run_id,
        platform: str,
        items: list[DiscoveryItem],
        extracted: dict[str, ExtractedArticle],
    ) -> dict[str, int]:
        source = await self.repository.ensure_discovery_source(platform)
        stats = {"seen": 0, "persisted": 0, "duplicates": 0, "media_candidates": 0}
        seen_canonical_urls: set[str] = set()

        for item in items:
            stats["seen"] += 1
            article = _article_for_item(item, extracted)
            parsed_item = _to_parsed_item(item, article)
            dedupe_key = (
                parsed_item.canonical_url_candidate or parsed_item.source_url_norm or parsed_item.external_id_norm
            )
            if dedupe_key in seen_canonical_urls:
                stats["duplicates"] += 1
                continue
            seen_canonical_urls.add(dedupe_key)

            payload = await self.repository.save_raw_payload(
                run_id=run_id,
                source_id=source.id,
                payload_kind="discovery_item",
                request_url=item.url or item.external_id,
                final_url=article.final_url,
                http_status=None,
                headers={},
                content_type="application/json",
                raw_text=_raw_payload_text(item, article),
                parser_warnings=article.extraction_warnings,
            )
            source_item = await self.repository.upsert_source_item(
                run_id=run_id,
                source_id=source.id,
                raw_payload_id=payload.id,
                parsed_item=parsed_item,
            )
            identities = build_item_identities(source, parsed_item)
            content_item = await self.repository.upsert_content_item(
                source=source,
                source_item=source_item,
                parsed_item=parsed_item,
                identities=identities,
            )
            await self.repository.attach_identities(
                content_item_id=content_item.id,
                source_item_id=source_item.id,
                source_id=source.id,
                identities=identities,
            )
            media_assets = await self.repository.upsert_media_assets(parsed_item)
            await self.repository.attach_item_media(
                content_item_id=content_item.id,
                media_assets=media_assets,
                parsed_item=parsed_item,
            )
            stats["persisted"] += 1
            stats["media_candidates"] += len(parsed_item.media_candidates)

        return stats


def _article_for_item(item: DiscoveryItem, extracted: dict[str, ExtractedArticle]) -> ExtractedArticle:
    key_candidates = [item.url, item.external_id]
    for key in key_candidates:
        if key and key in extracted:
            return extracted[key]
    return ExtractedArticle(
        url=item.url or item.external_id,
        final_url=item.url or item.external_id,
        title=item.title,
        summary=item.summary,
        content_text=item.summary or item.title,
        content_html=None,
        author=item.author,
        published_at=item.published_at,
        image_url=item.image_url,
        extraction_status="not_extracted",
        extraction_warnings=["not_extracted"],
    )


def _to_parsed_item(item: DiscoveryItem, article: ExtractedArticle) -> ParsedSourceItem:
    source_url = article.url or item.url
    source_url_norm = normalize_url(source_url) if source_url else None
    canonical_url = article.final_url or article.url or item.url
    canonical_url_candidate = normalize_url(canonical_url) if canonical_url else source_url_norm
    published_at = article.published_at or item.published_at
    date_key = published_at.date().isoformat() if published_at else ""
    title = article.title or item.title
    image_url = article.image_url or item.image_url
    media_candidates = _media_candidates(image_url)
    return ParsedSourceItem(
        external_id_raw=item.external_id,
        external_id_norm=_external_id_norm(item.external_id, title, date_key),
        source_url=source_url,
        source_url_norm=source_url_norm,
        canonical_url_candidate=canonical_url_candidate,
        title=title,
        summary=article.summary or item.summary or "",
        content_html=article.content_html,
        content_text=article.content_text or item.summary or item.title,
        author=article.author or item.author,
        categories=list(item.categories),
        published_raw=published_at.isoformat() if published_at else None,
        published_at=published_at,
        date_parse_status="parsed" if published_at else "missing",
        media_candidates=media_candidates,
        parser_meta={
            "source_platform": item.source_platform,
            "source_name": item.source_name,
            "discovery_external_id": item.external_id,
            "discovery_metadata": item.metadata,
            "extraction_status": article.extraction_status,
            "extraction_warnings": article.extraction_warnings,
            "final_url": article.final_url,
        },
    )


def _external_id_norm(external_id: str, title: str, date_key: str) -> str:
    value = external_id.strip()
    if value:
        scheme = urlsplit(value).scheme.lower()
        if scheme in {"http", "https"}:
            return normalize_url(value)
        return fingerprint_text(value)
    return title_date_fingerprint(title, date_key)


def _media_candidates(image_url: str | None) -> list[MediaCandidate]:
    if not image_url:
        return []
    normalized_url = normalize_url(image_url)
    if not is_http_media_url(normalized_url):
        return []
    return [
        MediaCandidate(
            original_url=image_url,
            normalized_url=normalized_url,
            kind="image",
            source_field="article_primary_image",
            confidence=1.0,
        )
    ]


def _raw_payload_text(item: DiscoveryItem, article: ExtractedArticle) -> str:
    return json.dumps(
        {"discovery_item": asdict(item), "extracted_article": asdict(article)},
        ensure_ascii=False,
        default=_json_default,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
