import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx

from app.daily_bundle import __main__ as daily_bundle_main
from app.daily_bundle.__main__ import DailyBundleDependencies, parse_args, run_daily_bundle
from app.discovery.models import DiscoveryItem, ExtractedArticle
from app.ingestion import service as ingestion_service


def test_parse_args_accepts_daily_bundle_flags(tmp_path):
    args = parse_args(
        [
            "--start",
            "2026-07-05",
            "--end",
            "2026-07-06",
            "--topic",
            "AI",
            "--topic",
            "economy",
            "--output",
            str(tmp_path),
            "--timezone",
            "Asia/Tehran",
            "--download-media",
        ]
    )

    assert args.start == "2026-07-05"
    assert args.end == "2026-07-06"
    assert args.topic == ["AI", "economy"]
    assert args.output == tmp_path
    assert args.timezone == "Asia/Tehran"
    assert args.download_media is True


async def test_run_daily_bundle_orchestrates_ingestion_discovery_extraction_download_and_export(tmp_path):
    events: list[tuple] = []
    run_id = uuid4()
    exported_range = {}

    args = parse_args(
        [
            "--topic",
            "AI",
            "--output",
            str(tmp_path),
            "--timezone",
            "Asia/Tehran",
            "--download-media",
        ]
    )
    deps = DailyBundleDependencies(
        session_factory=lambda: FakeSessionContext(events),
        http_client_factory=lambda: FakeClientContext(events),
        ingestion_service_factory=lambda session, client: FakeIngestionService(events),
        repository_factory=lambda session: FakeRepository(events, run_id),
        discovery_service_factory=lambda session, repository: FakeDiscoveryService(events),
        media_downloader_factory=lambda session, client: FakeMediaDownloader(events),
        gdelt_discoverer=lambda client, start, end, topics: fake_discoverer(events, "gdelt", topics),
        google_news_discoverer=lambda client, start, end, topics: fake_discoverer(events, "google_news", topics),
        hackernews_discoverer=lambda client, start, end: fake_discoverer(events, "hackernews", []),
        article_extractor=fake_extract_article,
        exporter=lambda session, start, end, output, limit=250: fake_exporter(
            events, exported_range, start, end, output, limit
        ),
        now=lambda: datetime(2026, 7, 6, 10, tzinfo=UTC),
        printer=lambda message: events.append(("print", message)),
    )

    result = await run_daily_bundle(args, deps)

    assert exported_range["start"].date().isoformat() == "2026-07-05"
    assert exported_range["end"].date().isoformat() == "2026-07-06"
    assert result["export"]["item_count"] == 3
    assert result["media_downloads"] == {"checked": 1, "downloaded": 1, "skipped": 0, "failed": 0}
    assert [event[0] for event in events] == [
        "client_enter",
        "session_enter",
        "existing_ingestion",
        "create_run",
        "discover",
        "discover",
        "discover",
        "extract",
        "extract",
        "extract",
        "persist",
        "persist",
        "persist",
        "download_media",
        "export",
        "finish_run",
        "commit",
        "print",
        "session_exit",
        "client_exit",
    ]
    assert events[2][1] == ("rss", "atom", "telegram_public")


async def test_http_client_builders_ignore_blank_proxy_settings(monkeypatch):
    for module in (daily_bundle_main, ingestion_service):
        monkeypatch.setattr(module.settings, "all_proxy", "")
        monkeypatch.setattr(module.settings, "https_proxy", "")
        monkeypatch.setattr(module.settings, "http_proxy", "")
        client = module._build_http_client()
        await client.aclose()


async def test_run_daily_bundle_records_discovery_errors_without_aborting(tmp_path):
    events: list[tuple] = []
    args = parse_args(["--start", "2026-07-05", "--end", "2026-07-06", "--topic", "AI", "--output", str(tmp_path)])
    deps = DailyBundleDependencies(
        session_factory=lambda: FakeSessionContext(events),
        http_client_factory=lambda: FakeClientContext(events),
        ingestion_service_factory=lambda session, client: FakeIngestionService(events),
        repository_factory=lambda session: FakeRepository(events, uuid4()),
        discovery_service_factory=lambda session, repository: FakeDiscoveryService(events),
        media_downloader_factory=lambda session, client: FakeMediaDownloader(events),
        gdelt_discoverer=failing_discoverer,
        google_news_discoverer=lambda client, start, end, topics: fake_discoverer(events, "google_news", topics),
        hackernews_discoverer=lambda client, start, end: fake_discoverer(events, "hackernews", []),
        article_extractor=fake_extract_article,
        exporter=lambda session, start, end, output, limit=250: fake_exporter(events, {}, start, end, output, limit),
        printer=lambda message: events.append(("print", message)),
    )

    result = await run_daily_bundle(args, deps)

    assert result["discovery"] == {"gdelt": 0, "google_news": 1, "hackernews": 1}
    assert result["discovery_errors"] == [{"platform": "gdelt", "error": "ConnectTimeout: gdelt timeout"}]
    assert ("persist", "google_news", 1, 2) in events
    assert ("persist", "hackernews", 1, 2) in events


async def test_run_daily_bundle_redacts_discovery_errors_before_persisting_or_printing(tmp_path):
    events: list[tuple] = []
    args = parse_args(["--start", "2026-07-05", "--end", "2026-07-06", "--output", str(tmp_path)])

    async def leaking_discoverer(client, start, end, topics):
        raise RuntimeError("authorization: Bearer daily-bundle-canary")

    deps = DailyBundleDependencies(
        session_factory=lambda: FakeSessionContext(events),
        http_client_factory=lambda: FakeClientContext(events),
        ingestion_service_factory=lambda session, client: FakeIngestionService(events),
        repository_factory=lambda session: FakeRepository(events, uuid4()),
        discovery_service_factory=lambda session, repository: FakeDiscoveryService(events),
        media_downloader_factory=lambda session, client: FakeMediaDownloader(events),
        gdelt_discoverer=leaking_discoverer,
        google_news_discoverer=lambda client, start, end, topics: fake_discoverer(events, "google_news", topics),
        hackernews_discoverer=lambda client, start, end: fake_discoverer(events, "hackernews", []),
        article_extractor=fake_extract_article,
        exporter=lambda session, start, end, output, limit=250: fake_exporter(events, {}, start, end, output, limit),
        printer=lambda message: events.append(("print", message)),
    )

    result = await run_daily_bundle(args, deps)

    serialized_result = json.dumps(result)
    printed = next(event[1] for event in events if event[0] == "print")
    persisted_stats = next(event[3] for event in events if event[0] == "finish_run")
    assert "daily-bundle-canary" not in serialized_result
    assert "daily-bundle-canary" not in printed
    assert "daily-bundle-canary" not in json.dumps(persisted_stats)
    assert result["discovery_errors"] == [{"platform": "gdelt", "error": "RuntimeError: authorization:[REDACTED]"}]


class FakeSessionContext:
    def __init__(self, events):
        self.events = events
        self.session = SimpleNamespace()

    async def __aenter__(self):
        self.events.append(("session_enter",))
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.events.append(("session_exit",))

    async def commit(self):
        self.events.append(("commit",))

    async def rollback(self):
        self.events.append(("rollback",))


class FakeClientContext:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        self.events.append(("client_enter",))
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.events.append(("client_exit",))


class FakeIngestionService:
    def __init__(self, events):
        self.events = events

    async def run_once(self, platforms, trigger):
        self.events.append(("existing_ingestion", tuple(platforms), trigger))
        return {"items": 2}


class FakeRepository:
    def __init__(self, events, run_id):
        self.events = events
        self.run_id = run_id

    async def create_run(self, trigger: str, parser_version: str):
        self.events.append(("create_run", trigger, parser_version))
        return SimpleNamespace(id=self.run_id)

    async def finish_run(self, run_id, status: str, stats: dict, error: str | None = None):
        self.events.append(("finish_run", run_id, status, stats, error))


class FakeDiscoveryService:
    def __init__(self, events):
        self.events = events

    async def ingest_discovery_items(self, run_id, platform, items, extracted):
        self.events.append(("persist", platform, len(items), len(extracted)))
        return {"seen": len(items), "persisted": len(items), "duplicates": 0, "media_candidates": len(items)}


class FakeMediaDownloader:
    def __init__(self, events):
        self.events = events

    async def download_missing(self):
        self.events.append(("download_media",))
        return {"checked": 1, "downloaded": 1, "skipped": 0, "failed": 0}


async def fake_discoverer(events, platform: str, topics: list[str]):
    events.append(("discover", platform, tuple(topics)))
    return [_item(platform)]


async def failing_discoverer(client, start, end, topics):
    raise httpx.ConnectTimeout("gdelt timeout")


async def fake_extract_article(client, item):
    events = client.events
    events.append(("extract", item.source_platform, item.url))
    return ExtractedArticle(
        url=item.url,
        final_url=item.url,
        title=item.title,
        summary=item.summary,
        content_text="Extracted text",
        content_html=None,
        author=None,
        published_at=item.published_at,
        image_url=item.image_url,
        extraction_status="ok",
        extraction_warnings=[],
    )


async def fake_exporter(events, exported_range, start, end, output, limit):
    events.append(("export", Path(output), limit))
    exported_range["start"] = start
    exported_range["end"] = end
    return {"output_path": str(output), "item_count": 3}


def _item(platform: str) -> DiscoveryItem:
    return DiscoveryItem(
        source_platform=platform,
        source_name=platform,
        external_id=f"https://example.com/{platform}",
        title=f"{platform} title",
        url=f"https://example.com/{platform}",
        summary="Summary",
        published_at=datetime(2026, 7, 5, 12, tzinfo=UTC),
        image_url=None,
        author=None,
        categories=[],
        metadata={},
    )
