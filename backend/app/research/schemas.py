from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.stories.evidence import build_evidence_key

CompletenessReason = Literal[
    "fewer_than_two_independent_sources",
    "insufficient_body_text",
    "missing_primary_evidence",
    "unresolved_contradictions",
]


class CompletenessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complete: bool
    score: int = Field(ge=0, le=100)
    reasons: list[CompletenessReason]
    independent_source_count: int = Field(ge=0)
    body_character_count: int = Field(ge=0)
    has_primary_evidence: bool


class ResearchBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_model_calls: int = Field(default=6, ge=1, le=12)
    max_input_tokens: int = Field(default=60_000, ge=1_000, le=500_000)
    max_output_tokens: int = Field(default=12_000, ge=500, le=100_000)
    max_cost_usd: Decimal = Field(default=Decimal("2.00"), ge=Decimal("0"), le=Decimal("50"))
    max_queries: int = Field(default=4, ge=1, le=8)
    max_results_per_query: int = Field(default=5, ge=1, le=10)
    max_pages: int = Field(default=8, ge=1, le=16)
    max_elapsed_seconds: int = Field(default=120, ge=10, le=600)
    max_total_chars: int = Field(default=120_000, ge=10_000, le=500_000)


class DiscoveredSourcePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str = Field(pattern=r"^url:https?://.+:[0-9a-f]{64}$", max_length=2_300)
    url: HttpUrl
    title: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=300)
    published_at: datetime | None = None
    retrieved_at: datetime
    content_text: str = Field(min_length=1, max_length=500_000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_status: Literal["ok", "fallback"]

    @model_validator(mode="after")
    def evidence_key_matches_materialized_content(self) -> DiscoveredSourcePayload:
        if hashlib.sha256(self.content_text.encode("utf-8")).hexdigest() != self.content_sha256:
            raise ValueError("content_sha256 does not match materialized content")
        expected = build_evidence_key(
            content_item_id=None,
            source_url=str(self.url),
            content_sha256=self.content_sha256,
        )
        if self.evidence_key != expected:
            raise ValueError("evidence_key does not match normalized URL and content hash")
        return self


class CandidateCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str = Field(min_length=1, max_length=2_300)
    locator: str = Field(min_length=1, max_length=240)
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    citations: list[CandidateCitation] = Field(min_length=1)


class CandidateResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    verified_facts: list[CandidateClaim]
    disagreements: list[CandidateClaim]
    missing_information: list[str]
    suggested_angles: list[str]
    discovered_evidence_keys: list[str]


class CitationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str
    evidence_snapshot_id: UUID
    source_url: HttpUrl | None
    locator: str = Field(min_length=1, max_length=240)
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    citations: list[CitationRef] = Field(min_length=1)


class ResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    verified_facts: list[Claim]
    disagreements: list[Claim]
    missing_information: list[str]
    suggested_angles: list[str]
    discovered_source_ids: list[UUID]
