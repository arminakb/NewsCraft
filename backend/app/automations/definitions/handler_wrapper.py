from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps
from typing import Any
from uuid import UUID

from app.automations.definitions.runtime_state import (
    sync_automation_job_failed,
    sync_automation_job_succeeded,
)
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution


async def _persist_automation_failure(
    context: JobContext,
    *,
    job_id: UUID,
    error_code: str,
    error_message: str,
    terminal: bool,
    waiting_for_review: bool,
) -> None:
    """Commit the failure projection in its own transaction.

    The handler's transaction is poisoned by the raised error and the worker
    rolls it back (``app/jobs/worker.py`` ``_execute_handler``), so the
    projection has to roll back first and then own a fresh transaction —
    exactly how ``app/automations/telegram/process_operations.py`` persists its
    post-failure dispatch state.
    """

    session = context.session
    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        row = await session.get(WorkflowJob, job_id)
        if row is None:
            return
        await sync_automation_job_failed(
            session,
            job=row,
            error_code=error_code,
            error_message=error_message,
            observed_at=datetime.now(UTC),
            terminal=terminal,
            waiting_for_review=waiting_for_review,
        )


def with_automation_projection(handler: JobHandler) -> JobHandler:
    """Project only explicitly linked Automation jobs; unrelated workers stay untouched."""

    @wraps(handler)
    async def wrapped(job: JobExecution, context: JobContext) -> dict[str, Any]:
        if job.automation_run_id is None or job.automation_node_run_id is None:
            return await handler(job, context)
        try:
            result = await handler(job, context)
        except NeedsReviewJobError as exc:
            await _persist_automation_failure(
                context,
                job_id=job.id,
                error_code=exc.code,
                error_message=exc.message,
                terminal=False,
                waiting_for_review=True,
            )
            raise
        except PermanentJobError as exc:
            await _persist_automation_failure(
                context,
                job_id=job.id,
                error_code=exc.code,
                error_message=exc.message,
                terminal=True,
                waiting_for_review=False,
            )
            raise
        except RetryableJobError as exc:
            if job.attempt_count >= job.max_attempts:
                await _persist_automation_failure(
                    context,
                    job_id=job.id,
                    error_code=exc.code,
                    error_message=exc.message,
                    terminal=True,
                    waiting_for_review=False,
                )
            raise
        row = await context.session.get(WorkflowJob, job.id)
        if row is not None:
            await sync_automation_job_succeeded(
                context.session,
                job=row,
                result=result,
                observed_at=datetime.now(UTC),
            )
        return result

    wrapped.__annotations__ = {
        "job": JobExecution,
        "context": JobContext,
        "return": dict[str, Any],
    }
    return wrapped


__all__ = ["with_automation_projection"]
