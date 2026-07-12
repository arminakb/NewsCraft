from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import ApproveContentItemIn, ApproveContentItemOut, ContentItemOut
from app.db.models import ContentItem
from app.db.session import get_session
from app.workflows.approval import ApprovalService

router = APIRouter()
SessionDependency = Depends(get_session)


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
