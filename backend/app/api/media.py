from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import MediaAssetListOut
from app.db.models import MediaAsset
from app.db.session import get_session

router = APIRouter()
SessionDependency = Depends(get_session)


@router.get("/media-assets", response_model=list[MediaAssetListOut])
async def list_media_assets(
    limit: int = Query(100, ge=1, le=250),
    session: AsyncSession = SessionDependency,
):
    rows = await session.scalars(
        select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(limit)
    )
    return list(rows)
