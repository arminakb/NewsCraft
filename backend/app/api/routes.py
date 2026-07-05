from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ContentItemOut, DiagnosticsOut, IngestRunOut, IngestRunRequest, SourceOut
from app.db.models import ContentItem, Source
from app.db.session import get_session
from app.diagnostics.service import DiagnosticsService
from app.ingestion.seed_sources import seed_sources
from app.ingestion.service import IngestionService

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
async def list_content_items(session: AsyncSession = SessionDependency):
    rows = await session.scalars(select(ContentItem).order_by(ContentItem.sort_at.desc()).limit(100))
    return list(rows)


@router.get("/diagnostics", response_model=DiagnosticsOut)
async def diagnostics(session: AsyncSession = SessionDependency):
    return await DiagnosticsService(session).check()
