"""Regression proof: automation failure projection survives the worker rollback.

``app/jobs/worker.py`` ``_execute_handler`` rolls the handler session back for
every classified failure, so ``with_automation_projection`` must own the
transaction that persists the failure instead of writing into the poisoned one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.automations.definitions.handler_wrapper import with_automation_projection
from app.automations.definitions.models import AutomationNodeRun, AutomationRun
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext
from app.jobs.types import JobExecution, JobOrigin


class _FakeTransaction:
    def __init__(self, session: _RecordingSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeTransaction:
        self._session.log.append("begin")
        self._session.active = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self._session.active = False
        self._session.log.append("rollback" if exc_type is not None else "commit")
        if exc_type is None:
            self._session.committed.extend(self._session.pending)
        self._session.pending.clear()
        return False


class _RecordingSession:
    """Minimal AsyncSession stand-in that records transaction boundaries."""

    def __init__(self, *, job: WorkflowJob, run: AutomationRun, node: AutomationNodeRun) -> None:
        self.log: list[str] = []
        self.pending: list[Any] = []
        self.committed: list[Any] = []
        self.active = False
        self._job = job
        self._run = run
        self._node = node

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    async def rollback(self) -> None:
        self.active = False
        self.log.append("rollback")
        self.pending.clear()

    async def get(self, _model: Any, _identity: Any) -> WorkflowJob:
        self.active = True
        return self._job

    async def scalar(self, statement: Any) -> Any:
        self.active = True
        entity = statement.column_descriptions[0]["entity"]
        if entity is AutomationRun:
            return self._run
        if entity is AutomationNodeRun:
            return self._node
        return None

    def add(self, instance: Any) -> None:
        self.pending.append(instance)


def _fixture() -> tuple[JobExecution, JobContext, _RecordingSession, AutomationRun, AutomationNodeRun]:
    job_id = uuid4()
    run_id = uuid4()
    node_run_id = uuid4()
    run = AutomationRun(
        id=run_id,
        automation_id=uuid4(),
        automation_version_id=uuid4(),
        trigger_kind="manual",
        trigger_metadata={},
        dry_run=False,
        status="running",
        current_node_id="generate-1",
    )
    node = AutomationNodeRun(
        id=node_run_id,
        automation_run_id=run_id,
        node_id="generate-1",
        status="running",
    )
    workflow_job = WorkflowJob(
        id=job_id,
        job_type="content_pack.generate",
        payload={},
        automation_run_id=run_id,
        automation_node_run_id=node_run_id,
    )
    session = _RecordingSession(job=workflow_job, run=run, node=node)
    execution = JobExecution(
        id=job_id,
        job_type="content_pack.generate",
        payload={},
        attempt_count=3,
        max_attempts=3,
        origin=JobOrigin.AUTOMATION,
        lease_owner="worker-1",
        created_at=datetime.now(UTC),
        scheduled_for=None,
        priority=0,
        pause_sensitive=True,
        automation_run_id=run_id,
        automation_node_run_id=node_run_id,
    )
    context = JobContext(session=session, providers=SimpleNamespace())  # type: ignore[arg-type]
    return execution, context, session, run, node


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (PermanentJobError(code="boom", message="permanent"), "failed"),
        (NeedsReviewJobError(code="review", message="needs review"), "waiting_for_review"),
        (RetryableJobError(code="retry", message="exhausted"), "failed"),
    ],
)
@pytest.mark.asyncio
async def test_failure_projection_is_committed_before_the_worker_rolls_back(
    error: Exception,
    expected_status: str,
) -> None:
    execution, context, session, run, node = _fixture()

    async def handler(_job: JobExecution, _context: JobContext) -> dict[str, Any]:
        session.active = True
        session.add(object())  # handler work the worker will discard
        raise error

    wrapped = with_automation_projection(handler)

    with pytest.raises(type(error)):
        await wrapped(execution, context)

    # The handler's poisoned transaction is discarded first, then the projection
    # owns its own committed transaction.
    assert session.log[:2] == ["rollback", "begin"], session.log
    assert session.log[-1] == "commit", session.log
    assert run.status == expected_status
    assert node.status == expected_status
    # The durable failure event is inside the committed set, not the discarded one.
    assert len(session.committed) == 1
    assert session.committed[0].event_type in {
        "automation.run.failed",
        "automation.run.review_boundary",
    }


@pytest.mark.asyncio
async def test_retryable_failure_with_attempts_left_does_not_project() -> None:
    execution, context, session, run, node = _fixture()
    execution = execution.__class__(
        **{**{field: getattr(execution, field) for field in execution.__dataclass_fields__}, "attempt_count": 1}
    )

    async def handler(_job: JobExecution, _context: JobContext) -> dict[str, Any]:
        raise RetryableJobError(code="retry", message="try again")

    wrapped = with_automation_projection(handler)

    with pytest.raises(RetryableJobError):
        await wrapped(execution, context)

    assert session.log == []
    assert run.status == "running"
    assert node.status == "running"
