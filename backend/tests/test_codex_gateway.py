from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.codex_gateway.credentials import GatewayCredentialHasher, GatewayKeyUnavailable
from app.codex_gateway.models import CodexConnection
from app.codex_gateway.schemas import (
    READ_ONLY_SCOPES,
    ConnectionScopesPatch,
    PairingSessionCreate,
)
from app.codex_gateway.service import connection_status
from app.core.config import Settings
from app.security.middleware import mutation_rule


def _key() -> bytes:
    return bytes(range(32))


def _encoded_key(*, padded: bool = True) -> str:
    value = base64.urlsafe_b64encode(_key()).decode()
    return value if padded else value.rstrip("=")


def _connection(now: datetime) -> CodexConnection:
    return CodexConnection(
        id=uuid4(),
        device_name="Codex workstation",
        credential_prefix="abcdefghijkl",
        credential_hash=b"x" * 32,
        credential_fingerprint="f" * 16,
        scopes=["settings:read"],
        status="active",
        expires_at=now + timedelta(hours=1),
        pairing_session_id=uuid4(),
        created_at=now,
        updated_at=now,
    )


def test_gateway_hasher_issues_parseable_hash_only_values_and_supports_unpadded_keys():
    config = Settings(
        _env_file=None,
        app_env="test",
        codex_gateway_hash_key=_encoded_key(padded=False),
    )
    hasher = GatewayCredentialHasher.from_settings(config)

    code, prefix, digest = hasher.issue_pairing_code()
    credential = hasher.issue_credential()

    assert hasher.parse_pairing_prefix(code) == prefix
    assert hasher.matches("pairing-code", code, digest)
    assert code.encode() not in digest
    assert hasher.parse_credential_prefix(credential.value) == credential.prefix
    assert hasher.matches("credential", credential.value, credential.digest)
    assert credential.value.encode() not in credential.digest
    assert hasher.issue_credential(seed="same-retry") == hasher.issue_credential(
        seed="same-retry"
    )
    assert hasher.issue_credential(seed="same-retry") != hasher.issue_credential(
        seed="different-retry"
    )


def test_gateway_hasher_fails_closed_without_exactly_32_bytes():
    unavailable = Settings(
        _env_file=None,
        app_env="test",
        codex_gateway_hash_key=None,
    )
    malformed = Settings(
        _env_file=None,
        app_env="test",
        codex_gateway_hash_key=base64.urlsafe_b64encode(b"short").decode(),
    )

    with pytest.raises(GatewayKeyUnavailable):
        GatewayCredentialHasher.from_settings(unavailable)
    with pytest.raises(GatewayKeyUnavailable):
        GatewayCredentialHasher.from_settings(malformed)


def test_pairing_defaults_read_only_and_write_grants_require_explicit_confirmation():
    body = PairingSessionCreate(device_name="  Codex   laptop  ")

    assert body.device_name == "Codex laptop"
    assert body.scopes == list(READ_ONLY_SCOPES)
    assert all(scope.endswith(":read") for scope in body.scopes)

    with pytest.raises(ValidationError):
        PairingSessionCreate(
            device_name="Codex laptop",
            scopes=["settings:read", "settings:write"],
        )
    confirmed = ConnectionScopesPatch(
        scopes=["settings:write", "settings:read", "settings:read"],
        confirm_write_scopes=True,
    )
    assert confirmed.scopes == ["settings:read", "settings:write"]


def test_connection_status_requires_authenticated_heartbeat_and_uses_server_windows():
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)
    connection = _connection(now)

    assert connection_status(connection, now=now, fresh_seconds=90, stale_seconds=300) == "gray"

    connection.last_heartbeat_at = now - timedelta(seconds=90)
    assert connection_status(connection, now=now, fresh_seconds=90, stale_seconds=300) == "green"
    connection.last_heartbeat_at = now - timedelta(seconds=91)
    assert connection_status(connection, now=now, fresh_seconds=90, stale_seconds=300) == "yellow"
    connection.last_heartbeat_at = now - timedelta(seconds=301)
    assert connection_status(connection, now=now, fresh_seconds=90, stale_seconds=300) == "gray"

    connection.last_heartbeat_at = now
    connection.last_error_code = "scope_denied"
    assert connection_status(connection, now=now, fresh_seconds=90, stale_seconds=300) == "red"
    connection.status = "revoked"
    assert connection_status(connection, now=now, fresh_seconds=90, stale_seconds=300) == "gray"


def test_pair_and_heartbeat_authenticate_inside_gateway_while_admin_mutations_remain_protected():
    assert mutation_rule("POST", "/codex-gateway/pair") is None
    assert mutation_rule("POST", "/codex-gateway/heartbeat") is None
    assert (
        mutation_rule("POST", "/codex-gateway/pairing-sessions").required_scope
        == "settings:write"
    )
    assert (
        mutation_rule(
            "POST",
            "/codex-gateway/connections/99e6ff1f-96fb-42a7-9a94-a78a7a06539d/rotate",
        ).required_scope
        == "settings:write"
    )


def test_gateway_heartbeat_thresholds_must_be_ordered():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="test",
            codex_gateway_heartbeat_fresh_seconds=300,
            codex_gateway_heartbeat_stale_seconds=300,
        )


def test_production_gateway_url_rejects_remote_plaintext_and_embedded_credentials():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            codex_gateway_public_url="http://newscraft.example",
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="development",
            codex_gateway_public_url="https://user:pass@newscraft.example",
        )

    local = Settings(
        _env_file=None,
        app_env="production",
        codex_gateway_public_url="http://127.0.0.1:8000",
    )
    assert local.codex_gateway_public_url == "http://127.0.0.1:8000"
