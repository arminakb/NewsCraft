from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from app.core.config import Settings

_PAIRING_PATTERN = re.compile(r"^ncp_([A-Za-z0-9_-]{12})[A-Za-z0-9_-]{31,64}$")
_CREDENTIAL_PATTERN = re.compile(
    r"^ncg_([A-Za-z0-9_-]{12})_([A-Za-z0-9_-]{40,64})$"
)


class GatewayKeyUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    value: str
    prefix: str
    digest: bytes
    fingerprint: str


class GatewayCredentialHasher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise GatewayKeyUnavailable("codex_gateway_unavailable")
        self._key = key

    @classmethod
    def from_settings(cls, config: Settings) -> GatewayCredentialHasher:
        configured = config.codex_gateway_hash_key
        if configured is None:
            raise GatewayKeyUnavailable("codex_gateway_unavailable")
        try:
            value = configured.get_secret_value().encode("ascii")
            value += b"=" * (-len(value) % 4)
            key = base64.urlsafe_b64decode(value)
        except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
            raise GatewayKeyUnavailable("codex_gateway_unavailable") from exc
        return cls(key)

    def digest(self, purpose: str, value: str) -> bytes:
        message = f"newscraft:{purpose}:v1:{value}".encode()
        return hmac.new(self._key, message, hashlib.sha256).digest()

    def matches(self, purpose: str, value: str, expected: bytes) -> bool:
        return hmac.compare_digest(self.digest(purpose, value), expected)

    def issue_pairing_code(self) -> tuple[str, str, bytes]:
        body = secrets.token_urlsafe(36)
        code = f"ncp_{body}"
        prefix = body[:12]
        return code, prefix, self.digest("pairing-code", code)

    def parse_pairing_prefix(self, code: str) -> str | None:
        match = _PAIRING_PATTERN.fullmatch(code)
        return match.group(1) if match is not None else None

    def issue_credential(self, *, seed: str | None = None) -> IssuedCredential:
        if seed is None:
            prefix = secrets.token_urlsafe(9)
            secret = secrets.token_urlsafe(36)
        else:
            prefix = base64.urlsafe_b64encode(
                self.digest("credential-prefix", seed)
            ).decode().rstrip("=")[:12]
            secret = base64.urlsafe_b64encode(
                self.digest("credential-secret-a", seed)
                + self.digest("credential-secret-b", seed)[:4]
            ).decode().rstrip("=")
        value = f"ncg_{prefix}_{secret}"
        digest = self.digest("credential", value)
        return IssuedCredential(
            value=value,
            prefix=prefix,
            digest=digest,
            fingerprint=digest.hex()[:16],
        )

    def parse_credential_prefix(self, credential: str) -> str | None:
        match = _CREDENTIAL_PATTERN.fullmatch(credential)
        return match.group(1) if match is not None else None

    def rate_limit_key(self, category: str, subject: str) -> bytes:
        return self.digest("rate-limit", f"{category}:{subject}")

    def idempotency_key(self, operation: str, subject: str, value: str) -> bytes:
        return self.digest("idempotency", f"{operation}:{subject}:{value}")


__all__ = [
    "GatewayCredentialHasher",
    "GatewayKeyUnavailable",
    "IssuedCredential",
]
