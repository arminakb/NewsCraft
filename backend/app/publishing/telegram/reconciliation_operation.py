from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.capabilities import CapabilityStatusDependency
from app.automations.telegram.handlers import (
    sha256_canonical,
)
from app.db.session import get_session
from app.generation.models import PlatformVariantRevision
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin
from app.publishing.models import (
    Destination,
    Publication,
    PublishJob,
    PublishOperationReceipt,
)
from app.publishing.telegram.draft_publication import (
    revision_dispatch as _revision_dispatch,
)
from app.publishing.telegram.service import (
    PublishValidationError,
    derive_telegram_permalink,
    ordered_receipt_remote_ids,
    validate_reconciliation,
)

# This module owns the reconciliation operation's request model and handler
# body; app/api/telegram_drafts.py owns the route table that mounts it. It
# therefore declares no router of its own — a second APIRouter(prefix=
# "/telegram") here was never decorated and never mounted.
InjectedSession = Annotated[AsyncSession, Depends(get_session)]


class TelegramReconcileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["published", "not_published"]
    remote_message_ids: list[int] = Field(default_factory=list)
    permalink: HttpUrl | None = None
    operator_note: str | None = Field(default=None, min_length=5, max_length=1_000)

    @field_validator("operator_note", mode="before")
    @classmethod
    def normalize_operator_note(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_outcome_fields(self):
        if self.outcome == "not_published" and self.permalink is not None:
            raise ValueError("Not-published outcome cannot include a permalink")
        return self


def _publication_out(publication: Publication) -> dict[str, Any]:
    return {
        "id": publication.id,
        "publish_job_id": publication.publish_job_id,
        "destination_id": publication.destination_id,
        "platform_variant_revision_id": publication.platform_variant_revision_id,
        "remote_message_ids": list(publication.remote_message_ids),
        "permalink": publication.permalink,
        "payload_hash": publication.payload_hash,
        "published_at": publication.published_at,
        "reconciliation_status": publication.reconciliation_status,
    }


def _receipt_out(receipt: PublishOperationReceipt) -> dict[str, Any]:
    return {
        "id": receipt.id,
        "operation_index": receipt.operation_index,
        "operation_key": receipt.operation_key,
        "method": receipt.method,
        "request_hash": receipt.request_hash,
        "status": receipt.status,
        "attempt_count": receipt.attempt_count,
        "remote_message_ids": list(receipt.remote_message_ids),
        "response_metadata": redact_event_data(dict(receipt.response_metadata or {})),
        "next_attempt_at": receipt.next_attempt_at,
        "ambiguous_at": receipt.ambiguous_at,
        "completed_at": receipt.completed_at,
        "created_at": receipt.created_at,
        "updated_at": receipt.updated_at,
    }


def _validate_reconciled_remote_ids(
    receipt: Any,
    remote_message_ids: list[int],
    *,
    expected_count: int | None = None,
) -> None:
    if len(set(remote_message_ids)) != len(remote_message_ids):
        raise HTTPException(422, "Remote message IDs must be unique")
    if expected_count is not None:
        if expected_count <= 0 or len(remote_message_ids) != expected_count:
            raise HTTPException(422, "Remote message IDs do not match the publish operation")
        return
    if receipt.method == "sendMediaGroup":
        if len(remote_message_ids) < 2:
            raise HTTPException(422, "A media group requires at least two remote message IDs")
    elif len(remote_message_ids) != 1:
        raise HTTPException(422, "This Telegram operation requires exactly one remote message ID")


def _reconciliation_decision_fields(body: TelegramReconcileIn) -> dict[str, object]:
    return {
        "operator_note": body.operator_note,
        "outcome": body.outcome,
        "permalink": str(body.permalink) if body.permalink is not None else None,
        "remote_message_ids": list(body.remote_message_ids),
    }


def _reconciliation_decision_hash(body: TelegramReconcileIn) -> str:
    return sha256_canonical(_reconciliation_decision_fields(body))


def _reconciliation_generation(receipt: PublishOperationReceipt) -> dict[str, object]:
    return {
        "operation_key": receipt.operation_key,
        "attempt_count": receipt.attempt_count,
        "ambiguous_at": (receipt.ambiguous_at.isoformat() if receipt.ambiguous_at is not None else None),
    }


async def _reconciliation_events(
    session: AsyncSession,
    publish_job_id: UUID,
) -> list[WorkflowEvent]:
    return list(
        await session.scalars(
            select(WorkflowEvent)
            .where(
                WorkflowEvent.event_type.in_(
                    (
                        "telegram.publish.reconciled_not_published",
                        "telegram.publish.reconciled_published",
                    )
                ),
                WorkflowEvent.event_data["publish_job_id"].as_string() == str(publish_job_id),
            )
            .order_by(WorkflowEvent.created_at.desc(), WorkflowEvent.id.desc())
        )
    )


def _event_matches_reconciliation_generation(
    event: WorkflowEvent,
    receipts: list[PublishOperationReceipt],
) -> bool:
    event_data = event.event_data if isinstance(event.event_data, dict) else {}
    generation = event_data.get("reconciliation_generation")
    if not isinstance(generation, dict):
        return False
    operation_key = generation.get("operation_key")
    attempt_count = generation.get("attempt_count")
    receipt = next(
        (item for item in receipts if item.operation_key == operation_key),
        None,
    )
    if receipt is None or receipt.attempt_count != attempt_count:
        return False
    if receipt.ambiguous_at is not None:
        return generation.get("ambiguous_at") == receipt.ambiguous_at.isoformat()
    return True


async def _replay_reconciliation_decision(
    session: AsyncSession,
    event: WorkflowEvent,
    publish_job: PublishJob,
    receipts: list[PublishOperationReceipt],
    response: Response,
) -> dict[str, Any]:
    event_data = event.event_data if isinstance(event.event_data, dict) else {}
    if event_data.get("outcome") == "published":
        publication_id = _uuid_or_none(event_data.get("publication_id"))
        publication = (
            await session.scalar(
                select(Publication).where(
                    Publication.id == publication_id,
                    Publication.publish_job_id == publish_job.id,
                )
            )
            if publication_id is not None
            else None
        )
        if publication is None:
            raise HTTPException(409, "Prior reconciliation result is unavailable")
        return _publication_out(publication)

    if event_data.get("outcome") == "not_published":
        workflow_job_id = _uuid_or_none(event_data.get("requeued_workflow_job_id"))
        requeued_job_status = event_data.get("requeued_job_status")
        requeued_job_deduplicated = event_data.get("requeued_job_deduplicated")
        workflow_job = await session.get(WorkflowJob, workflow_job_id) if workflow_job_id is not None else None
        if (
            workflow_job is None
            or not isinstance(requeued_job_status, str)
            or not isinstance(requeued_job_deduplicated, bool)
        ):
            raise HTTPException(409, "Prior reconciliation result is unavailable")
        response.status_code = 202
        return {
            "publish_job_id": publish_job.id,
            "reconciliation_status": "requeued",
            "job": {
                "job_id": workflow_job.id,
                "status": requeued_job_status,
                "deduplicated": requeued_job_deduplicated,
            },
            "receipts": [_receipt_out(receipt) for receipt in receipts],
        }

    raise HTTPException(409, "Prior reconciliation result is unavailable")


def _uuid_or_none(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except TypeError, ValueError:
        return None


def _reconciliation_event_data(
    *,
    body: TelegramReconcileIn,
    publish_job: PublishJob,
    receipts: list[PublishOperationReceipt],
    generation: dict[str, object],
    result_ids: dict[str, object],
) -> dict[str, object]:
    return redact_event_data(
        {
            "publish_job_id": str(publish_job.id),
            "decision_hash": _reconciliation_decision_hash(body),
            "operation_keys": [receipt.operation_key for receipt in receipts],
            **_reconciliation_decision_fields(body),
            **result_ids,
            "reconciliation_generation": generation,
        }
    )


async def _requeue_not_published(
    session: AsyncSession,
    *,
    body: TelegramReconcileIn,
    publish_job: PublishJob,
    receipts: list[PublishOperationReceipt],
    ambiguous: PublishOperationReceipt,
    observed_at: datetime,
    generation: dict[str, object],
    response: Response,
) -> dict[str, Any]:
    ambiguous.status = "pending"
    ambiguous.remote_message_ids = []
    ambiguous.response_metadata = {}
    ambiguous.next_attempt_at = None
    ambiguous.ambiguous_at = None
    ambiguous.completed_at = None
    ambiguous.updated_at = observed_at
    publish_job.status = "queued"
    publish_job.scheduled_for = observed_at
    publish_job.updated_at = observed_at
    result = await JobRepository(session).enqueue_job(
        job_type="telegram.publish",
        payload={"publish_job_id": str(publish_job.id)},
        idempotency_key=(
            f"telegram-publish-reconcile:{publish_job.id}:{ambiguous.operation_key}:{ambiguous.attempt_count}"
        ),
        origin=JobOrigin.RETRY,
    )
    publish_job.workflow_job_id = result.job.id
    session.add(
        WorkflowEvent(
            workflow_job_id=result.job.id,
            event_type="telegram.publish.reconciled_not_published",
            actor="operator",
            event_data=_reconciliation_event_data(
                body=body,
                publish_job=publish_job,
                receipts=receipts,
                generation=generation,
                result_ids={
                    "requeued_workflow_job_id": str(result.job.id),
                    "requeued_job_status": result.job.status,
                    "requeued_job_deduplicated": not result.created,
                },
            ),
        )
    )
    await session.flush()
    response.status_code = 202
    return {
        "publish_job_id": publish_job.id,
        "reconciliation_status": "requeued",
        "job": {
            "job_id": result.job.id,
            "status": result.job.status,
            "deduplicated": not result.created,
        },
        "receipts": [_receipt_out(receipt) for receipt in receipts],
    }


async def _confirm_published(
    session: AsyncSession,
    *,
    body: TelegramReconcileIn,
    publish_job: PublishJob,
    destination: Destination,
    receipts: list[PublishOperationReceipt],
    ambiguous: PublishOperationReceipt,
    observed_at: datetime,
    generation: dict[str, object],
) -> dict[str, Any]:
    _validate_reconciled_remote_ids(ambiguous, body.remote_message_ids)
    ambiguous.status = "succeeded"
    ambiguous.remote_message_ids = list(body.remote_message_ids)
    ambiguous.response_metadata = {
        "operator_confirmed": True,
        "reconciliation_outcome": "published",
    }
    ambiguous.next_attempt_at = None
    ambiguous.completed_at = observed_at
    ambiguous.updated_at = observed_at
    try:
        remote_ids = ordered_receipt_remote_ids(receipts)
    except PublishValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    permalink = (
        str(body.permalink)
        if body.permalink is not None
        else derive_telegram_permalink(destination.target_ref, remote_ids)
    )
    existing = await session.scalar(
        select(Publication).where(Publication.publish_job_id == publish_job.id).with_for_update()
    )
    if existing is None:
        publication = Publication(
            publish_job_id=publish_job.id,
            destination_id=publish_job.destination_id,
            platform_variant_revision_id=publish_job.platform_variant_revision_id,
            remote_message_ids=remote_ids,
            permalink=permalink,
            payload_hash=publish_job.payload_hash,
            published_at=observed_at,
            reconciliation_status="confirmed",
        )
        session.add(publication)
    else:
        if (
            existing.destination_id != publish_job.destination_id
            or existing.platform_variant_revision_id != publish_job.platform_variant_revision_id
            or existing.payload_hash != publish_job.payload_hash
            or list(existing.remote_message_ids) != remote_ids
            or existing.permalink != permalink
            or existing.reconciliation_status != "confirmed"
        ):
            raise HTTPException(409, "Telegram publication conflicts with reconciliation")
        publication = existing
    publish_job.status = "succeeded"
    publish_job.scheduled_for = None
    publish_job.updated_at = observed_at
    revision = await session.get(
        PlatformVariantRevision,
        publish_job.platform_variant_revision_id,
    )
    dispatch = await _revision_dispatch(session, revision) if revision is not None else None
    if dispatch is not None:
        dispatch.status = "published"
        dispatch.publish_job_id = publish_job.id
    await session.flush()
    session.add(
        WorkflowEvent(
            workflow_job_id=publish_job.workflow_job_id,
            event_type="telegram.publish.reconciled_published",
            actor="operator",
            event_data=_reconciliation_event_data(
                body=body,
                publish_job=publish_job,
                receipts=receipts,
                generation=generation,
                result_ids={
                    "publication_id": str(publication.id),
                },
            ),
        )
    )
    await session.flush()
    return _publication_out(publication)


async def reconcile_telegram_publish_job(
    publish_job_id: UUID,
    body: TelegramReconcileIn,
    response: Response,
    session: InjectedSession,
    capability_status: CapabilityStatusDependency,
):
    async with session.begin():
        publish_job = await session.scalar(select(PublishJob).where(PublishJob.id == publish_job_id).with_for_update())
        if publish_job is None:
            raise HTTPException(404, "Telegram publish job not found")
        destination = await session.get(Destination, publish_job.destination_id)
        if destination is None or destination.platform != "telegram":
            raise HTTPException(404, "Telegram publish job not found")
        if body.outcome == "not_published":
            await capability_status.require_available(
                "destination",
                destination.id,
                "publishing",
                job_type="telegram.publish",
            )
        receipts = list(
            await session.scalars(
                select(PublishOperationReceipt)
                .where(PublishOperationReceipt.publish_job_id == publish_job.id)
                .order_by(PublishOperationReceipt.operation_index)
                .with_for_update()
            )
        )
        decision_hash = _reconciliation_decision_hash(body)
        prior_events = await _reconciliation_events(session, publish_job.id)
        prior_event = next(
            (event for event in prior_events if _event_matches_reconciliation_generation(event, receipts)),
            None,
        )
        if prior_event is not None:
            event_data = prior_event.event_data if isinstance(prior_event.event_data, dict) else {}
            if event_data.get("decision_hash") != decision_hash:
                raise HTTPException(409, "Conflicting reconciliation decision")
            return await _replay_reconciliation_decision(
                session,
                prior_event,
                publish_job,
                receipts,
                response,
            )
        if any(
            isinstance(event.event_data, dict) and event.event_data.get("decision_hash") == decision_hash
            for event in prior_events
        ):
            raise HTTPException(409, "Stale reconciliation decision")

        try:
            ambiguous = validate_reconciliation(
                receipts,
                outcome=body.outcome,
                remote_message_ids=body.remote_message_ids,
            )
        except PublishValidationError as exc:
            raise HTTPException(409, str(exc)) from None

        observed_at = datetime.now(UTC)
        generation = _reconciliation_generation(ambiguous)

        if body.outcome == "not_published":
            return await _requeue_not_published(
                session,
                body=body,
                publish_job=publish_job,
                receipts=receipts,
                ambiguous=ambiguous,
                observed_at=observed_at,
                generation=generation,
                response=response,
            )
        return await _confirm_published(
            session,
            body=body,
            publish_job=publish_job,
            destination=destination,
            receipts=receipts,
            ambiguous=ambiguous,
            observed_at=observed_at,
            generation=generation,
        )
