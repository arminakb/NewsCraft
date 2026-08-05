from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    SourceCreateIn,
    SourceDetailOut,
    SourceHealthOut,
    SourceOut,
    telegram_username_from_url,
)
from app.automations.definitions.resources import count_automation_definitions_referencing
from app.automations.models import AutomationRoute
from app.db.models import Source
from app.db.session import get_session
from app.ingestion.seed_sources import seed_sources
from app.sources.health import SourceHealthCheck, check_source_health

router = APIRouter()
SessionDependency = Depends(get_session)


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(session: AsyncSession = SessionDependency):
    rows = await session.scalars(
        select(Source)
        .where(Source.deleted_at.is_(None))
        .order_by(Source.source_group, Source.name)
    )
    return list(rows)


@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(payload: SourceCreateIn, session: AsyncSession = SessionDependency):
    source = Source(
        id=uuid4(),
        platform=payload.platform,
        name=payload.name,
        feed_url=payload.url if payload.platform == "rss" else None,
        homepage_url=None,
        telegram_username=telegram_username_from_url(payload.url) if payload.platform == "telegram_public" else None,
        source_group=payload.source_group,
        language_hint=payload.language_hint.lower(),
        default_timezone="UTC",
        normalization_profile={},
        fetch_interval_minutes=payload.fetch_interval_minutes,
        active=True,
        failure_count=0,
        health_status="unknown",
    )
    session.add(source)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="source already exists") from None
    return source


@router.post("/sources/seed")
async def seed(session: AsyncSession = SessionDependency):
    count = await seed_sources(session)
    await session.commit()
    return {"upserted": count}


@router.get("/sources/{source_id}", response_model=SourceDetailOut)
async def get_source(source_id: UUID, session: AsyncSession = SessionDependency):
    source = await session.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(status_code=404, detail="source not found")
    return source


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: UUID, session: AsyncSession = SessionDependency) -> None:
    source = await session.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(status_code=404, detail="source not found")
    legacy_dependencies = int(
        await session.scalar(
            select(func.count()).select_from(AutomationRoute).where(AutomationRoute.source_id == source_id)
        )
        or 0
    )
    definition_dependencies = await count_automation_definitions_referencing(session, source_id)
    if legacy_dependencies or definition_dependencies:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "source_has_automation_dependencies",
                "automations": legacy_dependencies + definition_dependencies,
            },
        )
    source.active = False
    source.disabled_reason = "deleted_by_operator"
    source.deleted_at = datetime.now(UTC)
    await session.commit()


@router.post("/sources/{source_id}/health-check", response_model=SourceHealthOut)
async def run_source_health_check(
    source_id: UUID,
    session: AsyncSession = SessionDependency,
) -> SourceHealthOut:
    source = await session.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(status_code=404, detail="source not found")
    if not source.active:
        raise HTTPException(status_code=409, detail="disabled sources cannot be checked")

    result = await check_source_health(source)
    _persist_health_result(source, result)
    await session.commit()
    return SourceHealthOut(
        source_id=source.id,
        health_status=source.health_status,
        last_checked_at=result.checked_at,
        failure_reason=result.failure_reason,
    )


def _persist_health_result(source: Source, result: SourceHealthCheck) -> None:
    source.health_status = result.status
    source.last_fetch_at = result.checked_at
    source.last_http_status = result.http_status
    if result.status == "healthy":
        source.last_success_at = result.checked_at
        source.failure_count = 0
        source.last_error_type = None
        source.last_error_message = None
        return
    source.last_failure_at = result.checked_at
    source.failure_count = int(source.failure_count or 0) + 1
    source.last_error_type = "health_check_failed"
    source.last_error_message = result.failure_reason
