from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContentItem


@dataclass(frozen=True, slots=True)
class FeedClearResult:
    cleared_count: int


def active_feed_condition():
    """Return the canonical predicate for articles currently visible in Feed."""
    return ContentItem.feed_cleared_at.is_(None)


async def count_active_feed(session: AsyncSession) -> int:
    count = await session.scalar(select(func.count()).select_from(ContentItem).where(active_feed_condition()))
    return int(count or 0)


async def clear_active_feed(session: AsyncSession) -> FeedClearResult:
    """Hide every active Feed item in one database statement.

    Canonical content, source rows, source identities, and downstream references
    remain untouched.
    """
    result = await session.execute(
        update(ContentItem)
        .where(active_feed_condition())
        .values(
            feed_cleared_at=func.current_timestamp(),
            updated_at=func.current_timestamp(),
        )
    )
    return FeedClearResult(cleared_count=int(getattr(result, "rowcount", 0) or 0))
