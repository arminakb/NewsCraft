from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.db.models import ContentItem


class ApprovalService:
    def __init__(self, session):
        self.session = session

    async def approve(self, content_item_id: UUID, notes: str | None = None) -> ContentItem:
        item = await self.session.get(ContentItem, content_item_id)
        if item is None:
            raise LookupError("content item not found")

        metrics = dict(item.metrics or {})
        metrics["approval"] = {
            "approved_at": datetime.now(UTC).isoformat(),
            "notes": notes,
        }
        item.metrics = metrics
        item.status = "approved"
        await self.session.flush()
        return item
