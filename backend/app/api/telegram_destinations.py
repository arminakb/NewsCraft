from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.capabilities import CapabilityStatusDependency
from app.api.telegram_schemas import (
    TelegramDestinationAcceptedOut,
    TelegramDestinationCreate,
    TelegramDestinationOut,
)
from app.db.session import get_session
from app.jobs.credential_capabilities import CapabilityStatusService
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.publishing.models import Destination

router = APIRouter(prefix="/telegram/destinations", tags=["telegram"])
SessionDependency = Depends(get_session)


def get_job_repository(session: AsyncSession = SessionDependency) -> JobRepository:
    return JobRepository(session)


JobRepositoryDependency = Annotated[JobRepository, Depends(get_job_repository)]


async def _destination_out(
    destination: Destination,
    capability_status: CapabilityStatusService,
) -> TelegramDestinationOut:
    state = await capability_status.get("destination", destination.id, "publishing")
    return TelegramDestinationOut(
        id=destination.id,
        name=destination.name,
        target_ref=destination.target_ref,
        enabled=destination.enabled,
        health_status=destination.health_status,
        configured=state.available,
        capability_state=state,
        settings=dict(destination.settings or {}),
    )


def _destination_matches(destination: Destination, body: TelegramDestinationCreate) -> bool:
    return (
        destination.name == body.name
        and destination.secret_ref == body.secret_ref
        and dict(destination.settings or {}) == {"allow_auto_publish": body.allow_auto_publish}
    )


@router.get("", response_model=list[TelegramDestinationOut])
async def list_telegram_destinations(
    session: AsyncSession = SessionDependency,
    capability_status: CapabilityStatusDependency = None,
):
    rows = list(
        await session.scalars(
            select(Destination).where(Destination.platform == "telegram").order_by(Destination.name)
        )
    )
    return [await _destination_out(row, capability_status) for row in rows]


@router.post("", response_model=TelegramDestinationAcceptedOut, status_code=202)
async def create_telegram_destination(
    body: TelegramDestinationCreate,
    session: AsyncSession = SessionDependency,
    jobs: JobRepositoryDependency = None,
    capability_status: CapabilityStatusDependency = None,
):
    destination = await session.scalar(
        select(Destination).where(
            Destination.platform == "telegram",
            Destination.target_ref == body.target_ref,
        )
    )
    if destination is None:
        now = datetime.now(UTC)
        destination = Destination(
            name=body.name,
            platform="telegram",
            target_ref=body.target_ref,
            secret_ref=body.secret_ref,
            enabled=True,
            health_status="unknown",
            settings={"allow_auto_publish": body.allow_auto_publish},
            updated_at=now,
        )
        try:
            async with session.begin_nested():
                session.add(destination)
                await session.flush()
        except IntegrityError:
            destination = await session.scalar(
                select(Destination).where(
                    Destination.platform == "telegram",
                    Destination.target_ref == body.target_ref,
                )
            )
            if destination is None:
                raise HTTPException(409, "Telegram destination create conflicted") from None
    if not _destination_matches(destination, body):
        raise HTTPException(409, "Telegram destination already exists with different configuration")
    result = await jobs.enqueue_job(
        job_type="telegram.destination.check",
        payload={"destination_id": str(destination.id)},
        idempotency_key=(
            f"telegram-destination-check:{destination.id}:{destination.updated_at.isoformat()}"
        ),
        origin=JobOrigin.AUTOMATION,
    )
    await session.commit()
    return TelegramDestinationAcceptedOut(
        destination=await _destination_out(destination, capability_status),
        job=JobAcceptedOut(
            job_id=result.job.id,
            status=result.job.status,
            deduplicated=not result.created,
        ),
    )
