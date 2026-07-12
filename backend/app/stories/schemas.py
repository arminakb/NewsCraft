from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ManualUrlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["url"]
    url: HttpUrl
    title: str | None = Field(default=None, max_length=300)


class ManualTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["text"]
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=20, max_length=200_000)
    source_label: str = Field(min_length=1, max_length=160)
    source_url: HttpUrl | None = None


ManualIntakeRequest = Annotated[
    ManualUrlInput | ManualTextInput,
    Field(discriminator="kind"),
]


class GroupPendingPayload(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    cursor: UUID | None = None
    root_ingest_job_id: UUID | None = None


class GroupPendingResult(BaseModel):
    selected_count: int
    grouped_story_count: int
    evidence_snapshot_count: int
    next_cursor: UUID | None
