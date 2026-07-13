from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.generation.revision_fence import (
    REGENERATION_FENCE_RESULT_KEY,
    RegenerationFenceConflict,
    RegenerationFenceOwner,
    acquire_regeneration_fence,
    clear_regeneration_fence,
    public_job_result,
    require_revision_write_allowed,
)


def _job(
    *,
    now: datetime,
    attempt: int = 1,
    lease_owner: str = "worker-a",
    lease_delta: timedelta = timedelta(minutes=5),
    result: dict | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        job_type="content_pack.regenerate",
        status="running",
        attempt_count=attempt,
        lease_owner=lease_owner,
        lease_expires_at=now + lease_delta,
        result=dict(result or {}),
    )


def _owner(job) -> RegenerationFenceOwner:
    return RegenerationFenceOwner(
        workflow_job_id=job.id,
        workflow_attempt=job.attempt_count,
        lease_owner=job.lease_owner,
    )


@pytest.mark.asyncio
async def test_live_durable_fence_blocks_foreign_writer_but_allows_exact_owner():
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    variant_id, base_revision_id = uuid4(), uuid4()
    job = _job(now=now, result={"platforms": []})
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[job]),
        flush=AsyncMock(),
    )

    owner = await acquire_regeneration_fence(
        session,
        variant_id=variant_id,
        base_revision_id=base_revision_id,
        base_content_hash="a" * 64,
        workflow_job_id=job.id,
        workflow_attempt=job.attempt_count,
        lease_owner=job.lease_owner,
        now=now,
    )

    assert owner == _owner(job)
    assert job.result[REGENERATION_FENCE_RESULT_KEY] == {
        "variant_id": str(variant_id),
        "base_revision_id": str(base_revision_id),
        "base_content_hash": "a" * 64,
        "workflow_job_id": str(job.id),
        "workflow_attempt": 1,
        "lease_owner": "worker-a",
    }
    with pytest.raises(RegenerationFenceConflict):
        await require_revision_write_allowed(session, variant_id=variant_id, now=now)
    await require_revision_write_allowed(
        session,
        variant_id=variant_id,
        owner=owner,
        expected_base_revision_id=base_revision_id,
        expected_base_content_hash="a" * 64,
        now=now,
    )


@pytest.mark.asyncio
async def test_expired_fence_is_inert_and_new_live_owner_can_reclaim():
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    variant_id, base_revision_id = uuid4(), uuid4()
    expired = _job(now=now, lease_owner="worker-old", lease_delta=timedelta(seconds=-1))
    expired.result[REGENERATION_FENCE_RESULT_KEY] = {
        "variant_id": str(variant_id),
        "base_revision_id": str(base_revision_id),
        "base_content_hash": "a" * 64,
        "workflow_job_id": str(expired.id),
        "workflow_attempt": expired.attempt_count,
        "lease_owner": expired.lease_owner,
    }
    replacement = _job(now=now, attempt=2, lease_owner="worker-new")
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[expired, replacement]),
        flush=AsyncMock(),
    )

    owner = await acquire_regeneration_fence(
        session,
        variant_id=variant_id,
        base_revision_id=base_revision_id,
        base_content_hash="a" * 64,
        workflow_job_id=replacement.id,
        workflow_attempt=replacement.attempt_count,
        lease_owner=replacement.lease_owner,
        now=now,
    )

    assert owner == _owner(replacement)
    assert replacement.result[REGENERATION_FENCE_RESULT_KEY]["workflow_attempt"] == 2


@pytest.mark.asyncio
async def test_clear_removes_only_the_exact_owned_fence_and_public_result_never_leaks_it():
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    variant_id, base_revision_id = uuid4(), uuid4()
    job = _job(now=now, result={"platforms": ["x"]})
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[job]),
        flush=AsyncMock(),
    )
    owner = await acquire_regeneration_fence(
        session,
        variant_id=variant_id,
        base_revision_id=base_revision_id,
        base_content_hash="a" * 64,
        workflow_job_id=job.id,
        workflow_attempt=job.attempt_count,
        lease_owner=job.lease_owner,
        now=now,
    )

    assert public_job_result(job.result) == {"platforms": ["x"]}
    assert not await clear_regeneration_fence(
        session,
        variant_id=variant_id,
        owner=RegenerationFenceOwner(
            workflow_job_id=uuid4(),
            workflow_attempt=owner.workflow_attempt,
            lease_owner=owner.lease_owner,
        ),
        now=now,
    )
    assert REGENERATION_FENCE_RESULT_KEY in job.result
    assert await clear_regeneration_fence(
        session,
        variant_id=variant_id,
        owner=owner,
        now=now,
    )
    assert job.result == {"platforms": ["x"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attempt", "lease_owner", "base_hash"),
    [
        (0, "worker-a", "a" * 64),
        (1, "", "a" * 64),
        (1, None, "a" * 64),
        (1, "worker-a", "not-a-hash"),
    ],
)
async def test_acquire_rejects_invalid_owner_or_base_before_query(attempt, lease_owner, base_hash):
    session = SimpleNamespace(scalars=AsyncMock(), flush=AsyncMock())

    with pytest.raises(RegenerationFenceConflict):
        await acquire_regeneration_fence(
            session,
            variant_id=uuid4(),
            base_revision_id=uuid4(),
            base_content_hash=base_hash,
            workflow_job_id=uuid4(),
            workflow_attempt=attempt,
            lease_owner=lease_owner,
        )

    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_malformed_fence_for_target_variant_fails_closed_and_query_is_bounded():
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    variant_id = uuid4()
    malformed = _job(now=now)
    malformed.result[REGENERATION_FENCE_RESULT_KEY] = {
        "variant_id": str(variant_id),
        "workflow_job_id": str(malformed.id),
    }
    session = SimpleNamespace(scalars=AsyncMock(return_value=[malformed]))

    with pytest.raises(RegenerationFenceConflict, match="invalid"):
        await require_revision_write_allowed(session, variant_id=variant_id, now=now)

    statement = session.scalars.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "workflow_jobs.status = 'running'" in sql
    assert "workflow_jobs.lease_expires_at IS NOT NULL" in sql
    assert "lower(" in sql
    assert str(variant_id) in sql
