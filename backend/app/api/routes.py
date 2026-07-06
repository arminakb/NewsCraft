from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    ApproveContentItemIn,
    ApproveContentItemOut,
    ContentItemOut,
    DashboardSummaryOut,
    DiagnosticsOut,
    IngestRunOut,
    IngestRunRequest,
    IngestRunSummaryOut,
    MediaAssetListOut,
    SourceDetailOut,
    SourceOut,
)
from app.db.models import ContentItem, IngestRun, MediaAsset, Source
from app.db.session import get_session
from app.diagnostics.service import DiagnosticsService
from app.ingestion.seed_sources import seed_sources
from app.ingestion.service import IngestionService
from app.workflows.approval import ApprovalService

router = APIRouter()
SessionDependency = Depends(get_session)


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(session: AsyncSession = SessionDependency):
    rows = await session.scalars(select(Source).order_by(Source.source_group, Source.name))
    return list(rows)


@router.post("/sources/seed")
async def seed(session: AsyncSession = SessionDependency):
    count = await seed_sources(session)
    await session.commit()
    return {"upserted": count}


@router.get("/sources/{source_id}", response_model=SourceDetailOut)
async def get_source(source_id: UUID, session: AsyncSession = SessionDependency):
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return source


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
async def dashboard_summary(session: AsyncSession = SessionDependency):
    rss_feeds = await _count(session, Source, Source.platform == "rss")
    telegram_channels = await _count(session, Source, Source.platform == "telegram_public")
    content_items = await _count(session, ContentItem)
    media_assets = await _count(session, MediaAsset)
    warnings = await _count(
        session,
        Source,
        or_(Source.health_status != "healthy", Source.failure_count > 0, Source.active.is_(False)),
    )
    return DashboardSummaryOut(
        rss_feeds=rss_feeds,
        telegram_channels=telegram_channels,
        content_items=content_items,
        media_assets=media_assets,
        warnings=warnings,
    )


@router.get("/ingest/runs", response_model=list[IngestRunSummaryOut])
async def list_ingest_runs(limit: int = Query(100, ge=1, le=250), session: AsyncSession = SessionDependency):
    rows = await session.scalars(select(IngestRun).order_by(IngestRun.started_at.desc()).limit(limit))
    return list(rows)


@router.post("/ingest/run", response_model=IngestRunOut)
async def run_ingest(request: IngestRunRequest, session: AsyncSession = SessionDependency):
    service = IngestionService(session)
    stats = await service.run_once(platforms=request.platforms, source_ids=request.source_ids, trigger="api")
    await session.commit()
    if "status" not in stats:
        stats["status"] = "partial" if stats.get("failed") else "succeeded"
    return stats


@router.get("/media-assets", response_model=list[MediaAssetListOut])
async def list_media_assets(limit: int = Query(100, ge=1, le=250), session: AsyncSession = SessionDependency):
    rows = await session.scalars(select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(limit))
    return list(rows)


@router.get("/content-items", response_model=list[ContentItemOut])
async def list_content_items(
    status: str | None = None,
    content_type: str | None = None,
    rewrite_bucket: str | None = None,
    is_rewrite_ready: bool | None = None,
    source_tier: str | None = None,
    quality_status: str | None = None,
    sort: Literal["latest", "score"] = "latest",
    limit: int = Query(100, ge=1, le=250),
    session: AsyncSession = SessionDependency,
):
    stmt = select(ContentItem).options(selectinload(ContentItem.primary_media))
    if status:
        stmt = stmt.where(ContentItem.status == status)
    if content_type:
        stmt = stmt.where(ContentItem.content_type == content_type)
    if rewrite_bucket:
        stmt = stmt.where(ContentItem.rewrite_bucket == rewrite_bucket)
    if is_rewrite_ready is not None:
        stmt = stmt.where(ContentItem.is_rewrite_ready.is_(is_rewrite_ready))
    if source_tier:
        stmt = stmt.where(ContentItem.source_tier == source_tier)
    if quality_status:
        stmt = stmt.where(ContentItem.quality_status == quality_status)
    if sort == "score":
        stmt = stmt.order_by(ContentItem.score.desc(), ContentItem.sort_at.desc())
    else:
        stmt = stmt.order_by(ContentItem.sort_at.desc())
    rows = await session.scalars(stmt.limit(limit))
    return list(rows)


@router.get("/content-items/{content_item_id}", response_model=ContentItemOut)
async def get_content_item(content_item_id: UUID, session: AsyncSession = SessionDependency):
    item = await session.scalar(
        select(ContentItem)
        .options(selectinload(ContentItem.primary_media))
        .where(ContentItem.id == content_item_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="content item not found")
    return item


@router.post("/content-items/{content_item_id}/approve", response_model=ApproveContentItemOut)
async def approve_content_item(
    content_item_id: UUID,
    payload: ApproveContentItemIn,
    session: AsyncSession = SessionDependency,
):
    try:
        item = await ApprovalService(session).approve(content_item_id, notes=payload.notes)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return item


@router.get("/diagnostics", response_model=DiagnosticsOut)
async def diagnostics(session: AsyncSession = SessionDependency):
    return await DiagnosticsService(session).check()


async def _count(session: AsyncSession, model, *criteria) -> int:
    stmt = select(func.count()).select_from(model)
    for condition in criteria:
        stmt = stmt.where(condition)
    return int(await session.scalar(stmt) or 0)
