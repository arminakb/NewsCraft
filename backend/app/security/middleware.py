from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import Settings, settings
from app.db.session import async_session
from app.security.application_principal import ApplicationPrincipalResolver
from app.security.audit import record_security_event
from app.security.auth import (
    AuthenticationFailure,
    SecurityPrincipal,
)

logger = logging.getLogger(__name__)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@dataclass(frozen=True, slots=True)
class MutationRule:
    required_scope: str
    resource_type: str
    action: str
    resource_id: str | None


def _uuid_segment(parts: list[str]) -> str | None:
    for part in parts:
        try:
            return str(UUID(part))
        except ValueError:
            continue
    return None


def mutation_rule(method: str, path: str) -> MutationRule | None:
    method = method.upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None
    first = parts[0]
    if first == "automation-resource-catalog":
        # Batched catalog is a read-only POST because resource IDs are supplied
        # in a bounded JSON body. Route-level read-scope checks remain authoritative.
        return None
    if first == "brand-profiles":
        scope, resource = "settings:write", "editorial_profile"
    elif first == "operator-settings":
        scope, resource = "settings:write", "operator_setting"
    elif parts[:2] in (
        ["operations", "retention-policy"],
        ["operations", "retention-preview"],
        ["operations", "retention-runs"],
    ):
        scope, resource = "settings:write", "retention_setting"
    elif first in {"prompt-templates", "prompt-template-versions"}:
        scope, resource = "prompts:write", "prompt"
    elif first == "llm-providers":
        scope, resource = "providers:write", "llm_provider"
    elif parts[:2] == ["telegram", "destinations"]:
        scope, resource = "destinations:write", "telegram_destination"
    elif parts[:2] == ["telegram", "proxies"]:
        scope, resource = "destinations:write", "telegram_proxy_profile"
    elif (
        first in {"automation-control", "automations", "automation-templates", "automation-resource-catalog"}
        or parts[:2] == ["telegram", "automations"]
    ):
        scope, resource = "automations:write", "automation"
    elif first == "jobs":
        scope, resource = "jobs:write", "job"
    elif first == "codex-gateway":
        if parts[1:] in (["pair"], ["heartbeat"]):
            # These endpoints authenticate one-time or paired Codex credentials
            # inside the gateway service. They are never human-admin mutations.
            return None
        scope, resource = "settings:write", "codex_connection"
    else:
        return None

    terminal = parts[-1].replace("_", "-")
    if terminal in {
        "activate",
        "archive",
        "duplicate",
        "enable",
        "disable",
        "pause",
        "resume",
        "restore-as-draft",
        "retry",
        "cancel",
        "rotate",
        "rotate-token",
        "rotate-credentials",
        "validate",
        "recheck",
        "revoke",
    }:
        action_name = terminal
    elif method == "POST":
        action_name = "create"
    elif method in {"PATCH", "PUT"}:
        action_name = "edit"
    else:
        action_name = "delete"
    return MutationRule(
        scope,
        resource,
        f"{resource}.{action_name}",
        _uuid_segment(parts),
    )


def _request_id(request: Request) -> str | None:
    value = request.headers.get("x-request-id")
    return value if value and _REQUEST_ID_PATTERN.fullmatch(value) else None


async def _persist_event(
    *,
    principal: SecurityPrincipal | None,
    rule: MutationRule,
    outcome: str,
    reason_code: str | None,
    request_id: str | None,
    status_code: int | None = None,
    session_factory=async_session,
) -> None:
    async with session_factory() as session:
        record_security_event(
            session,
            principal=principal,
            required_scope=rule.required_scope,
            action=rule.action,
            resource_type=rule.resource_type,
            resource_id=rule.resource_id,
            outcome=outcome,
            reason_code=reason_code,
            request_id=request_id,
            metadata={"status_code": status_code} if status_code is not None else {},
        )
        await session.commit()


class SecurityAuthorizationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, config: Settings = settings, session_factory=None) -> None:
        super().__init__(app)
        self.config = config
        self.principal_resolver = ApplicationPrincipalResolver(config)
        self.session_factory = session_factory or async_session

    async def _audit_or_fail(
        self,
        *,
        principal: SecurityPrincipal | None,
        rule: MutationRule,
        outcome: str,
        reason_code: str | None,
        request_id: str | None,
        status_code: int | None = None,
    ) -> JSONResponse | None:
        if not self.config.security_audit_enabled or self.config.app_env == "test":
            return None
        try:
            await _persist_event(
                principal=principal,
                rule=rule,
                outcome=outcome,
                reason_code=reason_code,
                request_id=request_id,
                status_code=status_code,
                session_factory=self.session_factory,
            )
        except Exception:  # noqa: BLE001 - mutation must fail closed before execution
            logger.exception("security audit persistence failed")
            return JSONResponse(status_code=503, content={"detail": {"code": "security_audit_unavailable"}})
        return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rule = mutation_rule(request.method, request.url.path)
        if rule is None:
            return await call_next(request)
        request_id = _request_id(request)
        try:
            resolved = self.principal_resolver.resolve(request, mutation=True)
            principal = resolved.principal
        except AuthenticationFailure as exc:
            audit_failure = await self._audit_or_fail(
                principal=None,
                rule=rule,
                outcome="rejected",
                reason_code=exc.code,
                request_id=request_id,
                status_code=exc.status_code,
            )
            return audit_failure or JSONResponse(
                status_code=exc.status_code,
                content={"detail": {"code": exc.code}},
            )
        request.state.authentication_method = resolved.authentication_method
        if not principal.permits(rule.required_scope):
            first = next((part for part in request.url.path.split("/") if part), "")
            denial_code = (
                "insufficient_permission"
                if first in {"automations", "automation-templates"}
                else "scope_denied"
            )
            audit_failure = await self._audit_or_fail(
                principal=principal,
                rule=rule,
                outcome="rejected",
                reason_code=denial_code,
                request_id=request_id,
                status_code=403,
            )
            return audit_failure or JSONResponse(status_code=403, content={"detail": {"code": denial_code}})
        audit_failure = await self._audit_or_fail(
            principal=principal,
            rule=rule,
            outcome="attempted",
            reason_code=None,
            request_id=request_id,
        )
        if audit_failure is not None:
            return audit_failure
        request.state.security_principal = principal
        response = await call_next(request)
        outcome = "succeeded" if 200 <= response.status_code < 300 else "rejected"
        reason = None if outcome == "succeeded" else "request_rejected"
        post_failure = await self._audit_or_fail(
            principal=principal,
            rule=rule,
            outcome=outcome,
            reason_code=reason,
            request_id=request_id,
            status_code=response.status_code,
        )
        if post_failure is not None:
            logger.critical("security mutation completed but outcome audit failed", extra={"action": rule.action})
        return response


__all__ = ["MutationRule", "SecurityAuthorizationMiddleware", "mutation_rule"]
