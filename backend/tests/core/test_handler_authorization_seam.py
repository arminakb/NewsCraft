"""Every router authorizes through the one shared in-handler seam.

The automation and codex-gateway routers used to carry private copies of the
"resolve a principal, then check a scope" helper, each with its own denial code
and its own idea of what counts as a mutation. They now delegate to
``app.api.dependencies``; these tests drive the real routers with a
production-shaped Settings object to pin the behaviour that must not drift:
authentication failures, the per-surface denial code, and the read-only POST
whose scope check is authoritative because the middleware rule table skips it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.api.dependencies as api_dependencies
from app.api.automations import router as automations_router
from app.api.codex_gateway import router as codex_router
from app.core.config import Settings
from app.db.session import get_session

CATALOG_BODY = {"resources": [{"kind": "provider", "id": "5e1b0e2e-2c0f-4a4b-9a08-0d6b0a1f4d21"}]}


class EmptySession:
    """Minimal session double: enough for an allowed empty read, nothing more."""

    async def scalars(self, _statement):
        return []

    async def execute(self, _statement):  # pragma: no cover - defensive
        raise AssertionError("these routes must not reach a write")


def _config(**values) -> Settings:
    configured = {
        "app_env": "production",
        "application_auth_mode": "local_owner",
        "cors_origins": "http://localhost:3000",
        "security_audit_enabled": False,
        "security_codex_token": "codex-secret",
        "security_codex_scopes": "automations:read",
        "security_internal_token": "internal-secret",
        "security_internal_scopes": "jobs:read,jobs:write",
    }
    configured.update(values)
    return Settings(_env_file=None, **configured)


def _app() -> FastAPI:
    api = FastAPI()
    api.include_router(automations_router)
    api.include_router(codex_router)

    async def session_override():
        yield EmptySession()

    api.dependency_overrides[get_session] = session_override
    return api


@pytest.fixture
def deployed(monkeypatch):
    def _apply(**values) -> None:
        monkeypatch.setattr(api_dependencies, "settings", _config(**values))

    return _apply


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test")


async def test_automation_reads_keep_publishing_insufficient_permission(deployed, client):
    deployed()

    async with client:
        response = await client.get(
            "/automations", headers={"Authorization": "Bearer internal-secret"}
        )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "insufficient_permission"}}


async def test_read_only_post_still_enforces_the_read_scope(deployed, client):
    # /automation-resource-catalog is in UNRULED_MUTATION_PATHS, so the
    # middleware never checks it: the route-level scope check is the only one.
    deployed()

    async with client:
        response = await client.post(
            "/automation-resource-catalog",
            json=CATALOG_BODY,
            headers={"Authorization": "Bearer internal-secret"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "insufficient_permission"}}


async def test_read_only_post_does_not_demand_an_origin_from_the_local_owner(deployed, client):
    # Classified as a read at this seam, so local-owner access needs no Origin
    # header even though the HTTP method is POST.
    deployed(security_codex_scopes="automations:read,providers:read")

    async with client:
        response = await client.post("/automation-resource-catalog", json={"resources": []})

    assert response.status_code == 200
    assert response.json() == {"resources": []}


async def test_automation_reads_fail_closed_without_credentials(deployed, client):
    deployed(application_auth_mode="profile")

    async with client:
        response = await client.get("/automations")

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "authentication_required"}}


async def test_gateway_reads_keep_publishing_scope_denied(deployed, client):
    deployed()

    async with client:
        response = await client.get(
            "/codex-gateway/connections/1c6f3a5e-9d0f-4f4a-9b56-2f5a1b0c7d34",
            headers={"Authorization": "Bearer internal-secret"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "scope_denied"}}


async def test_gateway_reads_fail_closed_on_invalid_credentials(deployed, client):
    deployed()

    async with client:
        response = await client.get(
            "/codex-gateway/connections/1c6f3a5e-9d0f-4f4a-9b56-2f5a1b0c7d34",
            headers={"Authorization": "Bearer wrong-secret"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "credential_invalid"}}
