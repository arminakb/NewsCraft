from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import SessionDependency
from app.feed.service import clear_active_feed, count_active_feed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feed", tags=["feed"])


class FeedSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_count: int


class FeedClearOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cleared_count: int


@router.get("/summary", response_model=FeedSummaryOut)
async def get_feed_summary(
    session: AsyncSession = SessionDependency,
) -> FeedSummaryOut:
    return FeedSummaryOut(article_count=await count_active_feed(session))


@router.post("/clear", response_model=FeedClearOut)
async def clear_feed(
    session: AsyncSession = SessionDependency,
) -> FeedClearOut:
    try:
        result = await clear_active_feed(session)
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("Feed clear operation failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feed could not be cleared right now. Try again.",
        ) from None
    return FeedClearOut(cleared_count=result.cleared_count)
