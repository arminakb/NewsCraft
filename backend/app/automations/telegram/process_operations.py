from __future__ import annotations

import logging
from functools import partial
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.automations.models import AutomationDispatch
from app.automations.telegram.handler_contracts import (
    ProcessDispatchPayload,
)
from app.automations.telegram.process_dispatch import (
    TelegramProcessDependencies,
    _process_route_dispatch,
)
from app.core.faults import FaultInjector, NoopFaultInjector
from app.core.redaction import redact_string
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution, job_payload_copy

logger = logging.getLogger(__name__)


async def _handle_process_route_dispatch(
    job: JobExecution,
    context: JobContext,
    *,
    dependencies: TelegramProcessDependencies,
) -> dict[str, Any]:
    workflow_job_id = job.id
    failure_payload = job_payload_copy(job)
    try:
        return await _process_route_dispatch(job, context, dependencies=dependencies)
    except (RetryableJobError, NeedsReviewJobError, PermanentJobError) as exc:
        session = context.session
        if session.in_transaction():
            await session.rollback()
        try:
            payload = ProcessDispatchPayload.model_validate(failure_payload)
        except ValidationError:
            raise exc from None
        async with session.begin():
            dispatch = await session.scalar(
                select(AutomationDispatch).where(AutomationDispatch.id == payload.dispatch_id).with_for_update()
            )
            if dispatch is not None and dispatch.variant_revision_id is None:
                dispatch.status = (
                    "needs_review"
                    if isinstance(exc, NeedsReviewJobError)
                    else "retryable"
                    if isinstance(exc, RetryableJobError)
                    else "failed"
                )
                dispatch.error_code = redact_string(exc.code)
                dispatch.error_message = redact_string(exc.message)
                event_type = (
                    "telegram.process.deferred"
                    if exc.code == "telegram_route_lineage_waiting"
                    else "telegram.process.blocked"
                    if exc.code == "telegram_route_lineage_blocked"
                    else "telegram.generation.failed"
                )
                session.add(
                    WorkflowEvent(
                        workflow_job_id=workflow_job_id,
                        event_type=event_type,
                        actor="automation",
                        event_data=redact_event_data(
                            {
                                "dispatch_id": str(dispatch.id),
                                "error_class": (
                                    "needs_review"
                                    if isinstance(exc, NeedsReviewJobError)
                                    else "retryable"
                                    if isinstance(exc, RetryableJobError)
                                    else "permanent"
                                ),
                                "error_code": exc.code,
                                "error_message": exc.message,
                            }
                        ),
                    )
                )
        raise


def build_telegram_process_handler(
    profile_resolver: Any,
    *,
    fault_injector: FaultInjector | None = None,
) -> JobHandler:
    dependencies = TelegramProcessDependencies(
        profile_resolver=profile_resolver,
        fault_injector=fault_injector or NoopFaultInjector(),
    )
    handler = partial(_handle_process_route_dispatch, dependencies=dependencies)
    handler.__annotations__ = {
        "job": JobExecution,
        "context": JobContext,
        "return": dict[str, Any],
    }
    return handler


async def process_route_dispatch(
    job: JobExecution,
    context: JobContext,
    *,
    profile_resolver: Any,
) -> dict[str, Any]:
    """Process one durable Telegram dispatch with explicit dependencies."""

    return await _handle_process_route_dispatch(
        job,
        context,
        dependencies=TelegramProcessDependencies(
            profile_resolver=profile_resolver,
            fault_injector=NoopFaultInjector(),
        ),
    )
