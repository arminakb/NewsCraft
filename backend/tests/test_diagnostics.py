from datetime import UTC, datetime
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.db.models import Source
from app.db.session import get_session
from app.diagnostics.service import DiagnosticsService
from app.main import app

CHECKED_AT = datetime(2026, 7, 6, tzinfo=UTC)


class FakeSession:
    def __init__(self, sources=None):
        self.sources = sources or []

    async def execute(self, *_args, **_kwargs):
        return None

    async def scalars(self, *_args, **_kwargs):
        return self.sources


async def _override_session():
    yield FakeSession()


async def test_diagnostics_endpoint_reports_database_and_source_support():
    app.dependency_overrides[get_session] = _override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/diagnostics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["database"] == "ok"
    assert payload["checks"]["rss_parser"] == "ok"
    assert payload["checks"]["telegram_public_parser"] == "ok"


async def test_diagnostics_summarizes_source_health_counts():
    sources = [
        _source("Healthy", "healthy"),
        _source("Slow", "degraded"),
        _source("Gone", "broken", failure_count=2, error_type="http_404"),
        _source("Disabled", "disabled", active=False, disabled_reason="manual"),
    ]

    payload = await DiagnosticsService(FakeSession(sources)).check()

    assert payload["status"] == "degraded"
    assert payload["checks"]["source_health"] == "degraded"
    assert payload["source_health"] == {
        "healthy": 1,
        "degraded": 1,
        "broken": 1,
        "disabled": 1,
        "unknown": 0,
        "total": 4,
    }
    assert payload["problem_sources"][0]["name"] == "Gone"
    assert payload["problem_sources"][0]["health_status"] == "broken"
    assert payload["problem_sources"][0]["last_error_type"] == "http_404"


async def test_diagnostics_marks_active_never_checked_sources_unknown():
    source = _source("Never Checked", "healthy", last_fetch_at=None)

    payload = await DiagnosticsService(FakeSession([source])).check()

    assert payload["status"] == "degraded"
    assert payload["checks"]["source_health"] == "degraded"
    assert payload["source_health"] == {
        "healthy": 0,
        "degraded": 0,
        "broken": 0,
        "disabled": 0,
        "unknown": 1,
        "total": 1,
    }
    assert payload["problem_sources"][0]["name"] == "Never Checked"
    assert payload["problem_sources"][0]["health_status"] == "unknown"


async def test_diagnostics_service_redacts_legacy_problem_source_fields():
    source = _source(
        "Legacy api_key=diagnostic-name-canary",
        "broken",
        failure_count=1,
        error_type="auth_token=diagnostic-type-canary",
    )
    source.last_error_message = 'failure {"authorization":"Bearer diagnostic-message-canary"}'
    source.disabled_reason = "password=diagnostic-disabled-canary"

    payload = await DiagnosticsService(FakeSession([source])).check()

    rendered = str(payload["problem_sources"])
    assert "diagnostic-name-canary" not in rendered
    assert "diagnostic-type-canary" not in rendered
    assert "diagnostic-message-canary" not in rendered
    assert "diagnostic-disabled-canary" not in rendered
    assert "[REDACTED]" in rendered


async def test_diagnostics_route_redacts_legacy_problem_source_fields():
    source = _source(
        "Route api_key=diagnostic-route-name-canary",
        "broken",
        failure_count=1,
        error_type="auth_token=diagnostic-route-type-canary",
    )
    source.last_error_message = 'failure {"authorization":"Bearer diagnostic-route-message-canary"}'

    async def override():
        yield FakeSession([source])

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/diagnostics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    rendered = str(response.json()["problem_sources"])
    assert "diagnostic-route-name-canary" not in rendered
    assert "diagnostic-route-type-canary" not in rendered
    assert "diagnostic-route-message-canary" not in rendered
    assert "[REDACTED]" in rendered


async def test_diagnostics_reports_failed_source_health_query():
    payload = await DiagnosticsService(BrokenSession()).check()

    assert payload["status"] == "degraded"
    assert payload["checks"]["database"] == "failed"
    assert payload["checks"]["source_health"] == "failed"
    assert payload["source_health"]["total"] == 0
    assert payload["problem_sources"] == []


class BrokenSession:
    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("database down")

    async def scalars(self, *_args, **_kwargs):
        raise RuntimeError("database down")


def _source(
    name: str,
    health_status: str,
    *,
    active: bool = True,
    failure_count: int = 0,
    error_type: str | None = None,
    disabled_reason: str | None = None,
    last_fetch_at: datetime | None = CHECKED_AT,
) -> Source:
    return Source(
        id=uuid4(),
        platform="rss",
        name=name,
        feed_url=f"https://example.com/{name}.xml",
        source_group="ai",
        active=active,
        health_status=health_status,
        failure_count=failure_count,
        last_error_type=error_type,
        disabled_reason=disabled_reason,
        last_fetch_at=last_fetch_at,
    )
