from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.db.models import Source
from app.ingestion.repository import IngestionRepository, build_item_identities
from app.sources.registry import parser_for_source

DEFAULT_HEADERS = {"User-Agent": "NewsCraftBot/1.0"}


class IngestionService:
    def __init__(
        self,
        session,
        repository: IngestionRepository | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.session = session
        self.repository = repository or IngestionRepository(session)
        self.http_client = http_client

    async def run_once(
        self,
        platforms: list[str] | None = None,
        source_ids: list[str] | None = None,
        trigger: str = "manual",
    ) -> dict[str, Any]:
        run = await self.repository.create_run(trigger=trigger, parser_version=settings.parser_version)
        stats = {
            "checked": 0,
            "fetched": 0,
            "skipped": 0,
            "failed": 0,
            "items": 0,
            "media_candidates": 0,
            "errors": [],
        }

        owns_client = self.http_client is None
        client = self.http_client or _build_http_client()
        try:
            sources = await self.repository.get_active_sources(platforms=platforms)
            for source in _filter_sources(sources, source_ids):
                stats["checked"] += 1
                try:
                    await self._ingest_source(client, run.id, source, stats)
                except Exception as exc:  # noqa: BLE001 - source-level failures should not abort the whole run
                    stats["failed"] += 1
                    stats["errors"].append({"source": source.name, "error": str(exc)})

            status = "partial" if stats["failed"] else "succeeded"
            await self.repository.finish_run(run.id, status=status, stats=stats)
            return stats
        except Exception as exc:
            stats["failed"] += 1
            stats["errors"].append({"run": str(exc)})
            await self.repository.finish_run(run.id, status="failed", stats=stats, error=str(exc))
            return stats
        finally:
            if owns_client:
                await client.aclose()

    async def _ingest_source(
        self,
        client: httpx.AsyncClient,
        run_id,
        source: Source,
        stats: dict[str, Any],
    ) -> None:
        request_url = _source_request_url(source)
        response = await client.get(request_url, headers=_request_headers(source), follow_redirects=True)
        payload = await self.repository.save_raw_payload(
            run_id=run_id,
            source_id=source.id,
            payload_kind=_payload_kind(source),
            request_url=request_url,
            final_url=str(response.url),
            http_status=response.status_code,
            headers=dict(response.headers),
            content_type=response.headers.get("content-type"),
            raw_text=response.text,
            parser_warnings=[],
        )

        _update_source_fetch_state(source, response)
        if response.status_code == 304:
            stats["skipped"] += 1
            await _flush(self.session)
            return
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code} for {request_url}")

        stats["fetched"] += 1
        parsed_payload = _parse_source_payload(source, response.text, request_url)
        payload.parser_warnings = parsed_payload.warnings

        for parsed_item in parsed_payload.items:
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
            stats["items"] += 1
            stats["media_candidates"] += len(parsed_item.media_candidates)
        await _flush(self.session)


def _build_http_client() -> httpx.AsyncClient:
    proxy = settings.all_proxy or settings.https_proxy or settings.http_proxy
    return httpx.AsyncClient(timeout=20.0, proxy=proxy, trust_env=True)


def _filter_sources(sources: list[Source], source_ids: list[str] | None) -> list[Source]:
    if not source_ids:
        return sources
    wanted = set(source_ids)
    return [source for source in sources if str(source.id) in wanted]


def _source_request_url(source: Source) -> str:
    if source.platform in {"rss", "atom"} and source.feed_url:
        return source.feed_url
    if source.platform == "telegram_public" and source.telegram_username:
        return f"https://t.me/s/{source.telegram_username}"
    raise ValueError(f"Source {source.name} is missing fetch URL data")


def _request_headers(source: Source) -> dict[str, str]:
    headers = dict(DEFAULT_HEADERS)
    if source.etag:
        headers["If-None-Match"] = source.etag
    if source.last_modified:
        headers["If-Modified-Since"] = source.last_modified
    return headers


def _payload_kind(source: Source) -> str:
    if source.platform in {"rss", "atom"}:
        return "feed_xml"
    if source.platform == "telegram_public":
        return "telegram_html"
    return "raw"


def _parse_source_payload(source: Source, raw_text: str, request_url: str):
    parser = parser_for_source(source)
    if source.platform in {"rss", "atom"}:
        return parser(
            raw_text,
            source_name=source.name,
            source_url=source.feed_url or request_url,
            default_timezone=source.default_timezone or "UTC",
        )
    if source.platform == "telegram_public":
        return parser(raw_text, channel=source.telegram_username)
    raise ValueError(f"Unsupported source platform: {source.platform}")


def _update_source_fetch_state(source: Source, response: httpx.Response) -> None:
    source.etag = response.headers.get("etag") or source.etag
    source.last_modified = response.headers.get("last-modified") or source.last_modified
    source.last_fetch_at = datetime.now(UTC)


async def _flush(session) -> None:
    if session is not None:
        await session.flush()
