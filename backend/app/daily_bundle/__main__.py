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

from app.core.outbound_proxy import build_outbound_http_client
from app.daily_bundle.date_range import default_yesterday, parse_date_range
from app.daily_bundle.exporter import export_daily_bundle
from app.db.session import async_session
from app.ingestion.workflow import IngestionWorkflow
from app.media.downloader import MediaDownloader

DEFAULT_INGESTION_PLATFORMS = ("rss", "atom", "telegram_public")
DEFAULT_TIMEZONE = "Asia/Tehran"


@dataclass(slots=True)
class DailyBundleDependencies:
    session_factory: Callable[[], Any] = async_session
    http_client_factory: Callable[[], Any] = lambda: _build_http_client()
    ingestion_workflow_factory: Callable[[httpx.AsyncClient], IngestionWorkflow] = lambda client: IngestionWorkflow(
        http_client=client
    )
    media_downloader_factory: Callable[[Any, httpx.AsyncClient], MediaDownloader] = lambda session, client: (
        MediaDownloader(session, http_client=client)
    )
    exporter: Callable[[Any, datetime, datetime, Path], Any] = export_daily_bundle
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    printer: Callable[[str], None] = print


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect configured sources and export a daily news bundle.")
    parser.add_argument("--start", help="Inclusive start date, YYYY-MM-DD.")
    parser.add_argument("--end", help="Exclusive end date, YYYY-MM-DD.")
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

    async with deps.http_client_factory() as client:
        async with deps.session_factory() as session:
            ingestion = await deps.ingestion_workflow_factory(client).run(
                session=session,
                platforms=list(DEFAULT_INGESTION_PLATFORMS),
                source_ids=None,
                trigger="daily_bundle",
            )
            media_downloads = None
            if args.download_media:
                media_downloads = await deps.media_downloader_factory(session, client).download_missing()
                await session.commit()
            export = await deps.exporter(session, start, end, output_path)

    result = {
        "date_range": {"start": start.isoformat(), "end": end.isoformat(), "timezone": args.timezone},
        "ingestion": ingestion,
        "media_downloads": media_downloads,
        "export": export,
    }
    deps.printer(json.dumps(result, ensure_ascii=False, default=_json_default))
    return result


def _resolve_date_range(args: argparse.Namespace, deps: DailyBundleDependencies) -> tuple[datetime, datetime]:
    if args.start and args.end:
        return parse_date_range(args.start, args.end, args.timezone)
    return default_yesterday(args.timezone, now=deps.now())


def _build_http_client() -> httpx.AsyncClient:
    return build_outbound_http_client(timeout=30.0)


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
