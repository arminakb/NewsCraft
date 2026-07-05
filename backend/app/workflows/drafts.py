from __future__ import annotations

from uuid import UUID

from app.db.models import ContentDraft


class DraftService:
    def __init__(self, session):
        self.session = session

    async def create(
        self,
        content_item_id: UUID,
        platform: str,
        draft_text: str,
        human_notes: str | None = None,
        draft_metadata: dict | None = None,
    ) -> ContentDraft:
        draft = ContentDraft(
            content_item_id=content_item_id,
            platform=platform,
            draft_text=draft_text,
            status="draft",
            human_notes=human_notes,
            draft_metadata=draft_metadata or {},
        )
        self.session.add(draft)
        await self.session.flush()
        return draft
