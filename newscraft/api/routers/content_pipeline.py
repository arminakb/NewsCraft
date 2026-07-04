from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from newscraft.api.deps import get_db
from newscraft.domain.schemas import ContentDraftCreate, ContentDraftRead, ContentDraftUpdate
from newscraft.services.content_pipeline_service import ContentPipelineService

router = APIRouter(prefix="/content-drafts", tags=["content-drafts"])


@router.get("", response_model=list[ContentDraftRead])
def list_content_drafts(db: Session = Depends(get_db), platform: str | None = None, status: str | None = None, limit: int = 100):
    return ContentPipelineService(db).list(platform=platform, status=status, limit=limit)


@router.post("", response_model=ContentDraftRead)
def create_content_draft(payload: ContentDraftCreate, db: Session = Depends(get_db)):
    return ContentPipelineService(db).create(payload)


@router.patch("/{draft_id}", response_model=ContentDraftRead)
def update_content_draft(draft_id: int, payload: ContentDraftUpdate, db: Session = Depends(get_db)):
    draft = ContentPipelineService(db).update(draft_id, payload)
    if not draft:
        raise HTTPException(status_code=404, detail="content draft not found")
    return draft
