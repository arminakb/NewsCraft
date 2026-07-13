from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.main import app


def _evidence(
    *,
    snapshot_id: UUID | None = None,
    captured_at: datetime | None = None,
    content_text: str = "Evidence text",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=snapshot_id or uuid4(),
        story_id=uuid4(),
        content_item_id=uuid4(),
        evidence_key="url:https://example.com/report:" + "a" * 64,
        title="Persisted evidence",
        source_url="https://example.com/report",
        authors=["Reporter"],
        published_at=datetime(2026, 7, 12, 8, tzinfo=UTC),
        captured_at=captured_at or datetime(2026, 7, 13, 8, tzinfo=UTC),
        content_sha256="b" * 64,
        content_text=content_text,
    )


def _original(
    *,
    content_item_id: UUID | None = None,
    sort_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=content_item_id or uuid4(),
        title="Persisted original",
        status="approved",
        source_id=uuid4(),
        source_name="Wire Desk",
        source_url="https://example.com/original",
        published_at=datetime(2026, 7, 12, 8, tzinfo=UTC),
        sort_at=sort_at or datetime(2026, 7, 13, 8, tzinfo=UTC),
    )


class _Rows:
    def __init__(self, rows: list[SimpleNamespace]):
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _OriginalSession:
    def __init__(self, rows: list[SimpleNamespace]):
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        params = statement.compile().params
        cursor_times = [value for value in params.values() if isinstance(value, datetime)]
        cursor_ids = [value for value in params.values() if isinstance(value, UUID)]
        rows = sorted(self.rows, key=lambda row: (row.sort_at, row.id), reverse=True)
        if cursor_times and cursor_ids:
            cursor = (cursor_times[0], cursor_ids[-1])
            rows = [row for row in rows if (row.sort_at, row.id) < cursor]
        return _Rows(rows[: statement._limit_clause.value])


class _EvidenceSession:
    def __init__(self, rows: list[SimpleNamespace]):
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        params = statement.compile().params
        cursor_times = [value for value in params.values() if isinstance(value, datetime)]
        cursor_ids = [value for value in params.values() if isinstance(value, UUID)]
        rows = sorted(self.rows, key=lambda row: (row.captured_at, row.id), reverse=True)
        if cursor_times and cursor_ids:
            cursor = (cursor_times[0], cursor_ids[-1])
            rows = [row for row in rows if (row.captured_at, row.id) < cursor]
        limit = statement._limit_clause.value
        return _Rows(rows[:limit])


def _research_run(
    *,
    run_id: UUID | None = None,
    created_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id or uuid4(),
        story_id=uuid4(),
        requested_mode="manual",
        backend="openrouter",
        status="succeeded",
        query_budget=4,
        page_budget=8,
        time_budget_seconds=120,
        created_at=created_at or datetime(2026, 7, 13, 8, tzinfo=UTC),
        started_at=None,
        finished_at=None,
        attempt_count=1,
        source_count=2,
        result_story_revision_id=None,
        error_summary=None,
    )


class _ResearchSession:
    def __init__(self, rows: list[SimpleNamespace]):
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        params = statement.compile().params
        cursor_times = [value for value in params.values() if isinstance(value, datetime)]
        cursor_ids = [value for value in params.values() if isinstance(value, UUID)]
        rows = sorted(self.rows, key=lambda row: (row.created_at, row.id), reverse=True)
        if cursor_times and cursor_ids:
            cursor = (cursor_times[0], cursor_ids[-1])
            rows = [row for row in rows if (row.created_at, row.id) < cursor]
        limit = statement._limit_clause.value
        return _Rows(rows[:limit])


def test_library_routes_are_registered_as_read_only_gets():
    operations = {
        (path, method.upper())
        for path, row in app.openapi()["paths"].items()
        for method in row
    }
    assert ("/library/evidence", "GET") in operations
    assert ("/library/originals", "GET") in operations
    assert ("/library/research-runs", "GET") in operations
    assert ("/library/research-runs/{run_id}", "GET") in operations
    assert not any(
        path.startswith("/library/") and method != "GET"
        for path, method in operations
    )


@pytest.mark.asyncio
async def test_originals_cursor_remains_stable_when_a_newer_row_is_inserted_between_pages():
    from app.api.library import list_library_originals

    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    original = [_original(sort_at=now - timedelta(minutes=index)) for index in range(3)]
    session = _OriginalSession(original)

    first = await list_library_originals(cursor=None, limit=1, session=session)
    inserted = _original(sort_at=now + timedelta(minutes=1))
    session.rows.append(inserted)
    second = await list_library_originals(cursor=first.next_cursor, limit=2, session=session)

    assert [item.id for item in first.items] == [original[0].id]
    assert [item.id for item in second.items] == [original[1].id, original[2].id]
    assert inserted.id not in {item.id for item in second.items}
    assert not ({item.id for item in first.items} & {item.id for item in second.items})
    assert first.items[0].model_dump().keys() == {
        "id",
        "title",
        "status",
        "source_id",
        "source_name",
        "source_url",
        "published_at",
        "sort_at",
    }


def test_originals_statement_uses_compound_persisted_order_without_raw_content():
    from app.api.library import original_statement

    cursor_at, cursor_id = datetime(2026, 7, 13, 9, tzinfo=UTC), uuid4()
    sql = str(
        original_statement(cursor=(cursor_at, cursor_id), limit=50).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "content_items.sort_at <" in sql
    assert "content_items.id <" in sql
    assert "ORDER BY content_items.sort_at DESC, content_items.id DESC" in sql
    assert "LIMIT 51" in sql
    assert "content_text" not in sql
    assert "content_html_sanitized" not in sql
    assert "classification_metadata" not in sql


def test_library_cursor_round_trips_compound_identity_and_rejects_tampering():
    from app.api.library import decode_library_cursor, encode_library_cursor

    timestamp = datetime(2026, 7, 13, 7, 2, 3, 456789, tzinfo=UTC)
    row_id = uuid4()
    cursor = encode_library_cursor(timestamp, row_id)

    assert decode_library_cursor(cursor) == (timestamp, row_id)
    with pytest.raises(ValueError, match="invalid library cursor"):
        decode_library_cursor(cursor + "not-valid")


def test_evidence_projection_normalizes_and_clamps_excerpt_without_raw_payload():
    from app.api.library import evidence_out

    raw = "  First\n\tline   " + "x" * 600
    output = evidence_out(_evidence(content_text=raw)).model_dump(mode="json")

    assert len(output["excerpt"]) == 500
    assert output["excerpt"].startswith("First line ")
    assert "\n" not in output["excerpt"]
    assert set(output) == {
        "id",
        "story_id",
        "content_item_id",
        "evidence_key",
        "title",
        "source_url",
        "authors",
        "published_at",
        "captured_at",
        "content_sha256",
        "excerpt",
    }
    assert "content_text" not in output
    assert "snapshot_metadata" not in output


def test_evidence_projection_does_not_leave_whitespace_at_clamp_boundary():
    from app.api.library import evidence_out

    raw = "  " + ("x" * 499) + " \n next word  "
    excerpt = evidence_out(_evidence(content_text=raw)).excerpt

    assert excerpt == "x" * 499
    assert len(excerpt) <= 500
    assert excerpt == " ".join(excerpt.split())


@pytest.mark.asyncio
async def test_evidence_cursor_remains_stable_when_a_newer_row_is_inserted_between_pages():
    from app.api.library import list_library_evidence

    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    original = [
        _evidence(captured_at=now - timedelta(minutes=index))
        for index in range(3)
    ]
    session = _EvidenceSession(original)

    first = await list_library_evidence(
        cursor=None,
        story_id=None,
        source_id=None,
        limit=1,
        session=session,
    )
    inserted = _evidence(captured_at=now + timedelta(minutes=1))
    session.rows.append(inserted)
    second = await list_library_evidence(
        cursor=first.next_cursor,
        story_id=None,
        source_id=None,
        limit=2,
        session=session,
    )

    assert [item.id for item in first.items] == [original[0].id]
    assert [item.id for item in second.items] == [original[1].id, original[2].id]
    assert inserted.id not in {item.id for item in second.items}
    assert not ({item.id for item in first.items} & {item.id for item in second.items})


def test_evidence_statement_uses_persisted_filters_and_compound_keyset_order():
    from app.api.library import evidence_statement

    story_id, source_id, cursor_id = uuid4(), uuid4(), uuid4()
    cursor_at = datetime(2026, 7, 13, 9, tzinfo=UTC)
    sql = str(
        evidence_statement(
            cursor=(cursor_at, cursor_id),
            story_id=story_id,
            source_id=source_id,
            limit=50,
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "story_evidence_snapshots.story_id =" in sql
    assert "content_items.primary_source_id =" in sql
    assert "story_evidence_snapshots.captured_at <" in sql
    assert "story_evidence_snapshots.id <" in sql
    assert "ORDER BY story_evidence_snapshots.captured_at DESC, story_evidence_snapshots.id DESC" in sql
    assert "LIMIT 51" in sql


def test_research_projection_is_persisted_bounded_and_secret_safe():
    from app.api.library import research_run_out

    row = SimpleNamespace(
        id=uuid4(),
        story_id=uuid4(),
        requested_mode="manual",
        backend="openrouter",
        status="failed",
        query_budget=4,
        page_budget=8,
        time_budget_seconds=120,
        created_at=datetime(2026, 7, 13, 8, tzinfo=UTC),
        started_at=datetime(2026, 7, 13, 8, 1, tzinfo=UTC),
        finished_at=datetime(2026, 7, 13, 8, 2, tzinfo=UTC),
        attempt_count=2,
        source_count=3,
        result_story_revision_id=None,
        error_summary="Bearer top-secret api_key=also-secret provider response failed " + "x" * 600,
        secret_ref="env:OPENROUTER_API_KEY",
        response_body={"private": True},
    )

    output = research_run_out(row).model_dump(mode="json")

    assert output["backend"] == "openrouter"
    assert output["budget"] == {
        "max_queries": 4,
        "max_pages": 8,
        "max_elapsed_seconds": 120,
    }
    assert output["attempt_count"] == 2
    assert output["source_count"] == 3
    assert "top-secret" not in (output["error_summary"] or "")
    assert "also-secret" not in (output["error_summary"] or "")
    assert len(output["error_summary"] or "") <= 500
    assert "[REDACTED]" in (output["error_summary"] or "")
    assert "secret_ref" not in output
    assert "response_body" not in output


@pytest.mark.asyncio
async def test_exact_research_route_returns_the_same_safe_projection_and_404s_missing_rows():
    from app.api.library import get_library_research_run

    run = _research_run()
    found = _ResearchSession([run])
    missing = _ResearchSession([])

    output = await get_library_research_run(run_id=run.id, session=found)
    assert output.id == run.id
    assert output.story_id == run.story_id
    assert output.result_story_revision_id is None
    assert output.model_dump().keys() == {
        "id",
        "story_id",
        "requested_mode",
        "backend",
        "status",
        "budget",
        "created_at",
        "started_at",
        "finished_at",
        "attempt_count",
        "source_count",
        "result_story_revision_id",
        "error_summary",
    }
    exact_sql = str(
        found.statements[-1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert f"research_runs.id = '{run.id}'" in exact_sql
    with pytest.raises(HTTPException) as error:
        await get_library_research_run(run_id=uuid4(), session=missing)
    assert error.value.status_code == 404


def test_research_statement_filters_only_persisted_values_and_uses_compound_cursor():
    from app.api.library import research_run_statement

    story_id, cursor_id = uuid4(), uuid4()
    cursor_at = datetime(2026, 7, 13, 9, tzinfo=UTC)
    sql = str(
        research_run_statement(
            cursor=(cursor_at, cursor_id),
            story_id=story_id,
            status="failed",
            backend="openrouter",
            limit=50,
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "research_runs.story_id =" in sql
    assert "research_runs.status = 'failed'" in sql
    assert "ai_provider_profiles.provider_type = 'openrouter'" in sql
    assert "research_runs.created_at <" in sql
    assert "research_runs.id <" in sql
    assert "ORDER BY research_runs.created_at DESC, research_runs.id DESC" in sql
    assert "LIMIT 51" in sql
    assert "secret_ref" not in sql
    assert "response_body" not in sql


@pytest.mark.asyncio
async def test_research_cursor_remains_stable_when_a_newer_row_is_inserted_between_pages():
    from app.api.library import list_library_research_runs

    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    original = [
        _research_run(created_at=now - timedelta(minutes=index))
        for index in range(3)
    ]
    session = _ResearchSession(original)

    first = await list_library_research_runs(
        cursor=None,
        story_id=None,
        status=None,
        backend=None,
        limit=1,
        session=session,
    )
    inserted = _research_run(created_at=now + timedelta(minutes=1))
    session.rows.append(inserted)
    second = await list_library_research_runs(
        cursor=first.next_cursor,
        story_id=None,
        status=None,
        backend=None,
        limit=2,
        session=session,
    )

    assert [item.id for item in first.items] == [original[0].id]
    assert [item.id for item in second.items] == [original[1].id, original[2].id]
    assert inserted.id not in {item.id for item in second.items}
    assert not ({item.id for item in first.items} & {item.id for item in second.items})


@pytest.mark.asyncio
async def test_routes_apply_cursor_filters_and_limit_to_the_database_projection():
    from app.api.library import (
        encode_library_cursor,
        list_library_evidence,
        list_library_research_runs,
    )

    cursor_at, cursor_id = datetime(2026, 7, 13, 9, tzinfo=UTC), uuid4()
    cursor = encode_library_cursor(cursor_at, cursor_id)
    story_id, source_id = uuid4(), uuid4()
    evidence_session = _EvidenceSession([])
    research_session = _ResearchSession([])

    await list_library_evidence(
        cursor=cursor,
        story_id=story_id,
        source_id=source_id,
        limit=7,
        session=evidence_session,
    )
    await list_library_research_runs(
        cursor=cursor,
        story_id=story_id,
        status="failed",
        backend="openrouter",
        limit=9,
        session=research_session,
    )

    evidence_sql = str(
        evidence_session.statements[-1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    research_sql = str(
        research_session.statements[-1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert str(story_id) in evidence_sql and str(source_id) in evidence_sql
    assert "LIMIT 8" in evidence_sql
    assert "captured_at <" in evidence_sql and "story_evidence_snapshots.id <" in evidence_sql
    assert str(story_id) in research_sql
    assert "research_runs.status = 'failed'" in research_sql
    assert "ai_provider_profiles.provider_type = 'openrouter'" in research_sql
    assert "LIMIT 10" in research_sql
    assert "created_at <" in research_sql and "research_runs.id <" in research_sql


@pytest.mark.asyncio
async def test_invalid_cursors_fail_before_any_database_query():
    from app.api.library import (
        list_library_evidence,
        list_library_originals,
        list_library_research_runs,
    )

    class Session:
        async def execute(self, _statement):
            raise AssertionError("invalid cursor must not query")

    with pytest.raises(HTTPException) as originals_error:
        await list_library_originals(cursor="not-a-cursor", limit=50, session=Session())
    with pytest.raises(HTTPException) as evidence_error:
        await list_library_evidence(
            cursor="not-a-cursor",
            story_id=None,
            source_id=None,
            limit=50,
            session=Session(),
        )
    with pytest.raises(HTTPException) as research_error:
        await list_library_research_runs(
            cursor="not-a-cursor",
            story_id=None,
            status=None,
            backend=None,
            limit=50,
            session=Session(),
        )

    assert originals_error.value.status_code == 422
    assert evidence_error.value.status_code == 422
    assert research_error.value.status_code == 422
