from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.operations.diagnostics import OperationsDiagnostics
from app.operations.history import (
    HistoryCategory,
    HistoryService,
    HistorySubjectType,
    decode_history_cursor,
)


class ComponentHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy", "degraded", "down", "unknown"]
    observed_at: datetime | None
    last_success_at: datetime | None
    message: str
    action_url: str | None


class AttentionItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Literal["warning", "error"]
    kind: Literal[
        "job",
        "route",
        "research",
        "generation",
        "publication",
        "destination",
        "source",
    ]
    title: str
    occurred_at: datetime
    action_url: str


class OperationsSnapshotOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    global_paused: bool
    dry_run: bool
    components: dict[str, ComponentHealthOut]
    queue_counts: dict[str, int]
    attention: list[AttentionItemOut]


class HistoryEntryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    occurred_at: datetime
    category: HistoryCategory
    status: str
    title: str
    summary: str
    job_id: UUID | None
    subject_url: str
    sanitized_metadata: dict[str, object]


class HistoryPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[HistoryEntryOut]
    next_cursor: str | None


router = APIRouter(prefix="/operations", tags=["operations"])
SessionDependency = Depends(get_session)


@router.get("/diagnostics", response_model=OperationsSnapshotOut)
async def operations_diagnostics(
    session: AsyncSession = SessionDependency,
) -> OperationsSnapshotOut:
    snapshot = await OperationsDiagnostics(session).snapshot()
    return OperationsSnapshotOut.model_validate(snapshot.model_dump())


@router.get("/history", response_model=HistoryPageOut)
async def operations_history(
    subject_type: HistorySubjectType | None = None,
    subject_id: UUID | None = None,
    category: HistoryCategory | None = None,
    status: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
    cursor: str | None = Query(default=None, min_length=1, max_length=1000),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = SessionDependency,
) -> HistoryPageOut:
    if (subject_type is None) != (subject_id is None):
        raise HTTPException(
            status_code=422,
            detail="subject_type and subject_id must be supplied together",
        )
    _validate_history_cursor(cursor)
    page = await HistoryService(session).list(
        subject_type=subject_type,
        subject_id=subject_id,
        category=category,
        status=status,
        cursor=cursor,
        limit=limit,
    )
    return HistoryPageOut.model_validate(page.model_dump())


def _validate_history_cursor(cursor: str | None) -> None:
    if cursor is None:
        return
    try:
        decode_history_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
