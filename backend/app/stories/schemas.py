from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class GroupPendingPayload(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    cursor: UUID | None = None
    root_ingest_job_id: UUID | None = None


class GroupPendingResult(BaseModel):
    selected_count: int
    grouped_story_count: int
    evidence_snapshot_count: int
    next_cursor: UUID | None
