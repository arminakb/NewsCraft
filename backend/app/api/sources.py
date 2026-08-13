import logging
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import SessionDependency
from app.api.schemas import (
    SourceCreateIn,
    SourceDetailOut,
    SourceHealthOut,
    SourceOut,
    telegram_username_from_url,
)
from app.automations.definitions.resources import count_automation_definitions_referencing
from app.automations.models import AutomationRoute
from app.core.config import settings
from app.db.models import Source
from app.ingestion.seed_sources import seed_sources
from app.jobs.errors import JobCapabilityUnavailable
from app.jobs.types import JobOrigin
from app.source_collections.models import SourceCollectionMembership
from app.source_collections.repository import list_sources as list_source_page
from app.source_collections.schemas import SourcePageOut
from app.sources.health import SourceHealthCheck, check_source_health
from app.sources.icon_discovery import ICON_PLATFORMS, enqueue_source_icon_discovery

logger = logging.getLogger(__name__)

router = APIRouter()


async def _schedule_source_icon_discovery(session: AsyncSession, source_id: UUID) -> None:
    """Claim the first icon-discovery attempt for a freshly created source.

    This is the seam the create path calls, and the seam tests substitute when
    they drive the router with a session double that has no durable job store —
    previously that was expressed as ``hasattr(session, "scalar")`` plus a
    catch-all for the doubles' ``AttributeError``/``TypeError``, which also
    swallowed genuine enqueue faults.

    The source row is already committed by the time we get here, and a failed
    claim rolls back to ``icon_status='pending'`` — exactly the state
    ``app.jobs.scheduler`` sweeps and re-queues — so dropping the attempt is
    recoverable. It is not, however, invisible: the warning names the source so
    a systematically rejected queue is diagnosable instead of showing up as
    icons that merely take a while.
    """

    try:
        await enqueue_source_icon_discovery(session, source_id, origin=JobOrigin.MANUAL)
        await session.commit()
    except JobCapabilityUnavailable as exc:
        logger.warning(
            "source icon discovery enqueue rejected; scheduler backfill remains the repair path",
            extra={"source_id": str(source_id), "error_code": exc.code},
        )
        await session.rollback()


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(session: AsyncSession = SessionDependency):
    rows = await session.scalars(
        select(Source)
        .where(Source.deleted_at.is_(None))
        .order_by(Source.source_group, Source.name)
    )
    return list(rows)


@router.get("/sources/search", response_model=SourcePageOut)
async def search_sources(
    search: str | None = Query(default=None, max_length=200),
    platform: str | None = Query(default=None, max_length=64),
    source_group: str | None = Query(default=None, max_length=100),
    collection_id: UUID | None = Query(default=None),  # noqa: B008
    unassigned: bool = Query(default=False),
    exclude_collection_id: UUID | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDependency,
) -> SourcePageOut:
    if collection_id is not None and unassigned:
        raise HTTPException(status_code=422, detail="collection_id and unassigned cannot be combined")
    page = await list_source_page(
        session,
        collection_id=collection_id,
        unassigned=unassigned,
        search=search,
        platform=platform,
        source_group=source_group,
        exclude_collection_id=exclude_collection_id,
        limit=limit,
        offset=offset,
    )
    return SourcePageOut(
        items=[SourceOut.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )


@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(payload: SourceCreateIn, session: AsyncSession = SessionDependency):
    source = Source(
        id=uuid4(),
        platform=payload.platform,
        name=payload.name,
        feed_url=payload.url if payload.platform in {"rss", "atom"} else None,
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
        icon_status="pending",
    )
    session.add(source)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="source already exists") from None
    if source.platform in ICON_PLATFORMS:
        await _schedule_source_icon_discovery(session, source.id)
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


@router.get("/sources/{source_id}/icon", response_class=FileResponse, include_in_schema=False)
async def get_source_icon(source_id: UUID, session: AsyncSession = SessionDependency) -> FileResponse:
    source = await session.get(Source, source_id)
    if source is None or source.deleted_at is not None or not source.icon_storage_path:
        raise HTTPException(status_code=404, detail="source icon not found")
    root = Path(settings.media_root).resolve()
    candidate = Path(source.icon_storage_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="source icon not found") from None
    if not resolved.is_relative_to(root) or not stat.S_ISREG(resolved.stat().st_mode):
        raise HTTPException(status_code=404, detail="source icon not found")
    return FileResponse(
        resolved,
        media_type=source.icon_mime_type or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"},
    )


@router.post("/sources/{source_id}/icon-failure", status_code=204, include_in_schema=False)
async def report_source_icon_failure(source_id: UUID, session: AsyncSession = SessionDependency) -> None:
    source = await session.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(status_code=404, detail="source not found")
    source.icon_status = "retryable"
    source.icon_next_retry_at = datetime.now(UTC)
    source.icon_last_error = "client_image_load_failed"
    source.icon_enqueued_at = None
    await session.commit()


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
    # No exception is absorbed here: this count is the referential-integrity
    # guard below, so a failing count must surface as a 500 rather than silently
    # authorize the delete.
    definition_dependencies = await count_automation_definitions_referencing(session, source_id)
    if legacy_dependencies or definition_dependencies:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "source_has_automation_dependencies",
                "automations": legacy_dependencies + definition_dependencies,
            },
        )
    await session.execute(
        delete(SourceCollectionMembership).where(SourceCollectionMembership.source_id == source_id)
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
