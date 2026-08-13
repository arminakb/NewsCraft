from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.capabilities import CapabilityStatusDependency
from app.api.dependencies import InjectedSession, SessionDependency
from app.automations.definitions.runtime_state import bind_automation_publish_job
from app.automations.models import AutomationDispatch
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.jobs.models import WorkflowJob
from app.jobs.schemas import JobAcceptedOut
from app.publishing.models import (
    Destination,
    Publication,
    PublishJob,
    PublishOperationReceipt,
)
from app.publishing.telegram.draft_publication import (
    ReviewedTelegramDraftError,
    publish_reviewed_draft,
)
from app.publishing.telegram.draft_publication import (
    revision_dispatch as _revision_dispatch,
)
from app.publishing.telegram.reconciliation_operation import (
    TelegramReconcileIn,
    _publication_out,
    _receipt_out,
    _validate_reconciled_remote_ids,
)
from app.publishing.telegram.reconciliation_operation import (
    reconcile_telegram_publish_job as _reconcile_telegram_publish_job,
)
from app.publishing.telegram.service import (
    ReconciliationCase,
    ReviewedTelegramScheduleError,
    get_reconciliation_case,
    list_reconciliation_cases,
    schedule_reviewed_telegram,
)

__all__ = [
    "ScheduleTelegramIn",
    "TelegramContentHashIn",
    "TelegramReconcileIn",
    "_publication_out",
    "_validate_reconciled_remote_ids",
    "publish_telegram_draft",
    "reconcile_telegram_publish_job",
    "router",
    "schedule_telegram_revision",
]

router = APIRouter(prefix="/telegram", tags=["telegram"])
draft_router = APIRouter(prefix="/drafts")
#: Every telegram revision ever written is a candidate here; the listing reads
#: newest-first, so this ceiling trims only the tail of the outcome history.
OUTCOME_CEILING = 200


class TelegramContentHashIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ScheduleTelegramIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination_id: UUID
    scheduled_for: AwareDatetime

    @field_validator("scheduled_for")
    @classmethod
    def normalize_scheduled_for(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class TelegramPublicationOut(BaseModel):
    id: UUID
    publish_job_id: UUID
    destination_id: UUID
    platform_variant_revision_id: UUID
    remote_message_ids: list[int]
    permalink: str | None
    payload_hash: str
    published_at: datetime
    reconciliation_status: str


class TelegramPublicationContextOut(BaseModel):
    revision_id: UUID
    platform_variant_id: UUID
    revision_number: int
    approval_state: str
    route_id: UUID | None
    dispatch_id: UUID | None
    publish_job_id: UUID | None
    publish_status: str | None
    publication: TelegramPublicationOut | None


class TelegramPublishIntentOut(BaseModel):
    publish_job_id: UUID
    workflow_job_id: UUID | None
    status: str


class TelegramPublishAcceptedOut(BaseModel):
    revision_id: UUID
    job: TelegramPublishIntentOut


def _publish_job_out(
    publish_job: PublishJob,
    receipts: Iterable[PublishOperationReceipt],
    publication: Publication | None,
) -> dict[str, Any]:
    return {
        "publish_job_id": publish_job.id,
        "workflow_job_id": publish_job.workflow_job_id,
        "destination_id": publish_job.destination_id,
        "platform_variant_revision_id": publish_job.platform_variant_revision_id,
        "status": publish_job.status,
        "payload_hash": publish_job.payload_hash,
        "scheduled_for": publish_job.scheduled_for,
        "created_at": publish_job.created_at,
        "updated_at": publish_job.updated_at,
        "receipts": [_receipt_out(receipt) for receipt in receipts],
        "publication": _publication_out(publication) if publication is not None else None,
    }


async def _publication_context_out(
    session: AsyncSession,
    revision: PlatformVariantRevision,
) -> TelegramPublicationContextOut:
    dispatch = await _revision_dispatch(session, revision)
    publish_job = await session.scalar(
        select(PublishJob)
        .where(PublishJob.platform_variant_revision_id == revision.id)
        .order_by(PublishJob.created_at.desc())
        .limit(1)
    )
    publication = (
        await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job.id))
        if publish_job is not None
        else None
    )
    return _publication_context(revision, dispatch, publish_job, publication)


def _publication_context(
    revision: PlatformVariantRevision,
    dispatch: AutomationDispatch | None,
    publish_job: PublishJob | None,
    publication: Publication | None,
) -> TelegramPublicationContextOut:
    return TelegramPublicationContextOut(
        revision_id=revision.id,
        platform_variant_id=revision.platform_variant_id,
        revision_number=revision.revision_number,
        approval_state=revision.approval_state,
        route_id=dispatch.route_id if dispatch is not None else None,
        dispatch_id=dispatch.id if dispatch is not None else None,
        publish_job_id=publish_job.id if publish_job is not None else None,
        publish_status=publish_job.status if publish_job is not None else None,
        publication=(
            TelegramPublicationOut.model_validate(_publication_out(publication)) if publication is not None else None
        ),
    )


@router.get("/publication-outcomes", response_model=list[TelegramPublicationContextOut])
async def list_telegram_publication_outcomes(
    session: AsyncSession = SessionDependency,
) -> list[TelegramPublicationContextOut]:
    statement = (
        select(PlatformVariantRevision)
        .join(PlatformVariant, PlatformVariant.id == PlatformVariantRevision.platform_variant_id)
        .where(PlatformVariant.platform == "telegram")
        .order_by(
            PlatformVariantRevision.created_at.desc(),
            PlatformVariantRevision.revision_number.desc(),
        )
        .limit(OUTCOME_CEILING)
    )
    revisions = list(await session.scalars(statement))
    if not revisions:
        return []

    revision_by_id = {revision.id: revision for revision in revisions}
    revision_ids = list(revision_by_id)
    dispatches = list(
        await session.scalars(
            select(AutomationDispatch)
            .where(AutomationDispatch.variant_revision_id.in_(revision_ids))
            .order_by(AutomationDispatch.created_at.desc())
        )
    )
    direct_dispatches: dict[UUID, AutomationDispatch] = {}
    for dispatch in dispatches:
        if dispatch.variant_revision_id is not None:
            direct_dispatches.setdefault(dispatch.variant_revision_id, dispatch)

    publish_jobs = list(
        await session.scalars(
            select(PublishJob)
            .where(PublishJob.platform_variant_revision_id.in_(revision_ids))
            .order_by(PublishJob.created_at.desc())
        )
    )
    latest_jobs: dict[UUID, PublishJob] = {}
    for publish_job in publish_jobs:
        latest_jobs.setdefault(publish_job.platform_variant_revision_id, publish_job)

    latest_job_ids = [publish_job.id for publish_job in latest_jobs.values()]
    publications = (
        list(await session.scalars(select(Publication).where(Publication.publish_job_id.in_(latest_job_ids))))
        if latest_job_ids
        else []
    )
    publication_by_job = {publication.publish_job_id: publication for publication in publications}

    def inherited_dispatch(revision: PlatformVariantRevision) -> AutomationDispatch | None:
        current: PlatformVariantRevision | None = revision
        seen: set[UUID] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            if dispatch := direct_dispatches.get(current.id):
                return dispatch
            current = revision_by_id.get(current.parent_revision_id) if current.parent_revision_id is not None else None
        return None

    outcomes: list[TelegramPublicationContextOut] = []
    for revision in revisions:
        latest_job = latest_jobs.get(revision.id)
        publication = publication_by_job.get(latest_job.id) if latest_job is not None else None
        outcomes.append(_publication_context(revision, inherited_dispatch(revision), latest_job, publication))
    return outcomes


@router.get(
    "/revisions/{revision_id}/publication-context",
    response_model=TelegramPublicationContextOut,
)
async def get_telegram_publication_context(
    revision_id: UUID,
    session: AsyncSession = SessionDependency,
) -> TelegramPublicationContextOut:
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .join(PlatformVariant, PlatformVariant.id == PlatformVariantRevision.platform_variant_id)
        .where(
            PlatformVariantRevision.id == revision_id,
            PlatformVariant.platform == "telegram",
        )
    )
    if revision is None:
        raise HTTPException(404, "Telegram revision not found")
    return await _publication_context_out(session, revision)


@draft_router.post(
    "/{revision_id}/publish",
    response_model=TelegramPublishAcceptedOut,
    status_code=202,
)
async def publish_telegram_draft(
    revision_id: UUID,
    body: TelegramContentHashIn,
    session: InjectedSession,
    capability_status: CapabilityStatusDependency,
):
    try:
        async with session.begin():
            result = await publish_reviewed_draft(
                session,
                revision_id=revision_id,
                content_hash=body.content_hash,
                capability_status=capability_status,
            )
            workflow_job = await session.get(WorkflowJob, result.publish_job.workflow_job_id)
            if workflow_job is not None:
                await bind_automation_publish_job(
                    session,
                    revision_id=result.revision.id,
                    workflow_job=workflow_job,
                    publish_job_id=result.publish_job.id,
                )
    except ReviewedTelegramDraftError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return TelegramPublishAcceptedOut(
        revision_id=result.revision.id,
        job=TelegramPublishIntentOut(
            publish_job_id=result.publish_job.id,
            workflow_job_id=result.publish_job.workflow_job_id,
            status=result.publish_job.status,
        ),
    )


@draft_router.post(
    "/{revision_id}/schedule",
    response_model=JobAcceptedOut,
    status_code=202,
)
async def schedule_telegram_revision(
    revision_id: UUID,
    body: ScheduleTelegramIn,
    session: InjectedSession,
    capability_status: CapabilityStatusDependency,
) -> JobAcceptedOut:
    try:
        async with session.begin():
            await capability_status.require_available(
                "destination",
                body.destination_id,
                "publishing",
                job_type="telegram.publish",
            )
            result = await schedule_reviewed_telegram(
                session,
                revision_id=revision_id,
                request=body,
            )
    except ReviewedTelegramScheduleError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return JobAcceptedOut.model_validate(
        {
            "job_id": result.workflow_job.id,
            "status": result.workflow_job.status,
            "deduplicated": not result.created,
        }
    )


@router.get("/publish-jobs/{publish_job_id}")
async def get_telegram_publish_job(
    publish_job_id: UUID,
    session: AsyncSession = SessionDependency,
):
    publish_job = await session.get(PublishJob, publish_job_id)
    if publish_job is None:
        raise HTTPException(404, "Telegram publish job not found")
    destination = await session.get(Destination, publish_job.destination_id)
    if destination is None or destination.platform != "telegram":
        raise HTTPException(404, "Telegram publish job not found")
    receipts = list(
        await session.scalars(
            select(PublishOperationReceipt)
            .where(PublishOperationReceipt.publish_job_id == publish_job.id)
            .order_by(PublishOperationReceipt.operation_index)
        )
    )
    publication = await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job.id))
    return _publish_job_out(publish_job, receipts, publication)


@router.get("/reconciliation", response_model=list[ReconciliationCase])
async def list_telegram_reconciliation_cases(
    session: AsyncSession = SessionDependency,
) -> list[ReconciliationCase]:
    return await list_reconciliation_cases(session)


@router.get("/reconciliation/{publish_job_id}", response_model=ReconciliationCase)
async def get_telegram_reconciliation_case(
    publish_job_id: UUID,
    session: AsyncSession = SessionDependency,
) -> ReconciliationCase:
    case = await get_reconciliation_case(session, publish_job_id)
    if case is None:
        raise HTTPException(404, "Telegram reconciliation case not found")
    return case


@router.post("/publish-jobs/{publish_job_id}/reconcile")
async def reconcile_telegram_publish_job(
    publish_job_id: UUID,
    body: TelegramReconcileIn,
    response: Response,
    session: InjectedSession,
    capability_status: CapabilityStatusDependency,
):
    return await _reconcile_telegram_publish_job(
        publish_job_id,
        body,
        response,
        session,
        capability_status,
    )


router.include_router(draft_router)
