from __future__ import annotations

import base64
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.codex_gateway as codex_api
import app.api.codex_tools as codex_tools_api
from app.codex_gateway.models import CodexConnection
from app.core.config import Settings
from app.db.session import get_session
from app.main import app
from app.security.models import SecurityAuditEvent


def _config() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        codex_gateway_hash_key=base64.urlsafe_b64encode(b"m" * 32).decode(),
        codex_gateway_public_url="https://newscraft.example",
        codex_gateway_pairing_ttl_seconds=300,
        codex_gateway_credential_ttl_seconds=3600,
        codex_gateway_heartbeat_interval_seconds=30,
        codex_gateway_heartbeat_fresh_seconds=90,
        codex_gateway_heartbeat_stale_seconds=300,
        codex_gateway_rate_window_seconds=60,
        codex_gateway_pairing_create_limit=10,
        codex_gateway_pair_exchange_limit=20,
        codex_gateway_heartbeat_limit=120,
        codex_gateway_capability_limit=120,
    )


async def test_tool_rest_facade_enforces_scope_audits_and_revokes_immediately(
    db_session: AsyncSession,
    monkeypatch,
):
    config = _config()
    monkeypatch.setattr(codex_api, "settings", config)
    monkeypatch.setattr(codex_tools_api, "settings", config)
    created = await _request(
        db_session,
        "POST",
        "/codex-gateway/pairing-sessions",
        json={
            "device_name": "Codex MCP test",
            "scopes": ["providers:read"],
        },
    )
    paired = await _request(
        db_session,
        "POST",
        "/codex-gateway/pair",
        json={"pairing_code": created.json()["pairing_code"]},
    )
    credential = paired.json()["credential"]
    connection_id = paired.json()["connection"]["id"]
    authorization = {"Authorization": f"Bearer {credential}"}

    providers = await _request(
        db_session,
        "GET",
        "/codex-gateway/tools/llm-providers",
        headers=authorization,
    )
    denied = await _request(
        db_session,
        "GET",
        "/codex-gateway/tools/telegram-destinations",
        headers=authorization,
    )
    missing = await _request(
        db_session,
        "GET",
        f"/codex-gateway/tools/llm-providers/{uuid4()}",
        headers=authorization,
    )
    assert providers.status_code == 200
    assert providers.json() == []
    assert denied.status_code == 403
    assert denied.json() == {"detail": {"code": "scope_denied"}}
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"code": "capability_unavailable"}}

    events = list(
        await db_session.scalars(
            select(SecurityAuditEvent).where(
                SecurityAuditEvent.actor_id == connection_id,
                SecurityAuditEvent.action == "codex_gateway.tool_call",
            )
        )
    )
    assert {(event.outcome, event.reason_code) for event in events} >= {
        ("succeeded", None),
        ("rejected", "capability_unavailable"),
    }

    revoked = await _request(
        db_session,
        "DELETE",
        f"/codex-gateway/connections/{connection_id}",
    )
    after_revoke = await _request(
        db_session,
        "GET",
        "/codex-gateway/tools/llm-providers",
        headers=authorization,
    )
    assert revoked.status_code == 204
    assert after_revoke.status_code == 401
    assert after_revoke.json() == {"detail": {"code": "credential_revoked"}}
    assert credential not in after_revoke.text
    connection = await db_session.get(CodexConnection, connection_id)
    assert connection.status == "revoked"


async def _request(session: AsyncSession, method: str, path: str, **kwargs):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.clear()
