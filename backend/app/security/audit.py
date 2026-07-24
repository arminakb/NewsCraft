from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact_secrets, redact_string
from app.security.auth import SecurityPrincipal
from app.security.models import SecurityAuditEvent


def _safe_text(value: str | None, *, limit: int = 200) -> str | None:
    if value is None:
        return None
    return redact_string(value)[:limit]


def record_security_event(
    session: AsyncSession,
    *,
    principal: SecurityPrincipal | None,
    required_scope: str | None,
    action: str,
    resource_type: str,
    outcome: str,
    resource_id: str | None = None,
    reason_code: str | None = None,
    request_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SecurityAuditEvent:
    sanitized = redact_secrets(dict(metadata or {}))
    event = SecurityAuditEvent(
        actor_type=principal.principal_type if principal is not None else "anonymous",
        actor_id=principal.principal_id if principal is not None else "anonymous",
        required_scope=_safe_text(required_scope),
        action=_safe_text(action) or "unknown",
        resource_type=_safe_text(resource_type) or "unknown",
        resource_id=_safe_text(resource_id),
        outcome=outcome,
        reason_code=_safe_text(reason_code),
        request_id=_safe_text(request_id, limit=128),
        event_metadata=sanitized if isinstance(sanitized, dict) else {},
    )
    session.add(event)
    return event


__all__ = ["record_security_event"]
