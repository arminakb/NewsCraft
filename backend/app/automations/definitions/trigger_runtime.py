"""Shared runtime for the event-trigger job handlers.

The ``new_source_item`` and ``collection_article_added`` handlers drive the
same automation-run state machine: they load the run/node pair the job is
linked to under ``FOR UPDATE``, validate that the link still matches the
payload, and later close the run out with a terminal status plus a
``WorkflowEvent``. Keeping one implementation here means a change to the
locking, the validity check, or the emitted event shape lands in both
handlers at once instead of drifting between two hand-maintained copies.

Only the error-code prefix, the human-readable subject, and the identifier
echoed back in the handler result differ per trigger, so those are
parameters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.models import AutomationNodeRun, AutomationRun
from app.db.models import ContentItem
from app.jobs.errors import PermanentJobError
from app.jobs.models import WorkflowEvent
from app.jobs.types import JobExecution


def utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime, assuming UTC when naive."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso(value: datetime | None) -> str | None:
    return utc(value).isoformat() if value is not None else None


def primary_media(item: ContentItem) -> dict[str, object] | None:
    """Serialise the item's primary media into the trigger output shape."""

    media = item.primary_media
    if media is None:
        return None
    return {
        "id": str(media.id),
        "url": media.normalized_url,
        "kind": media.kind,
        "mime_type": media.mime_type,
        "width": media.width,
        "height": media.height,
        "alt_text": media.alt_text,
    }


class TriggerRunLink(Protocol):
    """The payload fields every trigger job carries to identify its run."""

    @property
    def automation_id(self) -> UUID: ...

    @property
    def automation_version_id(self) -> UUID: ...

    @property
    def trigger_node_id(self) -> str: ...


async def load_trigger_run(
    session: AsyncSession,
    *,
    job: JobExecution,
    payload: TriggerRunLink,
    error_prefix: str,
    subject: str,
) -> tuple[AutomationRun, AutomationNodeRun]:
    """Lock and validate the automation run/node this trigger job belongs to.

    ``error_prefix`` names the permanent-error family (``<prefix>_link_missing``
    / ``<prefix>_link_invalid``) and ``subject`` is the handler-facing noun used
    in the message text.
    """

    if job.automation_run_id is None or job.automation_node_run_id is None:
        raise PermanentJobError(
            code=f"{error_prefix}_link_missing",
            message=f"{subject} is not linked to an Automation run",
        )
    run = await session.scalar(select(AutomationRun).where(AutomationRun.id == job.automation_run_id).with_for_update())
    node = await session.scalar(
        select(AutomationNodeRun).where(AutomationNodeRun.id == job.automation_node_run_id).with_for_update()
    )
    if (
        run is None
        or node is None
        or node.automation_run_id != run.id
        or run.automation_id != payload.automation_id
        or run.automation_version_id != payload.automation_version_id
        or node.node_id != payload.trigger_node_id
    ):
        raise PermanentJobError(
            code=f"{error_prefix}_link_invalid",
            message=f"{subject} references an invalid Automation run",
        )
    return run, node


async def finish_trigger_run(
    session: AsyncSession,
    *,
    job: JobExecution,
    run: AutomationRun,
    node: AutomationNodeRun,
    outcome: str,
    status: Literal["succeeded", "failed", "cancelled"],
    observed_at: datetime,
    result_key: str,
    error_code: str | None = None,
    error_message: str | None = None,
    output: dict[str, object] | None = None,
) -> dict[str, object]:
    """Close out the run and its trigger node, emitting the terminal event.

    ``result_key`` is both the trigger-metadata key holding the subject
    identifier and the key it is echoed under in the handler result.
    """

    node.status = "succeeded" if status == "succeeded" else "failed" if status == "failed" else "skipped"
    node.started_at = node.started_at or observed_at
    node.finished_at = observed_at
    if output is not None:
        node.output_summary = output
    if error_code is not None:
        node.safe_error_code = error_code
        node.safe_error_message = error_message
    run.status = status
    run.current_node_id = None if status == "succeeded" else node.node_id
    run.safe_error_code = error_code
    run.safe_error_message = error_message
    run.finished_at = observed_at
    if status == "succeeded":
        event_type = "automation.run.completed"
    elif status == "cancelled":
        event_type = "automation.run.cancelled"
    else:
        event_type = "automation.run.failed"
    session.add(
        WorkflowEvent(
            workflow_job_id=job.id,
            event_type=event_type,
            actor="automation",
            event_data={
                "automation_run_id": str(run.id),
                "outcome": outcome,
                "error_code": error_code,
            },
        )
    )
    return {
        "outcome": outcome,
        "run_id": str(run.id),
        result_key: str(run.trigger_metadata.get(result_key)),
    }
