from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
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
RUN_ID = UUID("44444444-4444-4444-8444-444444444444")
CANDIDATE_ID = UUID("55555555-5555-4555-8555-555555555555")


def _policy_row(**changes):
    values = {
        "id": "global",
        "raw_payload_days": 30,
        "completed_job_days": 90,
        "attempt_metadata_days": 90,
        "export_artifact_days": 14,
        "unreferenced_media_days": 30,
        "created_at": GENERATED_AT - timedelta(days=1),
        "updated_at": GENERATED_AT,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _run_row(**changes):
    values = {
        "id": RUN_ID,
        "workflow_job_id": JOB_ID,
        "status": "queued",
        "schema_revision": "0009_operational_retention",
        "policy_snapshot": {
            "raw_payload_days": 30,
            "completed_job_days": 90,
            "attempt_metadata_days": 90,
            "export_artifact_days": 14,
            "unreferenced_media_days": 30,
        },
        "count_snapshot": {
            "export_artifact": {
                "count": 1,
                "byte_length": 120,
                "oldest_at": "2026-06-01T12:00:00Z",
                "newest_at": "2026-06-01T12:00:00Z",
            }
        },
        "error_snapshot": [],
        "previewed_at": GENERATED_AT,
        "preview_expires_at": GENERATED_AT + timedelta(minutes=30),
        "queued_at": GENERATED_AT + timedelta(minutes=1),
        "started_at": None,
        "finished_at": None,
        "created_at": GENERATED_AT,
        "updated_at": GENERATED_AT + timedelta(minutes=1),
    }
    values.update(changes)
    return SimpleNamespace(**values)


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


def test_real_application_registers_diagnostics_history_and_retention_routes():
    operations = {
        (path, method.upper())
        for path, row in app.openapi()["paths"].items()
        if path.startswith("/operations/")
        for method in row
    }

    assert operations == {
        ("/operations/diagnostics", "GET"),
        ("/operations/history", "GET"),
        ("/operations/retention-policy", "GET"),
        ("/operations/retention-policy", "PUT"),
        ("/operations/retention-preview", "POST"),
        ("/operations/retention-runs", "POST"),
        ("/operations/retention-runs", "GET"),
        ("/operations/retention-runs/{run_id}", "GET"),
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


def test_retention_policy_get_returns_persisted_policy_without_writes(api_client, monkeypatch):
    client, session = api_client
    seen: dict[str, object] = {}

    class Service:
        def __init__(self, received_session):
            seen["session"] = received_session

        async def get_policy(self):
            seen["get_policy"] = True
            return _policy_row()

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    response = client.get("/operations/retention-policy")

    assert response.status_code == 200
    assert response.json() == {
        "id": "global",
        "raw_payload_days": 30,
        "completed_job_days": 90,
        "attempt_metadata_days": 90,
        "export_artifact_days": 14,
        "unreferenced_media_days": 30,
        "created_at": "2026-07-12T12:00:00Z",
        "updated_at": "2026-07-13T12:00:00Z",
    }
    assert seen == {"session": session, "get_policy": True}
    assert session.commits == 0


def test_retention_policy_put_validates_delegates_and_commits(api_client, monkeypatch):
    client, session = api_client
    seen: dict[str, object] = {}

    class Service:
        def __init__(self, received_session):
            seen["session"] = received_session

        async def update_policy(self, value):
            seen["value"] = value.model_dump()
            return _policy_row(export_artifact_days=value.export_artifact_days)

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    response = client.put(
        "/operations/retention-policy",
        json={
            "raw_payload_days": 30,
            "completed_job_days": 90,
            "attempt_metadata_days": 90,
            "export_artifact_days": 21,
            "unreferenced_media_days": 30,
        },
    )

    assert response.status_code == 200
    assert response.json()["export_artifact_days"] == 21
    assert seen == {
        "session": session,
        "value": {
            "raw_payload_days": 30,
            "completed_job_days": 90,
            "attempt_metadata_days": 90,
            "export_artifact_days": 21,
            "unreferenced_media_days": 30,
        },
    }
    assert session.commits == 1


@pytest.mark.parametrize(
    "body",
    [
        {"export_artifact_days": 0},
        {
            "raw_payload_days": 30,
            "completed_job_days": 90,
            "attempt_metadata_days": 90,
            "export_artifact_days": 14,
            "unreferenced_media_days": 30,
            "media_root": "/client/chosen/path",
        },
    ],
)
def test_retention_policy_put_rejects_invalid_or_extra_input_before_service(
    api_client,
    monkeypatch,
    body,
):
    client, session = api_client

    class ShouldNotConstruct:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Invalid retention policy must not construct the service")

    monkeypatch.setattr(operations_api, "RetentionService", ShouldNotConstruct, raising=False)

    response = client.put("/operations/retention-policy", json=body)

    assert response.status_code == 422
    assert session.commits == 0


def test_retention_preview_persists_and_returns_public_candidate_contract(api_client, monkeypatch):
    client, session = api_client
    seen: dict[str, object] = {}

    class Service:
        def __init__(self, received_session):
            seen["session"] = received_session

        async def preview(self):
            seen["preview"] = True
            return SimpleNamespace(
                run_id=RUN_ID,
                preview_token="b" * 64,
                schema_revision="0009_operational_retention",
                policy=SimpleNamespace(
                    raw_payload_days=30,
                    completed_job_days=90,
                    attempt_metadata_days=90,
                    export_artifact_days=14,
                    unreferenced_media_days=30,
                ),
                candidates=[
                    SimpleNamespace(
                        category="export_artifact",
                        record_type="workflow_job",
                        record_id=CANDIDATE_ID,
                        operation="expire",
                        occurred_at=GENERATED_AT - timedelta(days=15),
                        byte_length=120,
                        state_hash="f" * 64,
                    )
                ],
                counts={
                    "export_artifact": SimpleNamespace(
                        count=1,
                        byte_length=120,
                        oldest_at=GENERATED_AT - timedelta(days=15),
                        newest_at=GENERATED_AT - timedelta(days=15),
                    )
                },
                previewed_at=GENERATED_AT,
                preview_expires_at=GENERATED_AT + timedelta(minutes=30),
            )

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    response = client.post("/operations/retention-preview", json={})

    assert response.status_code == 200
    assert response.json() == {
        "run_id": str(RUN_ID),
        "preview_token": "b" * 64,
        "schema_revision": "0009_operational_retention",
        "policy": {
            "raw_payload_days": 30,
            "completed_job_days": 90,
            "attempt_metadata_days": 90,
            "export_artifact_days": 14,
            "unreferenced_media_days": 30,
        },
        "candidates": [
            {
                "category": "export_artifact",
                "record_type": "workflow_job",
                "record_id": str(CANDIDATE_ID),
                "operation": "expire",
                "occurred_at": "2026-06-28T12:00:00Z",
                "byte_length": 120,
            }
        ],
        "counts": {
            "export_artifact": {
                "count": 1,
                "byte_length": 120,
                "oldest_at": "2026-06-28T12:00:00Z",
                "newest_at": "2026-06-28T12:00:00Z",
            }
        },
        "previewed_at": "2026-07-13T12:00:00Z",
        "preview_expires_at": "2026-07-13T12:30:00Z",
    }
    assert seen == {"session": session, "preview": True}
    assert session.commits == 1


@pytest.mark.parametrize(
    "body",
    [
        {"record_ids": [str(JOB_ID)]},
        {"export_root": "/client/chosen/path"},
    ],
)
def test_retention_preview_rejects_client_candidate_ids_and_paths_before_service(
    api_client,
    monkeypatch,
    body,
):
    client, session = api_client

    class ShouldNotConstruct:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Invalid retention preview input must not construct the service")

    monkeypatch.setattr(operations_api, "RetentionService", ShouldNotConstruct, raising=False)

    response = client.post("/operations/retention-preview", json=body)

    assert response.status_code == 422
    assert session.commits == 0


def test_retention_runs_list_and_detail_return_safe_audit_fields_without_preview_snapshot(
    api_client,
    monkeypatch,
):
    client, session = api_client
    seen: dict[str, object] = {}
    run = _run_row()

    class Service:
        def __init__(self, received_session):
            seen["session"] = received_session

        async def list_runs(self, limit=50):
            seen["limit"] = limit
            return [run]

        async def get_run(self, run_id):
            seen["run_id"] = run_id
            return run

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    listed = client.get("/operations/retention-runs", params={"limit": 7})
    detailed = client.get(f"/operations/retention-runs/{RUN_ID}")

    assert listed.status_code == 200
    assert listed.json() == {"items": [detailed.json()]}
    assert detailed.status_code == 200
    assert detailed.json() == {
        "id": str(RUN_ID),
        "workflow_job_id": str(JOB_ID),
        "status": "queued",
        "schema_revision": "0009_operational_retention",
        "policy": {
            "raw_payload_days": 30,
            "completed_job_days": 90,
            "attempt_metadata_days": 90,
            "export_artifact_days": 14,
            "unreferenced_media_days": 30,
        },
        "counts": {
            "export_artifact": {
                "count": 1,
                "byte_length": 120,
                "oldest_at": "2026-06-01T12:00:00Z",
                "newest_at": "2026-06-01T12:00:00Z",
            }
        },
        "errors": [],
        "previewed_at": "2026-07-13T12:00:00Z",
        "preview_expires_at": "2026-07-13T12:30:00Z",
        "queued_at": "2026-07-13T12:01:00Z",
        "started_at": None,
        "finished_at": None,
        "created_at": "2026-07-13T12:00:00Z",
        "updated_at": "2026-07-13T12:01:00Z",
    }
    assert "preview_token" not in detailed.json()
    assert "candidate_snapshot" not in detailed.json()
    assert "cleanup_intent_snapshot" not in detailed.json()
    assert seen == {"session": session, "limit": 7, "run_id": RUN_ID}
    assert session.commits == 0


def test_retention_run_detail_redacts_legacy_snapshots_without_changing_numeric_counts(
    api_client,
    monkeypatch,
):
    client, session = api_client
    run = _run_row(
        count_snapshot={
            "execution": {"deleted": 7, "byte_length": 120},
            "access_token": "retention-count-canary",
        },
        error_snapshot=[
            {
                "code": "provider_failed",
                "message": "authorization: Bearer retention-error-canary",
                "attempt": 2,
            }
        ],
    )

    class Service:
        def __init__(self, _received_session):
            pass

        async def get_run(self, _run_id):
            return run

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    response = client.get(f"/operations/retention-runs/{RUN_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert "retention-count-canary" not in response.text
    assert "retention-error-canary" not in response.text
    assert payload["counts"] == {
        "execution": {"deleted": 7, "byte_length": 120},
        "access_token": "[REDACTED]",
    }
    assert payload["errors"] == [
        {
            "code": "provider_failed",
            "message": "authorization:[REDACTED]",
            "attempt": 2,
        }
    ]
    assert session.commits == 0


def test_retention_run_detail_returns_404_when_service_has_no_run(api_client, monkeypatch):
    client, session = api_client

    class Service:
        def __init__(self, _received_session):
            pass

        async def get_run(self, _run_id):
            return None

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    response = client.get(f"/operations/retention-runs/{RUN_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Retention run not found"}
    assert session.commits == 0


def test_retention_run_detail_maps_service_not_found_to_404(api_client, monkeypatch):
    from app.retention.service import RetentionNotFound

    client, session = api_client

    class Service:
        def __init__(self, _received_session):
            pass

        async def get_run(self, _run_id):
            raise RetentionNotFound("retention run does not exist")

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    response = client.get(f"/operations/retention-runs/{RUN_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Retention run not found"}
    assert session.commits == 0


def test_retention_enqueue_accepts_only_preview_token_and_exact_confirmation(
    api_client,
    monkeypatch,
):
    client, session = api_client
    job_id = UUID("71111111-1111-4111-8111-111111111111")
    seen: dict[str, object] = {}

    class Service:
        def __init__(self, received_session):
            seen["session"] = received_session

        async def enqueue(self, *, preview_token, confirmation):
            seen["enqueue"] = (preview_token, confirmation)
            return SimpleNamespace(
                run=SimpleNamespace(id=UUID("81111111-1111-4111-8111-111111111111")),
                job=SimpleNamespace(id=job_id, status="queued"),
                created=True,
            )

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    response = client.post(
        "/operations/retention-runs",
        json={
            "preview_token": "a" * 64,
            "confirmation": "DELETE PREVIEWED DATA",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": str(job_id),
        "status": "queued",
        "deduplicated": False,
    }
    assert seen == {
        "session": session,
        "enqueue": ("a" * 64, "DELETE PREVIEWED DATA"),
    }
    assert session.commits == 1


def test_retention_enqueue_maps_stale_or_expired_preview_to_conflict(api_client, monkeypatch):
    client, session = api_client

    class Service:
        def __init__(self, _received_session):
            pass

        async def enqueue(self, **_kwargs):
            raise operations_api.RetentionConflict("Retention preview has expired")

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    response = client.post(
        "/operations/retention-runs",
        json={
            "preview_token": "a" * 64,
            "confirmation": "DELETE PREVIEWED DATA",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Retention preview has expired"}
    assert session.commits == 0


def test_retention_enqueue_maps_service_confirmation_error_to_unprocessable(
    api_client,
    monkeypatch,
):
    from app.retention.service import RetentionConfirmationError

    client, session = api_client

    class Service:
        def __init__(self, _received_session):
            pass

        async def enqueue(self, **_kwargs):
            raise RetentionConfirmationError("confirmation was rejected")

    monkeypatch.setattr(operations_api, "RetentionService", Service, raising=False)

    response = client.post(
        "/operations/retention-runs",
        json={
            "preview_token": "a" * 64,
            "confirmation": "DELETE PREVIEWED DATA",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "confirmation was rejected"}
    assert session.commits == 0


@pytest.mark.parametrize(
    "body",
    [
        {"preview_token": "a" * 64, "confirmation": "delete previewed data"},
        {"preview_token": "short", "confirmation": "DELETE PREVIEWED DATA"},
        {
            "preview_token": "a" * 64,
            "confirmation": "DELETE PREVIEWED DATA",
            "record_ids": [str(JOB_ID)],
        },
        {
            "preview_token": "a" * 64,
            "confirmation": "DELETE PREVIEWED DATA",
            "media_root": "/client/chosen/path",
        },
    ],
)
def test_retention_enqueue_rejects_confirmation_drift_client_ids_and_paths_before_service(
    api_client,
    monkeypatch,
    body,
):
    client, session = api_client

    class ShouldNotConstruct:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Invalid retention input must not construct the service")

    monkeypatch.setattr(
        operations_api,
        "RetentionService",
        ShouldNotConstruct,
        raising=False,
    )

    response = client.post("/operations/retention-runs", json=body)

    assert response.status_code == 422
    assert session.commits == 0
