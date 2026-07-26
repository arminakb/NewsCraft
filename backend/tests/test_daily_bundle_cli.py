from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.daily_bundle import __main__ as daily_bundle_main
from app.daily_bundle.__main__ import DailyBundleDependencies, parse_args, run_daily_bundle
from app.ingestion import workflow as ingestion_workflow


def test_parse_args_accepts_daily_bundle_flags(tmp_path):
    args = parse_args(
        [
            "--start",
            "2026-07-05",
            "--end",
            "2026-07-06",
            "--output",
            str(tmp_path),
            "--timezone",
            "Asia/Tehran",
            "--download-media",
        ]
    )

    assert args.start == "2026-07-05"
    assert args.end == "2026-07-06"
    assert args.output == tmp_path
    assert args.timezone == "Asia/Tehran"
    assert args.download_media is True


async def test_run_daily_bundle_uses_canonical_ingestion_and_export(tmp_path):
    events: list[tuple] = []
    exported_range: dict[str, datetime] = {}
    args = parse_args(
        [
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
        ingestion_workflow_factory=lambda client: FakeIngestionWorkflow(events),
        media_downloader_factory=lambda session, client: FakeMediaDownloader(events),
        exporter=lambda session, start, end, output, limit=250: fake_exporter(
            events, exported_range, start, end, output, limit
        ),
        now=lambda: datetime(2026, 7, 6, 10, tzinfo=UTC),
        printer=lambda message: events.append(("print", message)),
    )

    result = await run_daily_bundle(args, deps)

    assert exported_range["start"].date().isoformat() == "2026-07-05"
    assert exported_range["end"].date().isoformat() == "2026-07-06"
    assert result["ingestion"] == {"items": 2}
    assert result["export"]["item_count"] == 3
    assert result["media_downloads"] == {"checked": 1, "downloaded": 1, "skipped": 0, "failed": 0}
    assert [event[0] for event in events] == [
        "client_enter",
        "session_enter",
        "ingestion",
        "download_media",
        "commit",
        "export",
        "session_exit",
        "client_exit",
        "print",
    ]
    assert events[2][1] == ("rss", "atom", "telegram_public")


async def test_http_client_builders_ignore_blank_proxy_settings(monkeypatch):
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        monkeypatch.setenv(name, "  ")
    for module in (daily_bundle_main, ingestion_workflow):
        client = module._build_http_client()
        assert client._trust_env is False
        assert client._transport.__class__.__name__ == "OutboundProxyTransport"
        await client.aclose()


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


class FakeClientContext:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        self.events.append(("client_enter",))
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.events.append(("client_exit",))


class FakeIngestionWorkflow:
    def __init__(self, events):
        self.events = events

    async def run(self, *, session, platforms, source_ids, trigger):
        assert session is not None
        assert source_ids is None
        assert trigger == "daily_bundle"
        self.events.append(("ingestion", tuple(platforms)))
        return {"items": 2}


class FakeMediaDownloader:
    def __init__(self, events):
        self.events = events

    async def download_missing(self):
        self.events.append(("download_media",))
        return {"checked": 1, "downloaded": 1, "skipped": 0, "failed": 0}


async def fake_exporter(events, exported_range, start, end, output, limit):
    events.append(("export", output, limit))
    exported_range["start"] = start
    exported_range["end"] = end
    assert Path(output).name
    return {"output_path": str(output), "item_count": 3}
