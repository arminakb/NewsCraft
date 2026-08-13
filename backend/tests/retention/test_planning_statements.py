from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.retention.contracts import RetentionPolicyInput
from app.retention.planning import RetentionPlanner

NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)

POLICY = RetentionPolicyInput(
    raw_payload_days=30,
    completed_job_days=30,
    attempt_metadata_days=30,
    export_artifact_days=30,
    unreferenced_media_days=30,
)


class _EmptyResult:
    def __iter__(self) -> Any:
        return iter(())


class _RecordingSession:
    """Compiles every statement the planner issues without touching a database."""

    def __init__(self) -> None:
        self.sql: list[str] = []

    def _record(self, statement: Any) -> None:
        self.sql.append(str(statement.compile(dialect=postgresql.dialect())))

    async def scalars(self, statement: Any) -> _EmptyResult:
        self._record(statement)
        return _EmptyResult()

    async def execute(self, statement: Any) -> _EmptyResult:
        self._record(statement)
        return _EmptyResult()

    async def scalar(self, statement: Any) -> None:
        self._record(statement)
        return None


async def _collect_sql(*, lock: bool) -> list[str]:
    session = _RecordingSession()
    planner = RetentionPlanner(session, Path("/nonexistent-media-root"))  # type: ignore[arg-type]
    await planner._collect_candidates(POLICY, now=NOW, lock=lock)
    return session.sql


def _statements_from(sql: list[str], table: str) -> list[str]:
    return [statement for statement in sql if re.search(rf"\bFROM {table}\b", statement)]


@pytest.mark.anyio
@pytest.mark.parametrize("lock", [False, True])
async def test_attempt_protection_never_materializes_whole_tables(lock: bool) -> None:
    """Protection sets live in SQL, so no attempt table is loaded unfiltered.

    The previous implementation ran `select(ResearchAttempt)` (and the same for
    generation and publish attempts) with no WHERE clause, turned the result
    into a Python set, and fed that set to `notin_()` — one bind parameter per
    protected row, which fails outright past PostgreSQL's 65535-parameter limit.
    """
    sql = await _collect_sql(lock=lock)
    for table in ("research_attempts", "generation_attempts", "publish_attempts"):
        for statement in _statements_from(sql, table):
            assert "WHERE" in statement, f"unfiltered scan of {table}: {statement}"


@pytest.mark.anyio
async def test_attempt_statements_use_correlated_exists() -> None:
    """Each attempt family gates on EXISTS rather than an expanded id list."""
    sql = await _collect_sql(lock=False)

    research = next(statement for statement in sql if statement.startswith("SELECT research_attempts.id"))
    assert "EXISTS (SELECT 1 \nFROM research_attempts AS research_attempts_1" in research
    assert "research_attempts_1.research_run_id = research_attempts.research_run_id" in research

    generation = next(statement for statement in sql if statement.startswith("SELECT generation_attempts.id"))
    assert "EXISTS (SELECT 1 \nFROM generation_attempts AS generation_attempts_1" in generation
    assert "FROM generation_runs" in generation
    assert "FROM platform_variant_revisions" in generation

    publish = next(statement for statement in sql if statement.startswith("SELECT publish_attempts.id"))
    for correlated in ("FROM publications", "FROM publish_operation_receipts", "FROM publish_jobs"):
        assert correlated in publish
    assert "EXISTS (SELECT 1 \nFROM publish_attempts AS publish_attempts_1" in publish


@pytest.mark.anyio
async def test_completed_job_ownership_is_an_anti_join() -> None:
    """Publish/retention ownership of a workflow job is checked in SQL."""
    sql = await _collect_sql(lock=False)
    completed = next(
        statement
        for statement in sql
        if statement.startswith("SELECT workflow_jobs.id") and "workflow_jobs.finished_at <" in statement
    )
    assert "NOT (EXISTS (SELECT 1 \nFROM publish_jobs \nWHERE publish_jobs.workflow_job_id = workflow_jobs.id))" in (
        completed
    )
    assert (
        "NOT (EXISTS (SELECT 1 \nFROM retention_runs \nWHERE retention_runs.workflow_job_id = workflow_jobs.id))"
        in completed
    )


@pytest.mark.anyio
async def test_stored_media_scan_loads_only_classification_columns() -> None:
    """The media path classification reads four columns, not whole entities."""
    sql = await _collect_sql(lock=False)
    stored_media = next(
        statement for statement in sql if statement.startswith("SELECT media_assets.id, media_assets.storage_path")
    )
    assert stored_media.startswith(
        "SELECT media_assets.id, media_assets.storage_path, media_assets.created_at, media_assets.fetch_status"
    )
