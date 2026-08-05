from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps
from typing import Any

from app.automations.definitions.runtime_state import (
    sync_automation_job_failed,
    sync_automation_job_succeeded,
)
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution


def with_automation_projection(handler: JobHandler) -> JobHandler:
    """Project only explicitly linked Automation jobs; unrelated workers stay untouched."""

    @wraps(handler)
    async def wrapped(job: JobExecution, context: JobContext) -> dict[str, Any]:
        if job.automation_run_id is None or job.automation_node_run_id is None:
            return await handler(job, context)
        try:
            result = await handler(job, context)
        except NeedsReviewJobError as exc:
            row = await context.session.get(WorkflowJob, job.id)
            if row is not None:
                await sync_automation_job_failed(
                    context.session,
                    job=row,
                    error_code=exc.code,
                    error_message=exc.message,
                    observed_at=datetime.now(UTC),
                    terminal=False,
                    waiting_for_review=True,
                )
            raise
        except PermanentJobError as exc:
            row = await context.session.get(WorkflowJob, job.id)
            if row is not None:
                await sync_automation_job_failed(
                    context.session,
                    job=row,
                    error_code=exc.code,
                    error_message=exc.message,
                    observed_at=datetime.now(UTC),
                    terminal=True,
                    waiting_for_review=False,
                )
            raise
        except RetryableJobError as exc:
            if job.attempt_count >= job.max_attempts:
                row = await context.session.get(WorkflowJob, job.id)
                if row is not None:
                    await sync_automation_job_failed(
                        context.session,
                        job=row,
                        error_code=exc.code,
                        error_message=exc.message,
                        observed_at=datetime.now(UTC),
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
