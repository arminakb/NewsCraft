from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact_secrets, redact_string
from app.security.auth import SecurityPrincipal
from app.security.models import SecurityAuditEvent

#: Metadata key linking the pre-mutation ``attempted`` row to the terminal row
#: written once the response is known. Without it a mutation whose outcome row
#: never landed is indistinguishable from a normal completed mutation, because
#: the ``attempted`` row is never rewritten.
CORRELATION_KEY = "audit_correlation_id"

#: Reason code of the synthetic terminal row that closes a mutation whose real
#: outcome was never recorded.
UNRECORDED_OUTCOME_REASON = "outcome_unrecorded"

#: How long a mutation may stay open before its missing outcome is treated as
#: lost rather than in flight. Comfortably longer than any request this service
#: should serve.
STALE_ATTEMPT_GRACE = timedelta(hours=1)

#: How far back a single sweep looks. Rows older than this were either already
#: reconciled or belong to history the trail no longer reasons about, so the
#: scan stays a bounded range over ``ix_security_audit_created``.
STALE_ATTEMPT_WINDOW = timedelta(days=7)

#: Upper bound on rows closed per sweep, so reconciliation never turns into an
#: unbounded write burst behind a single request.
STALE_ATTEMPT_BATCH = 50


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


def _correlation_id(event: SecurityAuditEvent) -> str | None:
    value = event.event_metadata.get(CORRELATION_KEY)
    return value if isinstance(value, str) else None


async def reconcile_stale_attempts(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = STALE_ATTEMPT_BATCH,
) -> list[SecurityAuditEvent]:
    """Close mutations whose terminal audit row never landed.

    The pre-mutation ``attempted`` row is committed in its own transaction so
    the mutation can fail closed when the trail is unwritable; its terminal row
    is written after the response. A crash, or a failure of that second write,
    therefore leaves an ``attempted`` row that no later code path ever closes.
    This appends a terminal ``failed`` row — the trail stays append-only — so a
    lost outcome is visible in the audit trail itself rather than only in a
    ``critical`` log line.
    """

    moment = now or datetime.now(UTC)
    correlation = SecurityAuditEvent.event_metadata[CORRELATION_KEY].astext
    open_events = (
        await session.execute(
            select(SecurityAuditEvent)
            .where(
                SecurityAuditEvent.outcome == "attempted",
                SecurityAuditEvent.created_at < moment - STALE_ATTEMPT_GRACE,
                SecurityAuditEvent.created_at >= moment - STALE_ATTEMPT_WINDOW,
                correlation.is_not(None),
            )
            .order_by(SecurityAuditEvent.created_at)
            .limit(limit)
        )
    ).scalars()
    candidates = {
        found: event for event in open_events if (found := _correlation_id(event)) is not None
    }
    if not candidates:
        return []
    closed = set(
        (
            await session.execute(
                select(correlation).where(
                    correlation.in_(sorted(candidates)),
                    SecurityAuditEvent.outcome != "attempted",
                )
            )
        )
        .scalars()
        .all()
    )
    reconciled = []
    for key, event in candidates.items():
        if key in closed:
            continue
        # Written field by field rather than through ``record_security_event``:
        # every value is copied from an already-recorded (and already-redacted)
        # row, including the original actor, which the shared writer can only
        # express as a live ``SecurityPrincipal``.
        closing = SecurityAuditEvent(
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            required_scope=event.required_scope,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            outcome="failed",
            reason_code=UNRECORDED_OUTCOME_REASON,
            request_id=event.request_id,
            event_metadata={CORRELATION_KEY: key, "reconciled_from": str(event.id)},
        )
        session.add(closing)
        reconciled.append(closing)
    return reconciled


__all__ = [
    "CORRELATION_KEY",
    "STALE_ATTEMPT_BATCH",
    "STALE_ATTEMPT_GRACE",
    "STALE_ATTEMPT_WINDOW",
    "UNRECORDED_OUTCOME_REASON",
    "reconcile_stale_attempts",
    "record_security_event",
]
