import base64
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.security.auth import TEST_ADMIN
from app.security.models import SecurityAuditEvent
from app.security.schemas import SecretMetadataOut, SecretWriteIn
from app.security.secret_store import (
    EncryptedSecretStore,
    MasterKeyRing,
    SecretAccessDenied,
    SecretDecryptionFailed,
    SecretKeyUnavailable,
)


class MemorySession:
    def __init__(self) -> None:
        self.values = []

    def add(self, value) -> None:
        self.values.append(value)


def _encoded(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def _ring(active: str = "v1") -> MasterKeyRing:
    return MasterKeyRing(active, {"v0": bytes([1]) * 32, "v1": bytes([2]) * 32})


def test_encryption_decryption_and_rotation_never_persist_plaintext():
    session = MemorySession()
    store = EncryptedSecretStore(session, _ring())
    owner_id = uuid4()
    record = store.create(
        purpose="telegram_bot_token",
        owner_type="telegram_destination",
        owner_id=owner_id,
        value=SecretStr("plaintext-canary"),
        principal=TEST_ADMIN,
        required_scope="destinations:write",
    )

    assert record.nonce and len(record.nonce) == 12
    assert b"plaintext-canary" not in record.ciphertext
    assert store.decrypt(record, principal=TEST_ADMIN, required_scope="destinations:write") == "plaintext-canary"

    first_ciphertext = record.ciphertext
    store.rotate(
        record,
        "replacement-canary",
        principal=TEST_ADMIN,
        required_scope="destinations:write",
    )
    assert record.ciphertext != first_ciphertext
    assert b"replacement-canary" not in record.ciphertext
    assert store.decrypt(record, principal=TEST_ADMIN, required_scope="destinations:write") == "replacement-canary"
    actions = [value.action for value in session.values if isinstance(value, SecurityAuditEvent)]
    assert "secret.create" in actions
    assert "secret.rotate" in actions


def test_master_key_rotation_rewraps_old_ciphertext_to_active_version():
    session = MemorySession()
    old_store = EncryptedSecretStore(session, MasterKeyRing("v0", _ring().keys))
    record = old_store.create(
        purpose="provider_api_key",
        owner_type="llm_provider",
        owner_id=uuid4(),
        value="provider-canary",
        principal=TEST_ADMIN,
        required_scope="providers:write",
        now=datetime(2026, 7, 22, tzinfo=UTC),
    )
    assert record.key_version == "v0"

    new_store = EncryptedSecretStore(session, _ring("v1"))
    assert new_store.rewrap(
        record,
        principal=TEST_ADMIN,
        required_scope="providers:write",
    )
    assert record.key_version == "v1"
    assert new_store.decrypt(record, principal=TEST_ADMIN, required_scope="providers:write") == "provider-canary"
    assert any(isinstance(value, SecurityAuditEvent) and value.action == "secret.rewrap" for value in session.values)


def test_missing_key_fails_closed_and_tampering_creates_redacted_audit_event():
    with pytest.raises(SecretKeyUnavailable):
        MasterKeyRing.from_settings(Settings(_env_file=None, secret_master_key=None))

    session = MemorySession()
    store = EncryptedSecretStore(session, _ring())
    record = store.create(
        purpose="proxy_password",
        owner_type="telegram_proxy_profile",
        owner_id=uuid4(),
        value="audit-secret-canary",
        principal=TEST_ADMIN,
        required_scope="destinations:write",
    )
    record.ciphertext = record.ciphertext[:-1] + bytes([record.ciphertext[-1] ^ 1])

    with pytest.raises(SecretDecryptionFailed):
        store.decrypt(record, principal=TEST_ADMIN, required_scope="destinations:write")

    audit = next(
        value
        for value in session.values
        if isinstance(value, SecurityAuditEvent) and value.reason_code == "secret_decryption_failed"
    )
    assert audit.reason_code == "secret_decryption_failed"
    assert "audit-secret-canary" not in str(audit.event_metadata)


def test_secret_store_enforces_scope_even_when_http_layer_is_bypassed():
    from app.security.auth import SecurityPrincipal

    session = MemorySession()
    store = EncryptedSecretStore(session, _ring())
    read_only = SecurityPrincipal("codex_service", "codex", frozenset({"providers:read"}))

    with pytest.raises(SecretAccessDenied):
        store.create(
            purpose="provider_api_key",
            owner_type="llm_provider",
            owner_id=uuid4(),
            value="must-not-encrypt",
            principal=read_only,
            required_scope="providers:write",
        )

    audit = next(value for value in session.values if isinstance(value, SecurityAuditEvent))
    assert audit.reason_code == "scope_denied"
    assert audit.outcome == "rejected"


def test_write_only_schema_masks_secret_serialization_and_key_config_parses_versions():
    body = SecretWriteIn(secret="schema-canary")
    assert "schema-canary" not in body.model_dump_json()
    assert set(SecretMetadataOut.model_fields) == {"configured", "last_rotated_at"}

    config = Settings(
        _env_file=None,
        secret_key_version="v1",
        secret_master_key=_encoded(2),
        secret_previous_keys=SecretStr('{"v0":"' + _encoded(1) + '"}'),
    )
    ring = MasterKeyRing.from_settings(config)
    assert ring.active_version == "v1"
    assert set(ring.keys) == {"v0", "v1"}

    blank_previous = MasterKeyRing.from_settings(
        Settings(
            _env_file=None,
            secret_key_version="v1",
            secret_master_key=_encoded(2),
            secret_previous_keys=SecretStr("  "),
        )
    )
    assert set(blank_previous.keys) == {"v1"}


def test_key_ring_rejects_malformed_base64_and_copies_key_material_mapping():
    with pytest.raises(SecretKeyUnavailable):
        MasterKeyRing.from_settings(
            Settings(
                _env_file=None,
                secret_master_key=_encoded(2) + "!",
            )
        )

    source = {"v1": bytes([2]) * 32}
    ring = MasterKeyRing("v1", source)
    source["v1"] = bytes([3]) * 32

    assert ring.active_key() == bytes([2]) * 32
    with pytest.raises(TypeError):
        ring.keys["v1"] = bytes([4]) * 32  # type: ignore[index]
