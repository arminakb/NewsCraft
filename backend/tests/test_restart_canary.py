from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.jobs.canary import (
    PUBLISHING_CANARY,
    SOURCE_GENERATION_CANARY,
    handle_worker_canary,
)
from app.jobs.errors import PermanentJobError
from app.jobs.types import JobExecution, JobOrigin


def _execution(
    job_type: str,
    target: str,
    *,
    hold_seconds: float = 0,
) -> JobExecution:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    return JobExecution.from_job(
        SimpleNamespace(
            id=uuid4(),
            job_type=job_type,
            payload={"target": target, "hold_seconds": hold_seconds},
            attempt_count=1,
            max_attempts=1,
            origin=JobOrigin.MANUAL,
            lease_owner="canary-worker",
            created_at=now,
            scheduled_for=now,
            priority=0,
            pause_sensitive=False,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_type", "target"),
    [
        (SOURCE_GENERATION_CANARY, "source-generation"),
        (PUBLISHING_CANARY, "publishing"),
    ],
)
async def test_worker_restart_canary_completes_without_external_side_effects(
    job_type,
    target,
):
    result = await handle_worker_canary(_execution(job_type, target), object())

    assert result == {"target": target, "status": "completed"}


@pytest.mark.asyncio
async def test_worker_restart_canary_rejects_cross_capability_target():
    with pytest.raises(PermanentJobError, match="target"):
        await handle_worker_canary(
            _execution(SOURCE_GENERATION_CANARY, "publishing"),
            object(),
        )


@pytest.mark.asyncio
async def test_worker_restart_canary_supports_a_bounded_no_side_effect_hold(
    monkeypatch,
):
    sleep = AsyncMock()
    monkeypatch.setattr("app.jobs.canary.asyncio.sleep", sleep)

    result = await handle_worker_canary(
        _execution(
            SOURCE_GENERATION_CANARY,
            "source-generation",
            hold_seconds=30,
        ),
        object(),
    )

    assert result == {"target": "source-generation", "status": "completed"}
    sleep.assert_awaited_once_with(30.0)
