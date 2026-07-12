from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DashboardSummaryOut, DiagnosticsOut
from app.db.models import ContentItem, MediaAsset, Source
from app.db.session import get_session
from app.diagnostics.service import DiagnosticsService

router = APIRouter()
SessionDependency = Depends(get_session)


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


@router.get("/diagnostics", response_model=DiagnosticsOut)
async def diagnostics(session: AsyncSession = SessionDependency):
    return await DiagnosticsService(session).check()


async def _count(session: AsyncSession, model, *criteria) -> int:
    stmt = select(func.count()).select_from(model)
    for condition in criteria:
        stmt = stmt.where(condition)
    return int(await session.scalar(stmt) or 0)
