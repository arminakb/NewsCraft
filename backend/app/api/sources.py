from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SourceDetailOut, SourceOut
from app.db.models import Source
from app.db.session import get_session
from app.ingestion.seed_sources import seed_sources

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
