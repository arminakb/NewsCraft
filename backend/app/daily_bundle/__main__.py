from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.outbound_proxy import build_outbound_http_client
from app.core.redaction import redact_string
from app.daily_bundle.date_range import default_yesterday, parse_date_range
from app.daily_bundle.exporter import export_daily_bundle
from app.db.session import async_session
from app.discovery.article_extractor import extract_article
from app.discovery.gdelt import discover_gdelt
from app.discovery.google_news import discover_google_news_rss
from app.discovery.hackernews import discover_hackernews
from app.discovery.models import DiscoveryItem, ExtractedArticle
from app.discovery.service import DiscoveryIngestionService
from app.ingestion.repository import IngestionRepository
from app.ingestion.service import IngestionService
from app.media.downloader import MediaDownloader

DEFAULT_DISCOVERY_PLATFORMS = ("rss", "atom", "telegram_public")
DEFAULT_TIMEZONE = "Asia/Tehran"
DEFAULT_EXTRACTION_CONCURRENCY = 8


@dataclass(slots=True)
class DailyBundleDependencies:
    session_factory: Callable[[], Any] = async_session
    http_client_factory: Callable[[], Any] = lambda: _build_http_client()
    ingestion_service_factory: Callable[[Any, httpx.AsyncClient], IngestionService] = lambda session, client: (
        IngestionService(session, http_client=client)
    )
    repository_factory: Callable[[Any], IngestionRepository] = lambda session: IngestionRepository(session)
    discovery_service_factory: Callable[[Any, IngestionRepository], DiscoveryIngestionService] = (
        lambda session, repository: DiscoveryIngestionService(session=session, repository=repository)
    )
    media_downloader_factory: Callable[[Any, httpx.AsyncClient], MediaDownloader] = lambda session, client: (
        MediaDownloader(session, http_client=client)
    )
    gdelt_discoverer: Callable[[httpx.AsyncClient, datetime, datetime, list[str]], Any] = discover_gdelt
    google_news_discoverer: Callable[[httpx.AsyncClient, datetime, datetime, list[str]], Any] = discover_google_news_rss
    hackernews_discoverer: Callable[[httpx.AsyncClient, datetime, datetime], Any] = discover_hackernews
    article_extractor: Callable[[httpx.AsyncClient, DiscoveryItem], Any] = extract_article
    exporter: Callable[[Any, datetime, datetime, Path], Any] = export_daily_bundle
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    printer: Callable[[str], None] = print


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and export a daily news bundle.")
    parser.add_argument("--start", help="Inclusive start date, YYYY-MM-DD.")
    parser.add_argument("--end", help="Exclusive end date, YYYY-MM-DD.")
    parser.add_argument("--topic", action="append", default=[], help="Discovery topic. Can be passed more than once.")
    parser.add_argument("--output", type=Path, help="Output folder for the agent-readable bundle.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="Timezone for default and parsed date ranges.")
    parser.add_argument("--download-media", action="store_true", help="Download missing remote media before export.")
    args = parser.parse_args(argv)
    if bool(args.start) != bool(args.end):
        parser.error("--start and --end must be provided together")
    return args


async def run_daily_bundle(
    args: argparse.Namespace,
    deps: DailyBundleDependencies | None = None,
) -> dict[str, Any]:
    deps = deps or DailyBundleDependencies()
    start, end = _resolve_date_range(args, deps)
    output_path = args.output or Path("../today-news") / start.date().isoformat()
    stats: dict[str, Any] = {
        "date_range": {"start": start.isoformat(), "end": end.isoformat(), "timezone": args.timezone},
        "topics": list(args.topic),
        "existing_ingestion": {},
        "discovery": {},
        "discovery_errors": [],
        "extraction": {},
        "persistence": {},
        "media_downloads": None,
        "export": {},
    }

    async with deps.http_client_factory() as client:
        async with deps.session_factory() as session:
            repository = deps.repository_factory(session)
            try:
                ingestion_service = deps.ingestion_service_factory(session, client)
                stats["existing_ingestion"] = await ingestion_service.run_once(
                    platforms=list(DEFAULT_DISCOVERY_PLATFORMS),
                    trigger="daily_bundle",
                )

                discovery_run = await repository.create_run(
                    trigger="daily_bundle",
                    parser_version=settings.parser_version,
                )
                discovered, discovery_errors = await _discover_items(client, start, end, list(args.topic), deps)
                stats["discovery"] = {platform: len(items) for platform, items in discovered.items()}
                stats["discovery_errors"] = discovery_errors

                all_items = [item for items in discovered.values() for item in items]
                extracted = await extract_articles(
                    client,
                    all_items,
                    extractor=deps.article_extractor,
                    concurrency=DEFAULT_EXTRACTION_CONCURRENCY,
                )
                stats["extraction"] = _extraction_stats(extracted)

                discovery_service = deps.discovery_service_factory(session, repository)
                for platform, items in discovered.items():
                    stats["persistence"][platform] = await discovery_service.ingest_discovery_items(
                        discovery_run.id,
                        platform,
                        items,
                        extracted,
                    )

                if args.download_media:
                    downloader = deps.media_downloader_factory(session, client)
                    stats["media_downloads"] = await downloader.download_missing()

                stats["export"] = await deps.exporter(session, start, end, output_path)
                await repository.finish_run(discovery_run.id, status="succeeded", stats=stats)
                await _commit(session)
                deps.printer(json.dumps(stats, ensure_ascii=False, default=_json_default))
            except Exception as exc:
                if "discovery_run" in locals():
                    await repository.finish_run(discovery_run.id, status="failed", stats=stats, error=str(exc))
                    await _commit(session)
                raise

    return stats


async def extract_articles(
    client: httpx.AsyncClient,
    items: list[DiscoveryItem],
    extractor: Callable[[httpx.AsyncClient, DiscoveryItem], Any] = extract_article,
    concurrency: int = DEFAULT_EXTRACTION_CONCURRENCY,
) -> dict[str, ExtractedArticle]:
    semaphore = asyncio.Semaphore(concurrency)
    keyed_items: dict[str, DiscoveryItem] = {}
    for item in items:
        key = item.url or item.external_id
        if key not in keyed_items:
            keyed_items[key] = item

    async def extract_one(key: str, item: DiscoveryItem) -> tuple[str, ExtractedArticle]:
        async with semaphore:
            try:
                return key, await extractor(client, item)
            except Exception as exc:  # noqa: BLE001 - one bad URL should not abort the bundle
                return key, _failed_extraction(item, exc)

    pairs = await asyncio.gather(*(extract_one(key, item) for key, item in keyed_items.items()))
    return dict(pairs)


async def _discover_items(
    client: httpx.AsyncClient,
    start: datetime,
    end: datetime,
    topics: list[str],
    deps: DailyBundleDependencies,
) -> tuple[dict[str, list[DiscoveryItem]], list[dict[str, str]]]:
    discovered: dict[str, list[DiscoveryItem]] = {}
    errors: list[dict[str, str]] = []
    discovery_calls = {
        "gdelt": lambda: deps.gdelt_discoverer(client, start, end, topics),
        "google_news": lambda: deps.google_news_discoverer(client, start, end, topics),
        "hackernews": lambda: deps.hackernews_discoverer(client, start, end),
    }
    for platform, discover in discovery_calls.items():
        try:
            discovered[platform] = await discover()
        except Exception as exc:  # noqa: BLE001 - one source should not abort the daily bundle
            discovered[platform] = []
            errors.append(
                {
                    "platform": platform,
                    "error": redact_string(f"{exc.__class__.__name__}: {exc}"),
                }
            )
    return discovered, errors


def _resolve_date_range(args: argparse.Namespace, deps: DailyBundleDependencies) -> tuple[datetime, datetime]:
    if args.start and args.end:
        return parse_date_range(args.start, args.end, args.timezone)
    return default_yesterday(args.timezone, now=deps.now())


def _build_http_client() -> httpx.AsyncClient:
    return build_outbound_http_client(timeout=30.0)


def _failed_extraction(item: DiscoveryItem, exc: Exception) -> ExtractedArticle:
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
        extraction_status="failed",
        extraction_warnings=[exc.__class__.__name__],
    )


def _extraction_stats(extracted: dict[str, ExtractedArticle]) -> dict[str, int]:
    failed = sum(1 for article in extracted.values() if article.extraction_status == "failed")
    return {"attempted": len(extracted), "failed": failed, "succeeded": len(extracted) - failed}


async def _commit(session) -> None:
    commit = getattr(session, "commit", None)
    if commit is not None:
        await commit()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def main() -> None:
    asyncio.run(run_daily_bundle(parse_args()))


if __name__ == "__main__":
    main()
