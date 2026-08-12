from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas import SourceOut
from app.source_collections.repository import normalize_description, normalize_source_collection_name


class SourceCollectionCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return normalize_source_collection_name(value)[0]

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return normalize_description(value)


class SourceCollectionUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return normalize_source_collection_name(value)[0] if value is not None else None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return normalize_description(value)

    @model_validator(mode="after")
    def require_update_field(self) -> SourceCollectionUpdateIn:
        if self.name is None and "description" not in self.model_fields_set:
            raise ValueError("source collection update requires name or description")
        return self


class SourceCollectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str | None = None
    source_count: int = Field(ge=0, le=100)
    maximum_sources: int = 100
    created_at: datetime
    updated_at: datetime
    active_ingest_run_id: UUID | None = None
    active_ingest_status: str | None = None
    active_ingest_source_count: int | None = None
    active_ingest_processed_count: int | None = None
    active_ingest_success_count: int | None = None
    active_ingest_failure_count: int | None = None
    continuous_subscription_id: UUID | None = None
    continuous_mode: Literal["continuous"] | None = None
    continuous_status: str | None = None
    continuous_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    continuous_started_at: datetime | None = None
    continuous_stopped_at: datetime | None = None
    continuous_last_cycle_at: datetime | None = None
    continuous_next_cycle_at: datetime | None = None
    continuous_last_success_at: datetime | None = None
    continuous_cycle_count: int | None = Field(default=None, ge=0)
    continuous_last_cycle_status: str | None = None
    continuous_last_error: str | None = None
    continuous_current_cycle_job_id: UUID | None = None
    continuous_current_cycle_run_id: UUID | None = None


class SourcePageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SourceOut]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    has_more: bool


class SourceCollectionMembershipBulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ids: list[UUID] = Field(min_length=1, max_length=100)


class SourceCollectionIngestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["once", "continuous"] = "once"
    request_id: UUID | None = None


class SourceCollectionContinuousStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID | None = None


class SourceCollectionSubscriptionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_collection_id: UUID | None = None
    source_collection_name: str | None = None
    mode: Literal["continuous"]
    status: str
    created_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_cycle_at: datetime | None = None
    next_cycle_at: datetime | None = None
    last_success_at: datetime | None = None
    cycle_count: int = Field(ge=0)
    interval_minutes: int = Field(ge=1, le=1440)
    created_by: str
    last_cycle_status: str | None = None
    last_error: str | None = None
    current_cycle_job_id: UUID | None = None
    current_cycle_run_id: UUID | None = None


class SourceCollectionMembershipChangeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: UUID
    added_source_ids: list[UUID] = Field(default_factory=list)
    removed_source_ids: list[UUID] = Field(default_factory=list)
    already_member_source_ids: list[UUID] = Field(default_factory=list)
    missing_source_ids: list[UUID] = Field(default_factory=list)
    source_count: int = Field(ge=0, le=100)
    maximum_sources: int = 100


class CollectionIngestAcceptedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID | None = None
    run_id: UUID | None = None
    source_collection_id: UUID
    source_collection_name: str
    source_count: int = Field(ge=0, le=100)
    status: str
    deduplicated: bool
    mode: Literal["once", "continuous"] = "once"
    subscription_id: UUID | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    next_cycle_at: datetime | None = None


class IngestRunSnapshotSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID | None = None
    position: int
    source_name: str
    platform: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class SourceCollectionRunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_collection_id: UUID | None = None
    source_collection_name_at_start: str | None = None
    source_count: int = Field(ge=0, le=100)
    processed_count: int = Field(ge=0, le=100)
    success_count: int = Field(ge=0, le=100)
    failure_count: int = Field(ge=0, le=100)
    skipped_count: int = Field(default=0, ge=0, le=100)
    started_at: datetime
    completed_at: datetime | None = None
    status: str
    trigger: str
    mode: Literal["once", "continuous"] = "once"
    continuous_subscription_id: UUID | None = None
    continuous_cycle_number: int | None = Field(default=None, ge=1)
    stats: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    sources: list[IngestRunSnapshotSourceOut] = Field(default_factory=list)

    @field_validator(
        "source_count",
        "processed_count",
        "success_count",
        "failure_count",
        "skipped_count",
        mode="before",
    )
    @classmethod
    def default_progress_counts(cls, value: object) -> int:
        return 0 if value is None else int(value)


class SourceCollectionRunPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SourceCollectionRunOut]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    has_more: bool
