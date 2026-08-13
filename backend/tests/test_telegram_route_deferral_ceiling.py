from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.automations.telegram.route_fetch import MAX_DEFER_SEQUENCE, _defer_route_job
from app.jobs.errors import NeedsReviewJobError

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class _Queue:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    async def enqueue_job(self, **kwargs):
        self.jobs.append(kwargs)
        return SimpleNamespace(created=True, job=SimpleNamespace(id=uuid4()))


def _context() -> SimpleNamespace:
    return SimpleNamespace(session=object())


def _job(defer_sequence: int | None, *, root_job_id: str | None = None) -> SimpleNamespace:
    payload: dict = {"route_id": str(uuid4())}
    if defer_sequence is not None:
        payload["defer_sequence"] = defer_sequence
    if root_job_id is not None:
        payload["defer_root_job_id"] = root_job_id
    return SimpleNamespace(id=uuid4(), job_type="telegram.route.poll", payload=payload)


async def test_deferral_chain_stops_at_the_ceiling_instead_of_enqueueing_forever():
    """A route left paused must not accrue queue rows without limit.

    Each deferral re-enqueues under a new idempotency key (the sequence is in
    the key), so nothing collapses the chain. Before the ceiling this call
    simply enqueued link 721 and every link after it; now it terminates the
    chain in a visible needs_review state and writes nothing.
    """

    queue = _Queue()
    route = SimpleNamespace(id=uuid4())

    with pytest.raises(NeedsReviewJobError) as excinfo:
        await _defer_route_job(
            _context(),
            repository=queue,
            route=route,
            job=_job(MAX_DEFER_SEQUENCE, root_job_id=str(uuid4())),
            scheduled_for=NOW + timedelta(seconds=30),
        )

    assert excinfo.value.code == "telegram_route_deferral_exhausted"
    assert queue.jobs == []


async def test_deferral_below_the_ceiling_still_extends_the_chain():
    queue = _Queue()
    route = SimpleNamespace(id=uuid4())
    root_job_id = str(uuid4())

    await _defer_route_job(
        _context(),
        repository=queue,
        route=route,
        job=_job(MAX_DEFER_SEQUENCE - 1, root_job_id=root_job_id),
        scheduled_for=NOW + timedelta(seconds=30),
    )

    assert len(queue.jobs) == 1
    enqueued = queue.jobs[0]
    assert enqueued["payload"]["defer_sequence"] == MAX_DEFER_SEQUENCE
    assert enqueued["payload"]["defer_root_job_id"] == root_job_id
    assert enqueued["idempotency_key"] == (
        f"telegram-route-deferred:{route.id}:{root_job_id}:{MAX_DEFER_SEQUENCE}"
    )


async def test_first_deferral_roots_the_chain_at_the_current_job():
    queue = _Queue()
    route = SimpleNamespace(id=uuid4())
    job = _job(None)

    await _defer_route_job(
        _context(),
        repository=queue,
        route=route,
        job=job,
        scheduled_for=NOW + timedelta(seconds=30),
    )

    enqueued = queue.jobs[0]
    assert enqueued["payload"]["defer_sequence"] == 1
    assert enqueued["payload"]["defer_root_job_id"] == str(job.id)


async def test_a_chain_already_past_the_ceiling_is_not_extended():
    """Rows enqueued before the ceiling existed drain into review, not more rows."""

    queue = _Queue()

    with pytest.raises(NeedsReviewJobError):
        await _defer_route_job(
            _context(),
            repository=queue,
            route=SimpleNamespace(id=uuid4()),
            job=_job(MAX_DEFER_SEQUENCE + 5_000, root_job_id=str(uuid4())),
            scheduled_for=NOW + timedelta(seconds=30),
        )

    assert queue.jobs == []
