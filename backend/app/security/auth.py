from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings
from app.security.scopes import APPLICATION_OWNER_SCOPES, parse_scopes

PrincipalType = Literal["local_owner", "codex_service", "internal_service", "test_harness"]


@dataclass(frozen=True, slots=True)
class SecurityPrincipal:
    principal_type: PrincipalType
    principal_id: str
    scopes: frozenset[str]

    def permits(self, scope: str) -> bool:
        return scope in self.scopes


class AuthenticationFailure(RuntimeError):
    def __init__(self, code: str, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class CredentialAuthenticator:
    def __init__(self, config: Settings) -> None:
        self.config = config

    @staticmethod
    def _bearer_value(authorization: str | None) -> str:
        if authorization is None:
            raise AuthenticationFailure("authentication_required", 401)
        scheme, separator, value = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not value or value.strip() != value:
            raise AuthenticationFailure("credential_invalid", 401)
        return value

    def authenticate(self, authorization: str | None) -> SecurityPrincipal:
        supplied = self._bearer_value(authorization)
        candidates = (
            (
                "codex_service",
                "codex-bootstrap",
                self.config.security_codex_token,
                parse_scopes(self.config.security_codex_scopes),
            ),
            (
                "internal_service",
                "internal-service",
                self.config.security_internal_token,
                parse_scopes(self.config.security_internal_scopes),
            ),
        )
        matches = [
            (principal_type, principal_id, scopes)
            for principal_type, principal_id, configured, scopes in candidates
            if configured is not None
            and configured.get_secret_value()
            and secrets.compare_digest(supplied, configured.get_secret_value())
        ]
        if len(matches) != 1:
            raise AuthenticationFailure("credential_invalid", 401)
        principal_type, principal_id, scopes = matches[0]
        return SecurityPrincipal(principal_type, principal_id, scopes)  # type: ignore[arg-type]


LOCAL_OWNER = SecurityPrincipal("local_owner", "local-owner", APPLICATION_OWNER_SCOPES)
TEST_ADMIN = SecurityPrincipal("test_harness", "pytest", APPLICATION_OWNER_SCOPES)


__all__ = [
    "AuthenticationFailure",
    "CredentialAuthenticator",
    "LOCAL_OWNER",
    "SecurityPrincipal",
    "TEST_ADMIN",
]
