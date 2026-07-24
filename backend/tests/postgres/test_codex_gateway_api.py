from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.codex_gateway as codex_api
from app.codex_gateway.credentials import GatewayCredentialHasher
from app.codex_gateway.models import CodexConnection, CodexPairingSession
from app.codex_gateway.service import CodexGatewayService, GatewayError
from app.core.config import Settings
from app.db.session import get_session
from app.main import app
from app.security.auth import TEST_ADMIN, SecurityPrincipal
from app.security.models import SecurityAuditEvent


def _config() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        codex_gateway_hash_key=base64.urlsafe_b64encode(b"g" * 32).decode(),
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


async def test_pair_heartbeat_rotate_scope_replay_and_revoke_lifecycle(
    db_session: AsyncSession,
    monkeypatch,
):
    monkeypatch.setattr(codex_api, "settings", _config())

    created = await _request(
        db_session,
        "POST",
        "/codex-gateway/pairing-sessions",
        json={"device_name": "Codex workstation"},
    )
    assert created.status_code == 201
    pairing_payload = created.json()
    pairing_code = pairing_payload["pairing_code"]
    pairing = await db_session.get(CodexPairingSession, pairing_payload["id"])
    assert pairing.code_hash != pairing_code.encode()
    assert pairing.code_prefix in pairing_code
    assert "pairing_code" not in pairing.__table__.c
    assert pairing_payload["status"] == "pending"
    assert pairing_code in pairing_payload["local_command"]

    paired = await _request(
        db_session,
        "POST",
        "/codex-gateway/pair",
        json={"pairing_code": pairing_code},
    )
    replay = await _request(
        db_session,
        "POST",
        "/codex-gateway/pair",
        json={"pairing_code": pairing_code},
    )
    assert paired.status_code == 201
    assert replay.status_code == 401
    assert replay.json() == {"detail": {"code": "pairing_code_invalid"}}
    credential = paired.json()["credential"]
    connection_id = paired.json()["connection"]["id"]
    assert paired.json()["connection"]["status"] == "gray"
    connection = await db_session.get(CodexConnection, connection_id)
    assert credential.encode() != connection.credential_hash
    assert connection.last_heartbeat_at is None

    heartbeat = await _request(
        db_session,
        "POST",
        "/codex-gateway/heartbeat",
        headers={"Authorization": f"Bearer {credential}"},
        json={"agent_version": "codex-test"},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "green"

    listed = await _request(db_session, "GET", "/codex-gateway/connections")
    capabilities = await _request(
        db_session,
        "GET",
        "/codex-gateway/capabilities",
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert listed.json()[0]["status"] == "green"
    assert all(item["risk"] == "read_only" for item in capabilities.json())
    assert all(item["granted"] for item in capabilities.json())

    service = CodexGatewayService(
        db_session,
        hasher=GatewayCredentialHasher.from_settings(_config()),
        config=_config(),
    )
    connection = await db_session.get(CodexConnection, connection_id)
    principal = SecurityPrincipal(
        "codex_service",
        str(connection.id),
        frozenset(connection.scopes),
    )
    with pytest.raises(GatewayError) as denied:
        service.require_scope(
            connection,
            principal,
            "providers:write",
            capability="future_write_tool",
        )
    await db_session.commit()
    assert denied.value.code == "scope_denied"
    errored = await _request(
        db_session,
        "GET",
        f"/codex-gateway/connections/{connection_id}",
    )
    heartbeat_with_error = await _request(
        db_session,
        "POST",
        "/codex-gateway/heartbeat",
        headers={"Authorization": f"Bearer {credential}"},
        json={},
    )
    assert errored.json()["status"] == "red"
    assert errored.json()["failure_code"] == "scope_denied"
    assert heartbeat_with_error.json()["status"] == "red"

    rotated = await _request(
        db_session,
        "POST",
        f"/codex-gateway/connections/{connection_id}/rotate",
        headers={"Idempotency-Key": "rotate-attempt-0001"},
    )
    retried = await _request(
        db_session,
        "POST",
        f"/codex-gateway/connections/{connection_id}/rotate",
        headers={"Idempotency-Key": "rotate-attempt-0001"},
    )
    rotated_credential = rotated.json()["credential"]
    assert rotated.status_code == 200
    assert retried.status_code == 200
    assert retried.json()["credential"] == rotated_credential
    assert rotated_credential != credential

    old_credential = await _request(
        db_session,
        "POST",
        "/codex-gateway/heartbeat",
        headers={"Authorization": f"Bearer {credential}"},
        json={},
    )
    new_credential = await _request(
        db_session,
        "POST",
        "/codex-gateway/heartbeat",
        headers={"Authorization": f"Bearer {rotated_credential}"},
        json={},
    )
    assert old_credential.status_code == 401
    assert old_credential.json() == {"detail": {"code": "credential_invalid"}}
    assert new_credential.status_code == 200

    scopes = await _request(
        db_session,
        "PATCH",
        f"/codex-gateway/connections/{connection_id}/scopes",
        json={
            "scopes": ["settings:read", "providers:write"],
            "confirm_write_scopes": True,
        },
    )
    assert scopes.status_code == 200
    assert scopes.json()["scopes"] == ["providers:write", "settings:read"]

    revoked = await _request(
        db_session,
        "DELETE",
        f"/codex-gateway/connections/{connection_id}",
    )
    rejected = await _request(
        db_session,
        "POST",
        "/codex-gateway/heartbeat",
        headers={"Authorization": f"Bearer {rotated_credential}"},
        json={},
    )
    assert revoked.status_code == 204
    assert rejected.status_code == 401
    assert rejected.json() == {"detail": {"code": "credential_revoked"}}

    activity = await _request(
        db_session,
        "GET",
        f"/codex-gateway/activity?connection_id={connection_id}",
    )
    assert activity.status_code == 200
    assert activity.json()
    assert pairing_code not in activity.text
    assert credential not in activity.text
    assert rotated_credential not in activity.text
    events = list(
        await db_session.scalars(
            select(SecurityAuditEvent).where(
                SecurityAuditEvent.resource_id == str(connection_id)
            )
        )
    )
    assert {event.action for event in events} >= {
        "codex_pairing.exchange",
        "codex_gateway.heartbeat",
        "codex_connection.rotate",
        "codex_connection.scopes",
        "codex_connection.revoke",
    }


async def test_rate_limit_is_database_backed_and_returns_safe_retry_metadata(
    db_session: AsyncSession,
):
    config = _config()
    service = CodexGatewayService(
        db_session,
        hasher=GatewayCredentialHasher.from_settings(config),
        config=config,
    )

    await service.consume_rate_limit(
        category="test_endpoint",
        subject="same-connection",
        limit=1,
        window_seconds=60,
        principal=TEST_ADMIN,
    )
    with pytest.raises(GatewayError) as captured:
        await service.consume_rate_limit(
            category="test_endpoint",
            subject="same-connection",
            limit=1,
            window_seconds=60,
            principal=TEST_ADMIN,
        )
    await db_session.commit()

    assert captured.value.code == "rate_limited"
    assert captured.value.status_code == 429
    assert captured.value.retry_after_seconds is not None


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
