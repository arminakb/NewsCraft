"""Reads must authorize through the same seam as mutations.

The middleware rule table only covers mutating methods, so GET routes used to
fall back to a scope-less ``unauthenticated-read`` principal that nothing ever
checked. These tests drive the real routers behind the real
``SecurityAuthorizationMiddleware`` with a production-shaped Settings object.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.api.dependencies as api_dependencies
from app.api.llm_providers import router as llm_router
from app.api.telegram_destinations import router as telegram_router
from app.core.config import Settings
from app.db.session import get_session


class ReadOnlySession:
    """Minimal session double: enough for the allowed-read path, nothing more."""

    def __init__(self) -> None:
        self.scalars_calls = 0

    async def scalars(self, _statement):
        self.scalars_calls += 1
        return []


def _config(**values) -> Settings:
    configured = {
        "app_env": "production",
        "application_auth_mode": "local_owner",
        "cors_origins": "http://localhost:3000,http://127.0.0.1:3000",
        "security_audit_enabled": False,
        "security_codex_token": "codex-secret",
        "security_codex_scopes": "providers:read",
        "security_internal_token": "internal-secret",
        "security_internal_scopes": "jobs:read,jobs:write",
    }
    configured.update(values)
    return Settings(_env_file=None, **configured)


def _app(session: ReadOnlySession | None = None) -> FastAPI:
    api = FastAPI()
    api.include_router(llm_router)
    api.include_router(telegram_router)
    request_session = session or ReadOnlySession()

    async def session_override():
        yield request_session

    api.dependency_overrides[get_session] = session_override
    return api


@pytest.fixture
def deployed(monkeypatch):
    def _apply(**values) -> None:
        monkeypatch.setattr(api_dependencies, "settings", _config(**values))

    return _apply


async def test_reads_fail_closed_when_the_deployment_cannot_authenticate(deployed):
    deployed(application_auth_mode="profile", cors_origins="http://localhost:3000")

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        providers = await client.get("/llm-providers")
        destinations = await client.get("/telegram/destinations")

    for response in (providers, destinations):
        assert response.status_code == 401
        assert response.json() == {"detail": {"code": "authentication_required"}}


async def test_reads_require_the_matching_read_scope(deployed):
    deployed(application_auth_mode="profile", cors_origins="http://localhost:3000")

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        # The internal service token holds jobs scopes only.
        providers = await client.get("/llm-providers", headers={"Authorization": "Bearer internal-secret"})
        destinations = await client.get(
            "/telegram/destinations", headers={"Authorization": "Bearer internal-secret"}
        )
        provider_dependencies = await client.get(
            "/llm-providers/99e6ff1f-96fb-42a7-9a94-a78a7a06539d/dependencies",
            headers={"Authorization": "Bearer internal-secret"},
        )

    for response in (providers, destinations, provider_dependencies):
        assert response.status_code == 403
        assert response.json() == {"detail": {"code": "scope_denied"}}


async def test_invalid_credentials_no_longer_downgrade_to_an_anonymous_read(deployed):
    deployed()

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.get("/llm-providers", headers={"Authorization": "Bearer wrong-secret"})

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "credential_invalid"}}


async def test_scoped_service_and_local_owner_reads_still_succeed(deployed):
    deployed()
    session = ReadOnlySession()
    api = _app(session)

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        service = await client.get("/llm-providers", headers={"Authorization": "Bearer codex-secret"})
        owner = await client.get("/llm-providers")

    assert service.status_code == 200
    assert service.json() == []
    assert owner.status_code == 200
    assert owner.json() == []
    assert session.scalars_calls == 2
