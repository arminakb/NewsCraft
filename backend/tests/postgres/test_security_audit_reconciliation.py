from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.security.audit import (
    CORRELATION_KEY,
    STALE_ATTEMPT_GRACE,
    UNRECORDED_OUTCOME_REASON,
    reconcile_stale_attempts,
)
from app.security.models import SecurityAuditEvent


def _event(
    *,
    correlation: str,
    outcome: str,
    created_at: datetime,
) -> SecurityAuditEvent:
    return SecurityAuditEvent(
        actor_type="local_owner",
        actor_id="local-owner",
        required_scope="providers:write",
        action="llm_provider.create",
        resource_type="llm_provider",
        resource_id=None,
        outcome=outcome,
        reason_code=None,
        request_id="req-1",
        event_metadata={CORRELATION_KEY: correlation},
        created_at=created_at,
    )


async def test_reconciliation_closes_only_mutations_whose_outcome_never_landed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    stale = now - STALE_ATTEMPT_GRACE - timedelta(minutes=5)
    async with session_factory() as session:
        session.add_all(
            [
                _event(correlation="lost", outcome="attempted", created_at=stale),
                _event(correlation="completed", outcome="attempted", created_at=stale),
                _event(correlation="completed", outcome="succeeded", created_at=stale),
                _event(correlation="in-flight", outcome="attempted", created_at=now),
            ]
        )
        await session.commit()

    async with session_factory() as session:
        reconciled = await reconcile_stale_attempts(session, now=now)
        await session.commit()

    assert [event.event_metadata[CORRELATION_KEY] for event in reconciled] == ["lost"]

    async with session_factory() as session:
        closing = (
            await session.execute(
                select(SecurityAuditEvent).where(SecurityAuditEvent.reason_code == UNRECORDED_OUTCOME_REASON)
            )
        ).scalars().all()

    assert len(closing) == 1
    assert closing[0].outcome == "failed"
    # The synthetic row preserves who acted and what they acted on, so the
    # trail still answers "who left this mutation unaccounted for".
    assert closing[0].actor_id == "local-owner"
    assert closing[0].action == "llm_provider.create"


async def test_reconciliation_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    stale = now - STALE_ATTEMPT_GRACE - timedelta(minutes=5)
    async with session_factory() as session:
        session.add(_event(correlation="lost", outcome="attempted", created_at=stale))
        await session.commit()

    async with session_factory() as session:
        first = await reconcile_stale_attempts(session, now=now)
        await session.commit()
    async with session_factory() as session:
        second = await reconcile_stale_attempts(session, now=now)
        await session.commit()

    assert len(first) == 1
    assert second == []
