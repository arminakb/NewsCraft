from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.editorial_errors import editorial_http_error
from app.db.models import ContentItem
from app.db.session import get_session
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.research.completeness import CompletenessEvidence, evaluate_completeness
from app.research.service import (
    ResearchDisposition,
    ResearchRequestError,
    ResearchService,
    evidence_set_hash,
)
from app.stories.models import Story, StoryEvidenceSnapshot
from app.stories.schemas import ManualIntakeRequest
from app.stories.states import (
    TELEGRAM_PROVISIONAL,
    EditableStoryStatus,
    EditorialStoryStatus,
    decide_story_transition,
)

router = APIRouter()
SessionDependency = Depends(get_session)


class ResearchRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["manual", "auto_if_incomplete"]
    depth: Literal["standard", "deep"] = "standard"
    provider_profile_id: UUID
    query_hint: str | None = Field(default=None, max_length=500)


class StoryEditorialStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: EditableStoryStatus


class StoryBulkEditorialStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    story_ids: list[UUID] = Field(min_length=1, max_length=200)
    state: EditableStoryStatus


class GroupPendingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=100, ge=1, le=500)


def _cursor_encode(story: Story) -> str:
    raw = f"{story.updated_at.isoformat()}|{story.id}".encode()
    return urlsafe_b64encode(raw).decode().rstrip("=")


def _cursor_decode(value: str) -> tuple[datetime, UUID]:
    try:
        raw = urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        timestamp, story_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), UUID(story_id)
    except UnicodeError, ValueError:
        raise HTTPException(422, "Invalid story cursor") from None


async def _story_summaries(session: AsyncSession, stories: list[Story]) -> dict[UUID, dict]:
    if not stories:
        return {}
    rows = (
        await session.execute(
            select(
                StoryEvidenceSnapshot.id,
                StoryEvidenceSnapshot.story_id,
                StoryEvidenceSnapshot.evidence_key,
                StoryEvidenceSnapshot.content_sha256,
                StoryEvidenceSnapshot.content_text,
                StoryEvidenceSnapshot.source_url,
                StoryEvidenceSnapshot.snapshot_metadata,
                StoryEvidenceSnapshot.captured_at,
            )
            .where(StoryEvidenceSnapshot.story_id.in_([story.id for story in stories]))
            .order_by(
                StoryEvidenceSnapshot.story_id,
                StoryEvidenceSnapshot.captured_at,
                StoryEvidenceSnapshot.id,
            )
        )
    ).all()
    grouped: dict[UUID, list] = {story.id: [] for story in stories}
    for row in rows:
        grouped[row.story_id].append(row)
    summaries: dict[UUID, dict] = {}
    for story in stories:
        snapshots = grouped[story.id]
        completeness = evaluate_completeness(
            [
                CompletenessEvidence(
                    evidence_key=item.evidence_key,
                    content_text=item.content_text,
                    source_url=item.source_url,
                    source_identity=(item.snapshot_metadata or {}).get("source_label"),
                    is_primary=bool((item.snapshot_metadata or {}).get("is_primary")),
                )
                for item in snapshots
            ]
        )
        summaries[story.id] = {
            "id": story.id,
            "title": story.title,
            "status": story.status,
            "primary_language": story.primary_language,
            "superseded_by_id": story.superseded_by_id,
            "evidence_count": len(snapshots),
            "latest_evidence_at": snapshots[-1].captured_at if snapshots else None,
            "completeness": completeness.model_dump(mode="json"),
            "evidence_set_hash": evidence_set_hash(snapshots),
            "created_at": story.created_at,
            "updated_at": story.updated_at,
        }
    return summaries


async def _story_summary(session: AsyncSession, story: Story) -> dict:
    return (await _story_summaries(session, [story]))[story.id]


@router.get("/stories")
async def list_stories(
    search: str | None = Query(default=None, max_length=200),
    editorial_state: EditorialStoryStatus | None = None,
    completeness: Literal["complete", "incomplete"] | None = None,
    include_superseded: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    session: AsyncSession = SessionDependency,
):
    base_statement = select(Story)
    if not include_superseded:
        base_statement = base_statement.where(Story.superseded_by_id.is_(None))
    if search:
        base_statement = base_statement.where(Story.title.ilike(f"%{search.strip()}%"))
    if editorial_state:
        base_statement = base_statement.where(Story.status == editorial_state)
    scan_after = _cursor_decode(cursor) if cursor else None
    matches: list[tuple[Story, dict]] = []
    batch_size = min(200, max(25, limit + 1))
    while len(matches) < limit + 1:
        statement = base_statement
        if scan_after is not None:
            updated_at, story_id = scan_after
            statement = statement.where(
                or_(
                    Story.updated_at < updated_at,
                    (Story.updated_at == updated_at) & (Story.id < story_id),
                )
            )
        rows = list(
            await session.scalars(statement.order_by(Story.updated_at.desc(), Story.id.desc()).limit(batch_size))
        )
        if not rows:
            break
        summaries = await _story_summaries(session, rows)
        for item in rows:
            summary = summaries[item.id]
            if completeness is None or (summary["completeness"]["complete"] is (completeness == "complete")):
                matches.append((item, summary))
                if len(matches) == limit + 1:
                    break
        if len(rows) < batch_size or len(matches) >= limit + 1:
            break
        last = rows[-1]
        scan_after = (last.updated_at, last.id)
    page = matches[:limit]
    return {
        "items": [summary for _story, summary in page],
        "next_cursor": _cursor_encode(page[-1][0]) if len(matches) > limit else None,
    }


@router.post("/stories/group-pending", response_model=JobAcceptedOut, status_code=202)
async def group_pending(
    payload: GroupPendingInput,
    session: AsyncSession = SessionDependency,
) -> JobAcceptedOut:
    has_snapshot = exists(select(1).where(StoryEvidenceSnapshot.content_item_id == ContentItem.id))
    has_active_provisional = exists(
        select(1)
        .select_from(StoryEvidenceSnapshot)
        .join(Story, Story.id == StoryEvidenceSnapshot.story_id)
        .where(
            StoryEvidenceSnapshot.content_item_id == ContentItem.id,
            Story.status == TELEGRAM_PROVISIONAL,
            Story.superseded_by_id.is_(None),
        )
    )
    candidate_ids = list(
        await session.scalars(
            select(ContentItem.id)
            .where(or_(~has_snapshot, has_active_provisional))
            .order_by(ContentItem.id)
            .limit(payload.limit)
        )
    )
    candidate_hash = hashlib.sha256(
        json.dumps([str(value) for value in candidate_ids], separators=(",", ":")).encode()
    ).hexdigest()
    result = await JobRepository(session).enqueue_job(
        job_type="story.group_pending",
        payload={"limit": payload.limit, "cursor": None, "root_ingest_job_id": None},
        idempotency_key=f"story-group-pending:{candidate_hash}:{payload.limit}",
        origin=JobOrigin.MANUAL,
    )
    await session.commit()
    return JobAcceptedOut(job_id=result.job.id, status=result.job.status, deduplicated=not result.created)


async def _change_states(
    session: AsyncSession,
    story_ids: list[UUID],
    state: EditableStoryStatus,
) -> list[dict]:
    if len(set(story_ids)) != len(story_ids):
        raise HTTPException(409, "Story IDs must be unique")
    rows = list(
        await session.scalars(select(Story).where(Story.id.in_(story_ids)).order_by(Story.id).with_for_update())
    )
    if len(rows) != len(story_ids) or any(item.superseded_by_id is not None for item in rows):
        raise HTTPException(409, "Every story must exist and be active")
    decisions = [decide_story_transition(story.status, state) for story in rows]
    if any(not decision.allowed for decision in decisions):
        raise HTTPException(409, "The requested story transition is not allowed")
    for story, decision in zip(rows, decisions, strict=True):
        if not decision.changed:
            continue
        old = story.status
        story.status = state
        session.add(
            WorkflowEvent(
                workflow_job_id=None,
                event_type="story.editorial_state_changed",
                actor="manual",
                event_data=redact_event_data({"story_id": str(story.id), "old_state": old, "new_state": state}),
            )
        )
    await session.flush()
    return [await _story_summary(session, item) for item in rows]


@router.patch("/stories/{story_id}/editorial-state")
async def change_editorial_state(
    story_id: UUID,
    payload: StoryEditorialStateInput,
    session: AsyncSession = SessionDependency,
):
    values = await _change_states(session, [story_id], payload.state)
    await session.commit()
    return values[0]


@router.post("/stories/bulk-editorial-state")
async def bulk_change_editorial_state(
    payload: StoryBulkEditorialStateInput,
    session: AsyncSession = SessionDependency,
):
    values = await _change_states(session, payload.story_ids, payload.state)
    await session.commit()
    by_id = {str(value["id"]): value for value in values}
    return {"items": [by_id[str(story_id)] for story_id in payload.story_ids]}


@router.post(
    "/stories/{story_id}/research-runs",
    response_model=ResearchDisposition,
    status_code=202,
)
async def create_research_run(
    story_id: UUID,
    payload: ResearchRunCreate,
    session: AsyncSession = SessionDependency,
):
    try:
        result = await ResearchService(session).request(
            story_id=story_id,
            mode=payload.mode,
            depth=payload.depth,
            provider_profile_id=payload.provider_profile_id,
            query_hint=payload.query_hint,
        )
    except ResearchRequestError as exc:
        raise editorial_http_error(exc) from None
    await session.commit()
    return result


@router.get("/stories/{story_id}/research-runs")
async def list_research_runs(story_id: UUID, session: AsyncSession = SessionDependency):
    return {"items": await ResearchService(session).list_runs(story_id)}


@router.get("/research-runs/{run_id}")
async def get_research_run(run_id: UUID, session: AsyncSession = SessionDependency):
    try:
        return await ResearchService(session).get_run(run_id)
    except ResearchRequestError:
        raise HTTPException(404, "Research run was not found") from None


@router.post("/stories/manual", response_model=JobAcceptedOut, status_code=202)
async def create_manual_intake(
    payload: ManualIntakeRequest,
    session: AsyncSession = SessionDependency,
) -> JobAcceptedOut:
    job_payload = payload.model_dump(mode="json")
    payload_hash = hashlib.sha256(json.dumps(job_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = await JobRepository(session).enqueue_job(
        job_type="manual_intake",
        payload=job_payload,
        idempotency_key=f"manual_intake:{payload_hash}",
        origin=JobOrigin.MANUAL,
    )
    await session.commit()
    return JobAcceptedOut(
        job_id=result.job.id,
        status=result.job.status,
        deduplicated=not result.created,
    )
