from sqlalchemy import select
from sqlalchemy.orm import Session

from newscraft.db.models import ContentDraft


class ContentDraftRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict):
        draft = ContentDraft(
            article_id=data["article_id"],
            platform=data["platform"],
            draft_text=data["draft_text"],
            status=data.get("status") or "draft",
            human_notes=data.get("human_notes"),
            draft_metadata=data.get("metadata") or {},
        )
        self.db.add(draft)
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def list(self, limit=100, platform=None, status=None):
        stmt = select(ContentDraft)
        if platform:
            stmt = stmt.where(ContentDraft.platform == platform)
        if status:
            stmt = stmt.where(ContentDraft.status == status)
        return list(self.db.scalars(stmt.order_by(ContentDraft.created_at.desc()).limit(limit)))

    def get(self, draft_id: int):
        return self.db.get(ContentDraft, draft_id)

    def update(self, draft_id: int, data: dict):
        draft = self.get(draft_id)
        if not draft:
            return None
        for key, value in data.items():
            if value is None:
                continue
            if key == "metadata":
                draft.draft_metadata = value
            else:
                setattr(draft, key, value)
        self.db.commit()
        self.db.refresh(draft)
        return draft
