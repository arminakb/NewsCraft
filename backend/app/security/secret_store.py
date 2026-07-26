from __future__ import annotations

import base64
import binascii
import json
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.security.audit import record_security_event
from app.security.auth import SecurityPrincipal
from app.security.models import EncryptedSecret


class SecretStoreError(RuntimeError):
    public_code = "secret_store_unavailable"

    def __init__(self) -> None:
        super().__init__(self.public_code)


class SecretKeyUnavailable(SecretStoreError):
    pass


class SecretDecryptionFailed(SecretStoreError):
    public_code = "secret_decryption_failed"


class SecretAccessDenied(SecretStoreError):
    public_code = "secret_access_denied"


def _decode_key(encoded: str) -> bytes:
    try:
        raw = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
    except binascii.Error, ValueError, TypeError:
        raise SecretKeyUnavailable from None
    if len(raw) != 32:
        raise SecretKeyUnavailable
    return raw


@dataclass(frozen=True, slots=True)
class MasterKeyRing:
    active_version: str
    keys: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if self.active_version not in self.keys:
            raise SecretKeyUnavailable
        copied: dict[str, bytes] = {}
        for version, key in self.keys.items():
            if (
                not isinstance(version, str)
                or not version
                or len(version) > 32
                or not version.replace("-", "").replace("_", "").isalnum()
                or not isinstance(key, bytes)
                or len(key) != 32
            ):
                raise SecretKeyUnavailable
            copied[version] = key
        object.__setattr__(self, "keys", MappingProxyType(copied))

    @classmethod
    def from_settings(cls, config: Settings) -> MasterKeyRing:
        if config.secret_master_key is None:
            raise SecretKeyUnavailable
        keys: dict[str, bytes] = {config.secret_key_version: _decode_key(config.secret_master_key.get_secret_value())}
        if config.secret_previous_keys is not None:
            encoded_previous = config.secret_previous_keys.get_secret_value().strip()
            if not encoded_previous:
                return cls(active_version=config.secret_key_version, keys=keys)
            try:
                previous = json.loads(encoded_previous)
            except json.JSONDecodeError, TypeError:
                raise SecretKeyUnavailable from None
            if not isinstance(previous, dict):
                raise SecretKeyUnavailable
            for version, encoded in previous.items():
                if not isinstance(version, str) or not version or not isinstance(encoded, str) or version in keys:
                    raise SecretKeyUnavailable
                keys[version] = _decode_key(encoded)
        return cls(active_version=config.secret_key_version, keys=keys)

    def active_key(self) -> bytes:
        try:
            return self.keys[self.active_version]
        except KeyError:
            raise SecretKeyUnavailable from None

    def key(self, version: str) -> bytes:
        try:
            return self.keys[version]
        except KeyError:
            raise SecretKeyUnavailable from None


class EncryptedSecretStore:
    def __init__(self, session: AsyncSession, key_ring: MasterKeyRing) -> None:
        self.session = session
        self.key_ring = key_ring

    @staticmethod
    def _aad(record: EncryptedSecret, key_version: str) -> bytes:
        return json.dumps(
            {
                "id": str(record.id),
                "purpose": record.purpose,
                "owner_type": record.owner_type,
                "owner_id": str(record.owner_id),
                "key_version": key_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _plaintext(value: str | SecretStr) -> bytes:
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not secret:
            raise ValueError("secret must not be empty")
        return secret.encode("utf-8")

    def _authorize(
        self,
        record: EncryptedSecret,
        *,
        principal: SecurityPrincipal,
        required_scope: str,
        action: str,
    ) -> None:
        if principal.permits(required_scope):
            return
        record_security_event(
            self.session,
            principal=principal,
            required_scope=required_scope,
            action=action,
            resource_type=record.owner_type,
            resource_id=str(record.owner_id),
            outcome="rejected",
            reason_code="scope_denied",
        )
        raise SecretAccessDenied

    def _encrypt(self, record: EncryptedSecret, value: str | SecretStr, *, rotated_at: datetime) -> None:
        version = self.key_ring.active_version
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self.key_ring.active_key()).encrypt(
            nonce,
            self._plaintext(value),
            self._aad(record, version),
        )
        record.nonce = nonce
        record.ciphertext = ciphertext
        record.key_version = version
        record.last_rotated_at = rotated_at

    def create(
        self,
        *,
        purpose: str,
        owner_type: str,
        owner_id: uuid.UUID,
        value: str | SecretStr,
        principal: SecurityPrincipal,
        required_scope: str,
        now: datetime | None = None,
    ) -> EncryptedSecret:
        record = EncryptedSecret(
            id=uuid.uuid4(),
            purpose=purpose,
            owner_type=owner_type,
            owner_id=owner_id,
            ciphertext=b"",
            nonce=b"",
            key_version=self.key_ring.active_version,
        )
        self._authorize(record, principal=principal, required_scope=required_scope, action="secret.create")
        self._encrypt(record, value, rotated_at=now or datetime.now(UTC))
        self.session.add(record)
        record_security_event(
            self.session,
            principal=principal,
            required_scope=required_scope,
            action="secret.create",
            resource_type=record.owner_type,
            resource_id=str(record.owner_id),
            outcome="succeeded",
            metadata={"purpose": record.purpose, "key_version": record.key_version},
        )
        return record

    def rotate(
        self,
        record: EncryptedSecret,
        value: str | SecretStr,
        *,
        principal: SecurityPrincipal,
        required_scope: str,
        now: datetime | None = None,
    ) -> None:
        self._authorize(record, principal=principal, required_scope=required_scope, action="secret.rotate")
        self._encrypt(record, value, rotated_at=now or datetime.now(UTC))
        record_security_event(
            self.session,
            principal=principal,
            required_scope=required_scope,
            action="secret.rotate",
            resource_type=record.owner_type,
            resource_id=str(record.owner_id),
            outcome="succeeded",
            metadata={"purpose": record.purpose, "key_version": record.key_version},
        )

    def decrypt(
        self,
        record: EncryptedSecret,
        *,
        principal: SecurityPrincipal,
        required_scope: str,
    ) -> str:
        self._authorize(record, principal=principal, required_scope=required_scope, action="secret.decrypt")
        try:
            plaintext = AESGCM(self.key_ring.key(record.key_version)).decrypt(
                record.nonce,
                record.ciphertext,
                self._aad(record, record.key_version),
            )
            return plaintext.decode("utf-8")
        except InvalidTag, SecretKeyUnavailable, UnicodeDecodeError, ValueError:
            record_security_event(
                self.session,
                principal=principal,
                required_scope=required_scope,
                action="secret.decrypt",
                resource_type=record.owner_type,
                resource_id=str(record.owner_id),
                outcome="failed",
                reason_code="secret_decryption_failed",
                metadata={"purpose": record.purpose, "key_version": record.key_version},
            )
            raise SecretDecryptionFailed from None

    def rewrap(
        self,
        record: EncryptedSecret,
        *,
        principal: SecurityPrincipal,
        required_scope: str,
        now: datetime | None = None,
    ) -> bool:
        if record.key_version == self.key_ring.active_version:
            return False
        plaintext = self.decrypt(record, principal=principal, required_scope=required_scope)
        self._encrypt(record, plaintext, rotated_at=now or datetime.now(UTC))
        record_security_event(
            self.session,
            principal=principal,
            required_scope=required_scope,
            action="secret.rewrap",
            resource_type=record.owner_type,
            resource_id=str(record.owner_id),
            outcome="succeeded",
            metadata={"purpose": record.purpose, "key_version": record.key_version},
        )
        return True


__all__ = [
    "EncryptedSecretStore",
    "MasterKeyRing",
    "SecretAccessDenied",
    "SecretDecryptionFailed",
    "SecretKeyUnavailable",
    "SecretStoreError",
]
