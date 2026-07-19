from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.health as health_api
from app.db.session import get_session
from app.operations.health import DependencyHealth, HealthState, ReadinessSnapshot

NOW = datetime(2026, 7, 17, 8, 30, tzinfo=UTC)


def _api():
    api = FastAPI()
    api.include_router(health_api.router)

    async def dependency_must_not_run_for_liveness():
        raise AssertionError("liveness performed dependency IO")
        yield  # pragma: no cover

    api.dependency_overrides[get_session] = dependency_must_not_run_for_liveness
    return api


def _snapshot(ready: bool) -> ReadinessSnapshot:
    state = HealthState.HEALTHY if ready else HealthState.UNAVAILABLE
    return ReadinessSnapshot(
        status="ready" if ready else "unavailable",
        generated_at=NOW,
        checks={
            "database": DependencyHealth(
                state=state,
                code="database_connected" if ready else "database_unavailable",
                observed_at=NOW,
                latency_ms=1,
                message="Database connectivity is available" if ready else "Database connectivity is unavailable",
                runbook_url="/docs/operations/readiness-and-health#database-unavailable",
            )
        },
        required_capabilities=(),
    )


def test_liveness_is_process_only_and_keeps_legacy_alias():
    api = _api()
    with TestClient(api) as client:
        assert client.get("/health/live").json() == {"status": "alive"}
        assert client.get("/health").json() == {"status": "ok"}


def test_readiness_returns_200_or_503_from_dependency_state(monkeypatch):
    api = FastAPI()
    api.include_router(health_api.router)

    async def session_override():
        yield object()

    api.dependency_overrides[get_session] = session_override

    class FakeReadiness:
        result = _snapshot(True)

        def __init__(self, _session):
            pass

        async def snapshot(self):
            return self.result

    monkeypatch.setattr(health_api, "ReadinessService", FakeReadiness)
    with TestClient(api) as client:
        assert client.get("/health/ready").status_code == 200
        FakeReadiness.result = _snapshot(False)
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"
