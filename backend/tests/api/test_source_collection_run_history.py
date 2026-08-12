from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.api import source_collections as source_collection_api
from app.db.models import IngestRun


class _RunHistorySession:
    def __init__(self, runs: list[IngestRun]):
        self.runs = runs
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return len(self.runs)

    async def scalars(self, statement):
        self.statements.append(statement)
        limit = int(statement._limit_clause.value)  # noqa: SLF001 - focused query contract test
        offset = int(statement._offset_clause.value)  # noqa: SLF001 - focused query contract test
        return self.runs[offset : offset + limit]


@pytest.mark.asyncio
async def test_ingestion_summary_api_returns_three_latest_runs_without_source_rows(monkeypatch):
    collection_id = uuid4()
    runs = _runs(collection_id, 101)
    session = _RunHistorySession(runs)

    async def collection_exists(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(source_collection_api, "get_collection", collection_exists)

    page = await source_collection_api.list_source_collection_runs(
        collection_id,
        limit=3,
        offset=0,
        session=session,
    )

    assert page.total == 101
    assert page.limit == 3
    assert page.offset == 0
    assert page.has_more is True
    assert [item.id for item in page.items] == [run.id for run in runs[:3]]
    assert all(item.sources == [] for item in page.items)
    assert page.items[0].continuous_cycle_number == 101
    assert page.items[0].success_count == 6
    assert page.items[0].failure_count == 2
    assert page.items[0].skipped_count == 2

    list_sql = str(session.statements[-1])
    assert "ORDER BY ingest_runs.started_at DESC, ingest_runs.id DESC" in list_sql
    assert "ingest_run_source_snapshots" not in list_sql


@pytest.mark.asyncio
async def test_ingestion_summary_api_paginates_older_runs_server_side(monkeypatch):
    collection_id = uuid4()
    runs = _runs(collection_id, 101)
    session = _RunHistorySession(runs)

    async def collection_exists(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(source_collection_api, "get_collection", collection_exists)

    page = await source_collection_api.list_source_collection_runs(
        collection_id,
        limit=25,
        offset=25,
        session=session,
    )

    assert len(page.items) == 25
    assert page.total == 101
    assert page.has_more is True
    assert [item.id for item in page.items] == [run.id for run in runs[25:50]]
    assert int(session.statements[-1]._limit_clause.value) == 25  # noqa: SLF001
    assert int(session.statements[-1]._offset_clause.value) == 25  # noqa: SLF001


def _runs(collection_id, count: int) -> list[IngestRun]:
    started_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    rows = []
    for index in range(count):
        continuous = index == 0
        rows.append(
            IngestRun(
                id=uuid4(),
                started_at=started_at - timedelta(minutes=index),
                finished_at=started_at - timedelta(minutes=index) + timedelta(seconds=30),
                trigger="source_collection_continuous" if continuous else "source_collection_manual",
                parser_version="test",
                status="partial" if continuous else "succeeded",
                stats={"checked": 10, "failed": 2, "skipped": 2} if continuous else {"checked": 10},
                source_collection_id=collection_id,
                source_collection_name_at_start="AI News",
                continuous_subscription_id=uuid4() if continuous else None,
                continuous_cycle_number=count if continuous else None,
                source_count=10,
                processed_count=10,
                success_count=8 if continuous else 10,
                failure_count=2 if continuous else 0,
            )
        )
    return rows
