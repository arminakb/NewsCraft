from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.operations as operations_api
from app.db.session import get_session
from app.main import app
from app.operations.diagnostics import (
    AttentionItem,
    ComponentHealth,
    OperationsSnapshot,
)
from app.operations.history import HistoryEntry, HistoryPage

ROUTE_ID = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("22222222-2222-4222-8222-222222222222")
EVENT_ID = UUID("33333333-3333-4333-8333-333333333333")
GENERATED_AT = datetime(2026, 7, 13, 12, tzinfo=UTC)


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture
def api_client():
    session = _Session()
    api = FastAPI()
    api.include_router(operations_api.router)

    async def override_session():
        yield session

    api.dependency_overrides[get_session] = override_session
    with TestClient(api) as client:
        yield client, session


def test_real_application_registers_only_read_only_operations_routes():
    operations = {
        (path, method.upper())
        for path, row in app.openapi()["paths"].items()
        if path.startswith("/operations/")
        for method in row
    }

    assert operations == {
        ("/operations/diagnostics", "GET"),
        ("/operations/history", "GET"),
    }


def test_diagnostics_route_returns_the_strict_snapshot_without_writes(api_client, monkeypatch):
    client, session = api_client
    seen: dict[str, object] = {}

    class FakeDiagnostics:
        def __init__(self, received_session):
            seen["session"] = received_session

        async def snapshot(self):
            seen["snapshot_calls"] = int(seen.get("snapshot_calls", 0)) + 1
            return OperationsSnapshot(
                generated_at=GENERATED_AT,
                global_paused=False,
                dry_run=True,
                components={
                    "worker-source-generation": ComponentHealth(
                        status="degraded",
                        observed_at=datetime(2026, 7, 13, 11, 59, 25, tzinfo=UTC),
                        last_success_at=None,
                        message="Last observed 35 seconds ago",
                        action_url="/jobs",
                    )
                },
                queue_counts={"queued": 2, "running": 1, "attention": 3},
                attention=[
                    AttentionItem(
                        id=f"job:{JOB_ID}",
                        severity="warning",
                        kind="job",
                        title="Generation needs review",
                        occurred_at=datetime(2026, 7, 13, 11, tzinfo=UTC),
                        action_url="/jobs",
                    )
                ],
            )

    monkeypatch.setattr(operations_api, "OperationsDiagnostics", FakeDiagnostics, raising=False)

    response = client.get("/operations/diagnostics")

    assert response.status_code == 200
    assert response.json() == {
        "generated_at": "2026-07-13T12:00:00Z",
        "global_paused": False,
        "dry_run": True,
        "components": {
            "worker-source-generation": {
                "status": "degraded",
                "observed_at": "2026-07-13T11:59:25Z",
                "last_success_at": None,
                "message": "Last observed 35 seconds ago",
                "action_url": "/jobs",
            }
        },
        "queue_counts": {"queued": 2, "running": 1, "attention": 3},
        "attention": [
            {
                "id": f"job:{JOB_ID}",
                "severity": "warning",
                "kind": "job",
                "title": "Generation needs review",
                "occurred_at": "2026-07-13T11:00:00Z",
                "action_url": "/jobs",
            }
        ],
    }
    assert seen == {"session": session, "snapshot_calls": 1}
    assert session.commits == 0


def test_history_route_delegates_all_filters_and_returns_the_strict_page(api_client, monkeypatch):
    client, session = api_client
    seen: dict[str, object] = {}

    class FakeHistoryService:
        def __init__(self, received_session):
            seen["session"] = received_session

        async def list(self, **filters):
            seen["filters"] = filters
            return HistoryPage(
                items=[
                    HistoryEntry(
                        id=str(EVENT_ID),
                        occurred_at=GENERATED_AT,
                        category="publish",
                        status="succeeded",
                        title="Telegram publication succeeded",
                        summary="The exact approved revision was published.",
                        job_id=JOB_ID,
                        subject_url=f"/automations/{ROUTE_ID}",
                        sanitized_metadata={"operation_count": 2},
                    )
                ],
                next_cursor="stable-next-cursor",
            )

    def fake_decode_history_cursor(cursor):
        seen["decoded_cursor"] = cursor
        return GENERATED_AT, EVENT_ID

    monkeypatch.setattr(operations_api, "HistoryService", FakeHistoryService, raising=False)
    monkeypatch.setattr(
        operations_api,
        "decode_history_cursor",
        fake_decode_history_cursor,
        raising=False,
    )

    response = client.get(
        "/operations/history",
        params={
            "subject_type": "automation_route",
            "subject_id": str(ROUTE_ID),
            "category": "publish",
            "status": "succeeded",
            "cursor": "stable-input-cursor",
            "limit": 7,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(EVENT_ID),
                "occurred_at": "2026-07-13T12:00:00Z",
                "category": "publish",
                "status": "succeeded",
                "title": "Telegram publication succeeded",
                "summary": "The exact approved revision was published.",
                "job_id": str(JOB_ID),
                "subject_url": f"/automations/{ROUTE_ID}",
                "sanitized_metadata": {"operation_count": 2},
            }
        ],
        "next_cursor": "stable-next-cursor",
    }
    assert seen == {
        "session": session,
        "decoded_cursor": "stable-input-cursor",
        "filters": {
            "subject_type": "automation_route",
            "subject_id": ROUTE_ID,
            "category": "publish",
            "status": "succeeded",
            "cursor": "stable-input-cursor",
            "limit": 7,
        },
    }
    assert session.commits == 0


@pytest.mark.parametrize(
    "params",
    [
        {"subject_type": ""},
        {"subject_type": "route!"},
        {"subject_type": "route"},
        {"subject_type": "r" * 65},
        {"subject_type": "automation_route"},
        {"subject_id": str(ROUTE_ID)},
        {"subject_id": "not-a-uuid"},
        {"category": "other"},
        {"status": ""},
        {"status": "s" * 65},
        {"cursor": ""},
        {"cursor": "not-a-valid-history-cursor"},
        {"limit": 0},
        {"limit": 101},
    ],
)
def test_history_route_rejects_invalid_filters_before_query(api_client, monkeypatch, params):
    client, _session = api_client

    class ShouldNotQuery:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("invalid history filters must not construct the service")

    monkeypatch.setattr(operations_api, "HistoryService", ShouldNotQuery, raising=False)

    response = client.get("/operations/history", params=params)

    assert response.status_code == 422
