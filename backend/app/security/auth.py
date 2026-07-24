from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings
from app.security.scopes import HUMAN_ADMIN_SCOPES, parse_scopes

PrincipalType = Literal["human_admin", "codex_service", "internal_service", "test_harness"]


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

    def authenticate(
        self,
        authorization: str | None,
        principal_type: str | None,
    ) -> SecurityPrincipal:
        supplied = self._bearer_value(authorization)
        selected = (principal_type or "human_admin").casefold()
        if selected == "human_admin":
            configured = self.config.security_admin_token
            scopes = HUMAN_ADMIN_SCOPES
            principal_id = "human-admin"
        elif selected == "codex_service":
            configured = self.config.security_codex_token
            scopes = parse_scopes(self.config.security_codex_scopes)
            principal_id = "codex-bootstrap"
        elif selected == "internal_service":
            configured = self.config.security_internal_token
            scopes = parse_scopes(self.config.security_internal_scopes)
            principal_id = "internal-service"
        else:
            raise AuthenticationFailure("credential_invalid", 401)
        if configured is None:
            raise AuthenticationFailure("authentication_unavailable", 503)
        expected = configured.get_secret_value()
        if not expected or not secrets.compare_digest(supplied, expected):
            raise AuthenticationFailure("credential_invalid", 401)
        return SecurityPrincipal(selected, principal_id, scopes)  # type: ignore[arg-type]


TEST_ADMIN = SecurityPrincipal("test_harness", "pytest", HUMAN_ADMIN_SCOPES)


__all__ = [
    "AuthenticationFailure",
    "CredentialAuthenticator",
    "SecurityPrincipal",
    "TEST_ADMIN",
]
