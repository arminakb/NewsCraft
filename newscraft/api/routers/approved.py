from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from newscraft.api.deps import get_db
from newscraft.domain.schemas import ApprovedArticleRead
from newscraft.repositories.approved_article_repository import ApprovedArticleRepository

router = APIRouter(prefix="/approved-articles", tags=["approved"])


@router.get("", response_model=list[ApprovedArticleRead])
def list_approved(db: Session = Depends(get_db), limit: int = 100, category: str | None = None, source_type: str | None = None):
    return ApprovedArticleRepository(db).list(limit=limit, category=category, source_type=source_type)
