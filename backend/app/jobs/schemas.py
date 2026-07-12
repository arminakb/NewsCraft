from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.jobs.types import JobErrorClass, JobOrigin, JobStatus


class JobAcceptedOut(BaseModel):
    job_id: UUID
    status: JobStatus
    deduplicated: bool


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    status: JobStatus
    origin: JobOrigin
    priority: int
    pause_sensitive: bool
    scheduled_for: datetime
    attempt_count: int
    max_attempts: int
    progress: int
    progress_message: str | None
    error_class: JobErrorClass | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobEventOut(BaseModel):
    id: UUID
    event_type: str
    actor: str
    event_data: dict[str, Any]
    created_at: datetime


class JobDetailOut(JobOut):
    payload: dict[str, Any]
    result: dict[str, Any]
    events: list[JobEventOut]


class JobListOut(BaseModel):
    items: list[JobOut]


class JobSummaryOut(BaseModel):
    queued: int
    running: int
    attention: int
    succeeded_today: int
