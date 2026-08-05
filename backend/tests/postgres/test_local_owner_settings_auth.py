from __future__ import annotations

import base64

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.llm_providers as llm_api
from app.api.llm_providers import router as llm_providers_router
from app.core.config import Settings
from app.db.session import get_session
from app.security.middleware import SecurityAuthorizationMiddleware
from app.security.models import SecurityAuditEvent
from app.security.secret_store import SecretStoreRuntime

PROVIDER_SECRET = "TEST_PROVIDER_SECRET_MUST_NOT_LEAK"


def _encoded(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def _config() -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        application_auth_mode="local_owner",
        cors_origins="http://localhost",
        secret_key_version="v1",
        secret_master_key=_encoded(7),
        security_codex_token="codex-read-only",
        security_codex_scopes="providers:read",
        security_audit_enabled=True,
    )


def _app(session_factory: async_sessionmaker[AsyncSession], config: Settings) -> FastAPI:
    api = FastAPI()
    api.state.secret_store_runtime = SecretStoreRuntime.from_settings(config)
    api.add_middleware(
        SecurityAuthorizationMiddleware,
        config=config,
        session_factory=session_factory,
    )
    api.include_router(llm_providers_router)

    async def override_session():
        async with session_factory() as session:
            session.info["enforce_api_capability_gate"] = True
            yield session

    api.dependency_overrides[get_session] = override_session
    return api


async def test_same_origin_local_owner_can_run_full_provider_lifecycle_without_operator_secret(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
    caplog,
):
    config = _config()
    monkeypatch.setattr(llm_api, "settings", config)
    api = _app(session_factory, config)
    browser = {
        "Origin": "http://localhost",
        "X-NewsCraft-Principal-Type": "human_admin",
        "X-NewsCraft-Scopes": "providers:write",
    }

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://localhost") as client:
        created = await client.post(
            "/llm-providers",
            headers=browser,
            json={"name": "Local owner provider", "protocol": "fake", "default_model": "fake-v1"},
        )
        assert created.status_code == 201
        provider_id = created.json()["id"]

        updated = await client.patch(
            f"/llm-providers/{provider_id}",
            headers=browser,
            json={"name": "Updated local owner provider"},
        )
        tested = await client.post(f"/llm-providers/{provider_id}/test", headers=browser)
        enabled = await client.post(f"/llm-providers/{provider_id}/enable", headers=browser)
        disabled = await client.post(f"/llm-providers/{provider_id}/disable", headers=browser)
        deleted = await client.delete(f"/llm-providers/{provider_id}", headers=browser)

        secret_provider = await client.post(
            "/llm-providers",
            headers=browser,
            json={
                "name": "Write-only secret provider",
                "protocol": "openai_compatible",
                "base_url": "https://llm.example/v1",
                "default_model": "vendor/model",
                "api_key": PROVIDER_SECRET,
            },
        )

    assert updated.status_code == 200
    assert tested.status_code == 200
    assert enabled.status_code == 200
    assert disabled.status_code == 200
    assert deleted.status_code == 204
    assert secret_provider.status_code == 201
    assert PROVIDER_SECRET not in secret_provider.text
    assert "api_key" not in secret_provider.json()
    assert PROVIDER_SECRET not in caplog.text

    async with session_factory() as session:
        events = list(await session.scalars(select(SecurityAuditEvent)))
    provider_events = [event for event in events if event.resource_type == "llm_provider"]
    assert provider_events
    assert {event.actor_type for event in provider_events} == {"local_owner"}
    assert {event.required_scope for event in provider_events} == {"providers:write"}
    assert PROVIDER_SECRET not in repr([
        (event.action, event.reason_code, event.event_metadata) for event in provider_events
    ])


async def test_local_owner_origin_policy_and_server_assigned_service_scopes(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    config = _config()
    monkeypatch.setattr(llm_api, "settings", config)
    api = _app(session_factory, config)

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://localhost") as client:
        missing = await client.post(
            "/llm-providers",
            json={"name": "Missing origin", "protocol": "fake", "default_model": "fake-v1"},
        )
        cross_origin = await client.post(
            "/llm-providers",
            headers={"Origin": "https://attacker.example"},
            json={"name": "Cross origin", "protocol": "fake", "default_model": "fake-v1"},
        )
        malformed = await client.post(
            "/llm-providers",
            headers={"Origin": "http://localhost:not-a-port"},
            json={"name": "Malformed origin", "protocol": "fake", "default_model": "fake-v1"},
        )
        service = await client.post(
            "/llm-providers",
            headers={
                "Authorization": "Bearer codex-read-only",
                "X-NewsCraft-Principal-Type": "human_admin",
                "X-NewsCraft-Scopes": "providers:write",
            },
            json={"name": "Spoofed service", "protocol": "fake", "default_model": "fake-v1"},
        )

    for response in (missing, cross_origin, malformed):
        assert response.status_code == 403
        assert response.json() == {"detail": {"code": "origin_validation_failed"}}
    assert service.status_code == 403
    assert service.json() == {"detail": {"code": "scope_denied"}}
