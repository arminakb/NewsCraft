from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.jobs import healthcheck

NOW = datetime(2026, 7, 17, 8, 30, tzinfo=UTC)


class SessionContext:
    def __init__(self, heartbeat=None, *, failure: Exception | None = None):
        self.heartbeat = heartbeat
        self.failure = failure

    async def __aenter__(self):
        if self.failure is not None:
            raise self.failure
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, _model, _identity):
        return self.heartbeat

    async def scalar(self, _statement):
        return NOW


def _heartbeat(component_type: str, observed_at: datetime):
    return SimpleNamespace(component_type=component_type, observed_at=observed_at)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("component_type", "age", "limit", "expected"),
    [
        ("worker", 120, 120, 0),
        ("worker", 121, 120, 1),
        ("scheduler", 90, 90, 0),
        ("scheduler", 91, 90, 1),
    ],
)
async def test_component_healthcheck_uses_database_clock_and_exact_age_boundary(
    monkeypatch,
    component_type,
    age,
    limit,
    expected,
):
    session = SessionContext(_heartbeat(component_type, NOW - timedelta(seconds=age)))
    monkeypatch.setattr(healthcheck, "async_session", lambda: session)
    monkeypatch.setattr(healthcheck, "build_component_id", lambda value: value)

    assert await healthcheck.check_component(component_type, limit) == expected


@pytest.mark.asyncio
async def test_component_healthcheck_fails_closed_for_missing_wrong_or_database_failure(monkeypatch):
    monkeypatch.setattr(healthcheck, "build_component_id", lambda value: value)

    monkeypatch.setattr(healthcheck, "async_session", lambda: SessionContext())
    assert await healthcheck.check_component("worker", 120) == 1

    monkeypatch.setattr(
        healthcheck,
        "async_session",
        lambda: SessionContext(_heartbeat("scheduler", NOW)),
    )
    assert await healthcheck.check_component("worker", 120) == 1

    monkeypatch.setattr(
        healthcheck,
        "async_session",
        lambda: SessionContext(failure=RuntimeError("token=healthcheck-canary")),
    )
    assert await healthcheck.check_component("worker", 120) == 1
