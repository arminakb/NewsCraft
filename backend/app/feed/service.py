from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, text
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

    The CTE returns only the aggregate count to the application. Canonical content,
    source rows, source identities, and downstream references remain untouched.
    """
    count = await session.scalar(
        text(
            """
            WITH cleared AS (
                UPDATE content_items
                SET feed_cleared_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE feed_cleared_at IS NULL
                RETURNING id
            )
            SELECT count(*) AS cleared_count
            FROM cleared
            """
        )
    )
    return FeedClearResult(cleared_count=int(count or 0))
