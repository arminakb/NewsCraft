from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ApproveContentItemIn,
    ApproveContentItemOut,
    ContentItemOut,
    DiagnosticsOut,
    IngestRunOut,
    IngestRunRequest,
    SourceOut,
)
from app.db.models import ContentItem, Source
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


@router.post("/ingest/run", response_model=IngestRunOut)
async def run_ingest(request: IngestRunRequest, session: AsyncSession = SessionDependency):
    service = IngestionService(session)
    stats = await service.run_once(platforms=request.platforms, source_ids=request.source_ids, trigger="api")
    if "status" not in stats:
        stats["status"] = "partial" if stats.get("failed") else "succeeded"
    return stats


@router.get("/content-items", response_model=list[ContentItemOut])
async def list_content_items(
    status: str | None = None,
    sort: Literal["latest", "score"] = "latest",
    limit: int = Query(100, ge=1, le=250),
    session: AsyncSession = SessionDependency,
):
    stmt = select(ContentItem)
    if status:
        stmt = stmt.where(ContentItem.status == status)
    if sort == "score":
        stmt = stmt.order_by(ContentItem.score.desc(), ContentItem.sort_at.desc())
    else:
        stmt = stmt.order_by(ContentItem.sort_at.desc())
    rows = await session.scalars(stmt.limit(limit))
    return list(rows)


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
