from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import Request

from app.core.config import Settings
from app.security.auth import (
    LOCAL_OWNER,
    TEST_ADMIN,
    AuthenticationFailure,
    CredentialAuthenticator,
    SecurityPrincipal,
)


def normalize_origin(value: str) -> str | None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    try:
        parsed_port = parsed.port
    except ValueError:
        return None
    default_port = (parsed.scheme == "http" and parsed_port in {None, 80}) or (
        parsed.scheme == "https" and parsed_port in {None, 443}
    )
    host = parsed.hostname.casefold().rstrip(".")
    rendered_host = f"[{host}]" if ":" in host else host
    port = "" if default_port else f":{parsed_port}"
    return f"{parsed.scheme}://{rendered_host}{port}"


def is_loopback_origin(value: str) -> bool:
    normalized = normalize_origin(value)
    if normalized is None:
        return False
    host = urlsplit(normalized).hostname
    if host == "localhost":
        return True
    try:
        return ip_address(host or "").is_loopback
    except ValueError:
        return False


def require_same_origin(request: Request, config: Settings) -> None:
    supplied = request.headers.get("origin")
    supplied_origin = normalize_origin(supplied) if supplied else None
    allowed = {
        normalized
        for value in config.cors_origins.split(",")
        if (normalized := normalize_origin(value.strip())) is not None
    }
    if supplied_origin is None or supplied_origin not in allowed:
        raise AuthenticationFailure("origin_validation_failed", 403)


@dataclass(frozen=True, slots=True)
class ResolvedApplicationPrincipal:
    principal: SecurityPrincipal
    authentication_method: str


class ApplicationPrincipalResolver:
    """Single seam for browser/profile and service principals.

    Local-owner mode creates browser authority from server deployment policy.
    Profile mode intentionally fails closed until profile-session resolution is
    implemented at this boundary.
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.authenticator = CredentialAuthenticator(config)

    def resolve(self, request: Request, *, mutation: bool) -> ResolvedApplicationPrincipal:
        authorization = request.headers.get("authorization")
        if authorization is not None:
            return ResolvedApplicationPrincipal(
                self.authenticator.authenticate(authorization),
                "bearer",
            )
        if self.config.app_env == "test":
            return ResolvedApplicationPrincipal(TEST_ADMIN, "test")
        if self.config.application_auth_mode == "local_owner":
            if mutation:
                require_same_origin(request, self.config)
            return ResolvedApplicationPrincipal(LOCAL_OWNER, "local_owner")
        raise AuthenticationFailure("authentication_required", 401)


def resolve_application_principal(
    request: Request,
    *,
    config: Settings,
    mutation: bool = False,
) -> SecurityPrincipal:
    existing = getattr(request.state, "security_principal", None)
    if isinstance(existing, SecurityPrincipal):
        return existing
    return ApplicationPrincipalResolver(config).resolve(request, mutation=mutation).principal


__all__ = [
    "ApplicationPrincipalResolver",
    "ResolvedApplicationPrincipal",
    "is_loopback_origin",
    "normalize_origin",
    "require_same_origin",
    "resolve_application_principal",
]
