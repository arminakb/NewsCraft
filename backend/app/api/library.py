from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.redaction import redact_secrets
from app.db.models import ContentItem, Source
from app.db.session import get_session
from app.generation.models import AIProviderProfile
from app.research.models import ResearchAttempt, ResearchRun, ResearchSource
from app.stories.models import StoryEvidenceSnapshot

router = APIRouter(tags=["library"])
SessionDependency = Depends(get_session)

_EXCERPT_LIMIT = 500
_ERROR_SUMMARY_LIMIT = 500


class LibraryOriginalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str | None
    status: str
    source_id: UUID | None
    source_name: str | None
    source_url: str | None
    published_at: datetime | None
    sort_at: datetime


class LibraryOriginalListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LibraryOriginalOut]
    next_cursor: str | None


class LibraryEvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    story_id: UUID
    content_item_id: UUID | None
    evidence_key: str
    title: str | None
    source_url: str | None
    authors: list[str]
    published_at: datetime | None
    captured_at: datetime
    content_sha256: str
    excerpt: str


class LibraryEvidenceListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LibraryEvidenceOut]
    next_cursor: str | None


class LibraryResearchBudgetOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_queries: int = Field(ge=0)
    max_pages: int = Field(ge=0)
    max_elapsed_seconds: int = Field(ge=0)


class LibraryResearchRunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    story_id: UUID
    requested_mode: str
    backend: str | None
    status: str
    budget: LibraryResearchBudgetOut
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    result_story_revision_id: UUID | None
    error_summary: str | None


class LibraryResearchRunListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LibraryResearchRunOut]
    next_cursor: str | None


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def encode_library_cursor(timestamp: datetime, row_id: UUID) -> str:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("library cursor timestamp must be timezone-aware")
    payload = {"id": str(row_id), "timestamp": timestamp.isoformat()}
    return base64.urlsafe_b64encode(_canonical_json(payload)).rstrip(b"=").decode("ascii")


def decode_library_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"id", "timestamp"}:
            raise ValueError
        timestamp = datetime.fromisoformat(payload["timestamp"])
        row_id = UUID(payload["id"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError
    except (binascii.Error, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise ValueError("invalid library cursor") from None
    return timestamp, row_id


def _bounded_text(value: object, *, limit: int) -> str:
    normalized = " ".join(str(value).split())
    return normalized[:limit].strip()


def original_out(row: Any) -> LibraryOriginalOut:
    return LibraryOriginalOut(
        id=row.id,
        title=row.title,
        status=row.status,
        source_id=row.source_id,
        source_name=row.source_name,
        source_url=row.source_url,
        published_at=row.published_at,
        sort_at=row.sort_at,
    )


def evidence_out(row: Any) -> LibraryEvidenceOut:
    return LibraryEvidenceOut(
        id=row.id,
        story_id=row.story_id,
        content_item_id=row.content_item_id,
        evidence_key=row.evidence_key,
        title=row.title,
        source_url=row.source_url,
        authors=list(row.authors or []),
        published_at=row.published_at,
        captured_at=row.captured_at,
        content_sha256=row.content_sha256,
        excerpt=_bounded_text(row.content_text, limit=_EXCERPT_LIMIT),
    )


def _safe_error_summary(value: object | None) -> str | None:
    if value is None:
        return None
    redacted = redact_secrets(str(value))
    summary = _bounded_text(redacted, limit=_ERROR_SUMMARY_LIMIT)
    return summary or None


def research_run_out(row: Any) -> LibraryResearchRunOut:
    return LibraryResearchRunOut(
        id=row.id,
        story_id=row.story_id,
        requested_mode=row.requested_mode,
        backend=row.backend,
        status=row.status,
        budget=LibraryResearchBudgetOut(
            max_queries=row.query_budget,
            max_pages=row.page_budget,
            max_elapsed_seconds=row.time_budget_seconds,
        ),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        attempt_count=row.attempt_count,
        source_count=row.source_count,
        result_story_revision_id=row.result_story_revision_id,
        error_summary=_safe_error_summary(row.error_summary),
    )


def original_statement(
    *,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
) -> Select:
    statement = select(
        ContentItem.id,
        ContentItem.title,
        ContentItem.status,
        ContentItem.primary_source_id.label("source_id"),
        Source.name.label("source_name"),
        ContentItem.canonical_url.label("source_url"),
        ContentItem.published_at,
        ContentItem.sort_at,
    ).outerjoin(Source, Source.id == ContentItem.primary_source_id)
    if cursor is not None:
        sort_at, content_item_id = cursor
        statement = statement.where(
            or_(
                ContentItem.sort_at < sort_at,
                (ContentItem.sort_at == sort_at) & (ContentItem.id < content_item_id),
            )
        )
    return statement.order_by(ContentItem.sort_at.desc(), ContentItem.id.desc()).limit(limit + 1)


def evidence_statement(
    *,
    cursor: tuple[datetime, UUID] | None,
    story_id: UUID | None,
    source_id: UUID | None,
    limit: int,
) -> Select:
    statement = select(
        StoryEvidenceSnapshot.id,
        StoryEvidenceSnapshot.story_id,
        StoryEvidenceSnapshot.content_item_id,
        StoryEvidenceSnapshot.evidence_key,
        StoryEvidenceSnapshot.title,
        StoryEvidenceSnapshot.source_url,
        StoryEvidenceSnapshot.authors,
        StoryEvidenceSnapshot.published_at,
        StoryEvidenceSnapshot.captured_at,
        StoryEvidenceSnapshot.content_sha256,
        StoryEvidenceSnapshot.content_text,
    )
    if source_id is not None:
        statement = statement.join(
            ContentItem,
            ContentItem.id == StoryEvidenceSnapshot.content_item_id,
        ).where(ContentItem.primary_source_id == source_id)
    if story_id is not None:
        statement = statement.where(StoryEvidenceSnapshot.story_id == story_id)
    if cursor is not None:
        captured_at, snapshot_id = cursor
        statement = statement.where(
            or_(
                StoryEvidenceSnapshot.captured_at < captured_at,
                (StoryEvidenceSnapshot.captured_at == captured_at)
                & (StoryEvidenceSnapshot.id < snapshot_id),
            )
        )
    return statement.order_by(
        StoryEvidenceSnapshot.captured_at.desc(),
        StoryEvidenceSnapshot.id.desc(),
    ).limit(limit + 1)


def research_run_statement(
    *,
    cursor: tuple[datetime, UUID] | None,
    story_id: UUID | None,
    status: str | None,
    backend: str | None,
    limit: int,
    run_id: UUID | None = None,
) -> Select:
    attempt_count = (
        select(func.count(ResearchAttempt.id))
        .where(ResearchAttempt.research_run_id == ResearchRun.id)
        .correlate(ResearchRun)
        .scalar_subquery()
    )
    source_count = (
        select(func.count(ResearchSource.id))
        .where(ResearchSource.research_run_id == ResearchRun.id)
        .correlate(ResearchRun)
        .scalar_subquery()
    )
    latest_error = (
        select(
            func.coalesce(
                ResearchAttempt.error_message,
                ResearchAttempt.error_code,
                ResearchAttempt.error_class,
            )
        )
        .where(
            ResearchAttempt.research_run_id == ResearchRun.id,
            or_(
                ResearchAttempt.error_message.is_not(None),
                ResearchAttempt.error_code.is_not(None),
                ResearchAttempt.error_class.is_not(None),
            ),
        )
        .order_by(ResearchAttempt.attempt_number.desc(), ResearchAttempt.id.desc())
        .limit(1)
        .correlate(ResearchRun)
        .scalar_subquery()
    )
    statement = select(
        ResearchRun.id,
        ResearchRun.story_id,
        ResearchRun.requested_mode,
        AIProviderProfile.provider_type.label("backend"),
        ResearchRun.status,
        ResearchRun.query_budget,
        ResearchRun.page_budget,
        ResearchRun.time_budget_seconds,
        ResearchRun.created_at,
        ResearchRun.started_at,
        ResearchRun.finished_at,
        attempt_count.label("attempt_count"),
        source_count.label("source_count"),
        ResearchRun.result_story_revision_id,
        latest_error.label("error_summary"),
    ).outerjoin(
        AIProviderProfile,
        AIProviderProfile.id == ResearchRun.provider_profile_id,
    )
    if run_id is not None:
        statement = statement.where(ResearchRun.id == run_id)
    if story_id is not None:
        statement = statement.where(ResearchRun.story_id == story_id)
    if status is not None:
        statement = statement.where(ResearchRun.status == status)
    if backend is not None:
        statement = statement.where(AIProviderProfile.provider_type == backend)
    if cursor is not None:
        created_at, run_id = cursor
        statement = statement.where(
            or_(
                ResearchRun.created_at < created_at,
                (ResearchRun.created_at == created_at) & (ResearchRun.id < run_id),
            )
        )
    return statement.order_by(ResearchRun.created_at.desc(), ResearchRun.id.desc()).limit(limit + 1)


def _decode_route_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if cursor is None:
        return None
    try:
        return decode_library_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/library/originals", response_model=LibraryOriginalListOut)
async def list_library_originals(
    cursor: str | None = Query(default=None, min_length=1, max_length=1000),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = SessionDependency,
) -> LibraryOriginalListOut:
    rows = (
        await session.execute(
            original_statement(cursor=_decode_route_cursor(cursor), limit=limit)
        )
    ).all()
    page = rows[:limit]
    next_cursor = (
        encode_library_cursor(page[-1].sort_at, page[-1].id)
        if len(rows) > limit and page
        else None
    )
    return LibraryOriginalListOut(
        items=[original_out(row) for row in page],
        next_cursor=next_cursor,
    )


@router.get("/library/evidence", response_model=LibraryEvidenceListOut)
async def list_library_evidence(
    cursor: str | None = Query(default=None, min_length=1, max_length=1000),
    story_id: UUID | None = None,
    source_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = SessionDependency,
) -> LibraryEvidenceListOut:
    rows = (
        await session.execute(
            evidence_statement(
                cursor=_decode_route_cursor(cursor),
                story_id=story_id,
                source_id=source_id,
                limit=limit,
            )
        )
    ).all()
    page = rows[:limit]
    next_cursor = (
        encode_library_cursor(page[-1].captured_at, page[-1].id)
        if len(rows) > limit and page
        else None
    )
    return LibraryEvidenceListOut(
        items=[evidence_out(row) for row in page],
        next_cursor=next_cursor,
    )


@router.get("/library/research-runs", response_model=LibraryResearchRunListOut)
async def list_library_research_runs(
    cursor: str | None = Query(default=None, min_length=1, max_length=1000),
    story_id: UUID | None = None,
    status: str | None = Query(default=None, min_length=1, max_length=64),
    backend: str | None = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = SessionDependency,
) -> LibraryResearchRunListOut:
    rows = (
        await session.execute(
            research_run_statement(
                cursor=_decode_route_cursor(cursor),
                story_id=story_id,
                status=status,
                backend=backend,
                limit=limit,
            )
        )
    ).all()
    page = rows[:limit]
    next_cursor = (
        encode_library_cursor(page[-1].created_at, page[-1].id)
        if len(rows) > limit and page
        else None
    )
    return LibraryResearchRunListOut(
        items=[research_run_out(row) for row in page],
        next_cursor=next_cursor,
    )


@router.get("/library/research-runs/{run_id}", response_model=LibraryResearchRunOut)
async def get_library_research_run(
    run_id: UUID,
    session: AsyncSession = SessionDependency,
) -> LibraryResearchRunOut:
    rows = (
        await session.execute(
            research_run_statement(
                cursor=None,
                story_id=None,
                status=None,
                backend=None,
                limit=1,
                run_id=run_id,
            )
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Library research run not found")
    return research_run_out(rows[0])
