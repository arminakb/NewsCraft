from contextlib import AbstractAsyncContextManager
from uuid import uuid4

import httpx
import pytest

from app.ingestion.workflow import (
    IngestionWorkflow,
    PreparedIngestionRun,
    PreparedSource,
    SourcePersistResult,
)


class _Transaction(AbstractAsyncContextManager):
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _Session:
    def begin(self):
        return _Transaction()

    def in_transaction(self):
        return False


def _prepared_source(index: int) -> PreparedSource:
    return PreparedSource(
        id=uuid4(),
        name=f"source-{index}",
        platform="rss",
        feed_url=f"https://publisher-{index}.test/feed.xml",
        telegram_username=None,
        default_timezone="UTC",
        etag=None,
        last_modified=None,
    )


class _StubWorkflow(IngestionWorkflow):
    def __init__(self, sources):
        super().__init__()
        self.sources = tuple(sources)
        self.clients_seen: list[int] = []

    async def prepare_run(self, session, *, platforms, source_ids, trigger):
        return PreparedIngestionRun(run_id=uuid4(), sources=self.sources)

    async def fetch_source(self, source, *, client=None):
        self.clients_seen.append(id(client))
        raise RuntimeError("network down")

    async def record_source_failure(self, session, *, run_id, source, error):
        return SourcePersistResult(failed=1)

    async def finish_run(self, session, *, run_id, stats):
        return None


@pytest.mark.asyncio
async def test_run_builds_one_http_client_and_shares_it_across_sources(monkeypatch):
    built: list[httpx.AsyncClient] = []
    closed: list[httpx.AsyncClient] = []

    class TrackingClient(httpx.AsyncClient):
        async def aclose(self) -> None:
            closed.append(self)
            await super().aclose()

    def build_client():
        client = TrackingClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
        built.append(client)
        return client

    monkeypatch.setattr("app.ingestion.workflow._build_http_client", build_client)

    workflow = _StubWorkflow([_prepared_source(index) for index in range(4)])
    result = await workflow.run(session=_Session(), platforms=None, source_ids=None, trigger="workflow_job")

    assert result["failed"] == 4
    assert len(built) == 1
    assert workflow.clients_seen == [id(built[0])] * 4
    assert closed == built
