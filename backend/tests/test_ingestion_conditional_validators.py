from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.models import Source
from app.ingestion.workflow import FetchedSourceBatch, IngestionWorkflow, PreparedSource


class _StubPayloadRepository:
    def __init__(self, _session):
        pass

    async def save_raw_payload(self, **_kwargs):
        return SimpleNamespace(id=uuid4(), parser_warnings=[])


def _source() -> Source:
    return Source(
        id=uuid4(),
        platform="rss",
        name="source-1",
        feed_url="https://example.com/feed.xml",
        source_group="news",
        default_timezone="UTC",
        active=True,
    )


async def _persist(monkeypatch, source: Source, *, http_status: int, headers: dict[str, str]):
    prepared = PreparedSource(
        id=source.id,
        name=source.name,
        platform=source.platform,
        feed_url=source.feed_url,
        telegram_username=None,
        default_timezone="UTC",
        etag=source.etag,
        last_modified=source.last_modified,
    )

    class Session:
        async def get(self, model, identifier):
            return source if model is Source and identifier == source.id else None

    monkeypatch.setattr("app.ingestion.workflow.IngestionRepository", _StubPayloadRepository)
    batch = FetchedSourceBatch(
        source=prepared,
        request_url=prepared.feed_url or "",
        final_url=prepared.feed_url or "",
        http_status=http_status,
        headers=headers,
        content_type="text/html",
        raw_text="",
        parser_warnings=(),
        parsed_items=(),
    )
    return await IngestionWorkflow().persist_source(Session(), run_id=uuid4(), batch=batch)


@pytest.mark.asyncio
async def test_error_response_validators_do_not_replace_the_stored_ones(monkeypatch):
    source = _source()
    source.etag = "good-etag"
    source.last_modified = "Tue, 12 Aug 2026 10:00:00 GMT"

    result = await _persist(
        monkeypatch,
        source,
        http_status=503,
        headers={"etag": "error-page-etag", "last-modified": "Wed, 13 Aug 2026 10:00:00 GMT"},
    )

    assert result.failed == 1
    assert source.etag == "good-etag"
    assert source.last_modified == "Tue, 12 Aug 2026 10:00:00 GMT"


@pytest.mark.asyncio
async def test_not_modified_response_still_refreshes_validators(monkeypatch):
    source = _source()
    source.etag = "old-etag"

    result = await _persist(monkeypatch, source, http_status=304, headers={"etag": "rotated-etag"})

    assert result.skipped == 1
    assert source.etag == "rotated-etag"
