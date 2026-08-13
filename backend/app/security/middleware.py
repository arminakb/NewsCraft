from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import Settings, settings
from app.db.session import async_session
from app.security.application_principal import ApplicationPrincipalResolver
from app.security.audit import CORRELATION_KEY, reconcile_stale_attempts, record_security_event
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


MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Scope demanded by any mutating path this table does not model. Unmodelled
# mutations are treated as administrative: browser owners hold every scope, so
# only narrowly scoped service tokens are affected, and a new router can never
# reach a handler without authentication, same-origin and audit.
DEFAULT_MUTATION_SCOPE = "settings:write"

# Mutating paths that deliberately carry no middleware rule because they
# authenticate inside their own handler. Matching is exact, so a nested path
# never inherits the exemption. Adding an entry is a security decision, never a
# convenience; the route-table test guards this set.
UNRULED_MUTATION_PATHS: frozenset[tuple[str, ...]] = frozenset(
    {
        # Batched catalog is a read-only POST because resource IDs are supplied
        # in a bounded JSON body. Route-level read-scope checks remain authoritative.
        ("automation-resource-catalog",),
        # These endpoints authenticate one-time or paired Codex credentials
        # inside the gateway service. They are never human-admin mutations.
        ("codex-gateway", "pair"),
        ("codex-gateway", "heartbeat"),
    }
)

# Ordered path-prefix table: the first entry whose segments prefix the request
# path wins, so longer prefixes are listed before the namespace they refine.
MUTATION_PREFIXES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("operations", "retention-policy"), "settings:write", "retention_setting"),
    (("operations", "retention-preview"), "settings:write", "retention_setting"),
    (("operations", "retention-runs"), "settings:write", "retention_setting"),
    (("telegram", "destinations"), "destinations:write", "telegram_destination"),
    (("telegram", "proxies"), "destinations:write", "telegram_proxy_profile"),
    (("telegram", "automations"), "automations:write", "automation"),
    (("telegram", "drafts"), DEFAULT_MUTATION_SCOPE, "telegram_draft"),
    (("telegram", "publish-jobs"), DEFAULT_MUTATION_SCOPE, "telegram_publish_job"),
    (("telegram", "sources"), DEFAULT_MUTATION_SCOPE, "telegram_source"),
    (("brand-profiles",), "settings:write", "editorial_profile"),
    (("operator-settings",), "settings:write", "operator_setting"),
    (("prompt-templates",), "prompts:write", "prompt"),
    (("prompt-template-versions",), "prompts:write", "prompt"),
    (("llm-providers",), "providers:write", "llm_provider"),
    (("automation-control",), "automations:write", "automation"),
    (("automations",), "automations:write", "automation"),
    (("automation-templates",), "automations:write", "automation"),
    (("automation-runs",), "automations:write", "automation_run"),
    (("jobs",), "jobs:write", "job"),
    (("feed",), "feed:write", "feed"),
    (("codex-gateway",), "settings:write", "codex_connection"),
    (("sources",), DEFAULT_MUTATION_SCOPE, "source"),
    (("source-collections",), DEFAULT_MUTATION_SCOPE, "source_collection"),
    (("article-collections",), DEFAULT_MUTATION_SCOPE, "article_collection"),
    (("stories",), DEFAULT_MUTATION_SCOPE, "story"),
    (("ingest",), DEFAULT_MUTATION_SCOPE, "ingest_run"),
    (("content-items",), DEFAULT_MUTATION_SCOPE, "content_item"),
    (("content-packs",), DEFAULT_MUTATION_SCOPE, "content_pack"),
    (("platform-variants",), DEFAULT_MUTATION_SCOPE, "platform_variant"),
    (("platform-variant-revisions",), DEFAULT_MUTATION_SCOPE, "platform_variant_revision"),
    (("manual-publication-plans",), DEFAULT_MUTATION_SCOPE, "manual_publication_plan"),
    (("exports",), DEFAULT_MUTATION_SCOPE, "export"),
)

# Two denial codes are published contracts and must not be merged: the
# automation surface documents `insufficient_permission`
# (docs/implementation-notes/automation-workflow-builder-contract.md) while the
# rest of the API documents `scope_denied`
# (docs/content-settings/codex-gateway-contract.md). The split lives here so it
# is a named policy rather than an inline path literal.
INSUFFICIENT_PERMISSION_PREFIXES = frozenset({"automations", "automation-templates"})

_ACTION_TERMINALS = frozenset(
    {
        "activate",
        "approve",
        "archive",
        "cancel",
        "clear",
        "disable",
        "duplicate",
        "enable",
        "health-check",
        "ingest",
        "mark-published",
        "pause",
        "publish",
        "recheck",
        "reconcile",
        "regenerate",
        "reject",
        "restore-as-draft",
        "resume",
        "retry",
        "revoke",
        "rotate",
        "rotate-credentials",
        "rotate-token",
        "run",
        "schedule",
        "seed",
        "stop",
        "validate",
    }
)


def _uuid_segment(parts: list[str]) -> str | None:
    for part in parts:
        try:
            return str(UUID(part))
        except ValueError:
            continue
    return None


def _scope_and_resource(parts: list[str]) -> tuple[str, str]:
    for prefix, scope, resource in MUTATION_PREFIXES:
        if tuple(parts[: len(prefix)]) == prefix:
            return scope, resource
    return DEFAULT_MUTATION_SCOPE, parts[0].replace("-", "_")


def mutation_rule(method: str, path: str) -> MutationRule | None:
    method = method.upper()
    if method not in MUTATION_METHODS:
        return None
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None
    if tuple(parts) in UNRULED_MUTATION_PATHS:
        return None
    scope, resource = _scope_and_resource(parts)

    terminal = parts[-1].replace("_", "-")
    if terminal in _ACTION_TERMINALS:
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
    correlation_id: str,
    status_code: int | None = None,
    session_factory=async_session,
) -> None:
    metadata: dict[str, object] = {CORRELATION_KEY: correlation_id}
    if status_code is not None:
        metadata["status_code"] = status_code
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
            metadata=metadata,
        )
        await session.commit()


#: Shortest gap between two reconciliation sweeps. The sweep runs after a
#: mutation's response has been produced, so this only bounds how much work the
#: audit trail does per request, not how quickly a request is served.
RECONCILE_INTERVAL_SECONDS = 300.0


class SecurityAuthorizationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, config: Settings = settings, session_factory=None) -> None:
        super().__init__(app)
        self.config = config
        self.principal_resolver = ApplicationPrincipalResolver(config)
        self.session_factory = session_factory or async_session
        self._last_reconcile: float | None = None

    def _auditing(self) -> bool:
        return bool(self.config.security_audit_enabled) and self.config.app_env != "test"

    async def _audit_or_fail(
        self,
        *,
        principal: SecurityPrincipal | None,
        rule: MutationRule,
        outcome: str,
        reason_code: str | None,
        request_id: str | None,
        correlation_id: str,
        status_code: int | None = None,
    ) -> JSONResponse | None:
        if not self._auditing():
            return None
        try:
            await _persist_event(
                principal=principal,
                rule=rule,
                outcome=outcome,
                reason_code=reason_code,
                request_id=request_id,
                correlation_id=correlation_id,
                status_code=status_code,
                session_factory=self.session_factory,
            )
        except Exception:  # noqa: BLE001 - mutation must fail closed before execution
            logger.exception("security audit persistence failed")
            return JSONResponse(status_code=503, content={"detail": {"code": "security_audit_unavailable"}})
        return None

    async def _reconcile_stale_attempts(self) -> None:
        """Close mutations whose outcome row never landed.

        A crash between the two audit writes, or a failure of the second one,
        leaves an ``attempted`` row that nothing else ever closes. Sweeping here
        keeps that gap out of the trail without a scheduler: every mutation is
        already paying for an audit round trip, and the interval keeps the extra
        query rare. Failures are swallowed — the mutation is already committed
        and its own outcome row is already written, so a sweep that cannot run
        must not turn a served request into an error.
        """

        if not self._auditing():
            return
        now = time.monotonic()
        if self._last_reconcile is not None and now - self._last_reconcile < RECONCILE_INTERVAL_SECONDS:
            return
        self._last_reconcile = now
        closed = 0
        try:
            async with self.session_factory() as session:
                reconciled = await reconcile_stale_attempts(session)
                closed = len(reconciled)
                if closed:
                    await session.commit()
        except Exception:  # noqa: BLE001 - reconciliation is best effort, never request-fatal
            logger.exception("security audit reconciliation failed")
            return
        if closed:
            logger.error(
                "security mutations closed without a recorded outcome",
                extra={"count": closed},
            )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rule = mutation_rule(request.method, request.url.path)
        if rule is None:
            return await call_next(request)
        request_id = _request_id(request)
        # Ties this request's pre-mutation row to its terminal row so a missing
        # outcome is detectable; see ``reconcile_stale_attempts``.
        correlation_id = str(uuid4())
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
                correlation_id=correlation_id,
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
                "insufficient_permission" if first in INSUFFICIENT_PERMISSION_PREFIXES else "scope_denied"
            )
            audit_failure = await self._audit_or_fail(
                principal=principal,
                rule=rule,
                outcome="rejected",
                reason_code=denial_code,
                request_id=request_id,
                correlation_id=correlation_id,
                status_code=403,
            )
            return audit_failure or JSONResponse(status_code=403, content={"detail": {"code": denial_code}})
        audit_failure = await self._audit_or_fail(
            principal=principal,
            rule=rule,
            outcome="attempted",
            reason_code=None,
            request_id=request_id,
            correlation_id=correlation_id,
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
            correlation_id=correlation_id,
            status_code=response.status_code,
        )
        if post_failure is not None:
            # The mutation is already committed, so this cannot fail closed. The
            # dangling ``attempted`` row it leaves behind is the durable signal:
            # the reconciliation sweep turns it into a terminal ``failed`` row
            # that operators reading the audit trail can see.
            logger.critical("security mutation completed but outcome audit failed", extra={"action": rule.action})
        await self._reconcile_stale_attempts()
        return response


__all__ = [
    "DEFAULT_MUTATION_SCOPE",
    "INSUFFICIENT_PERMISSION_PREFIXES",
    "MUTATION_METHODS",
    "MUTATION_PREFIXES",
    "MutationRule",
    "SecurityAuthorizationMiddleware",
    "UNRULED_MUTATION_PATHS",
    "mutation_rule",
]
