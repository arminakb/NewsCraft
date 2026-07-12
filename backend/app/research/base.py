from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.research.schemas import CandidateResearchBrief, DiscoveredSourcePayload, ResearchBudget
from app.stories.evidence import EvidenceRecord


class ResearchBudgetExceeded(RuntimeError):
    """A fixed-message failure raised before an over-budget result escapes."""


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    story_id: UUID
    provider_profile_id: UUID
    requested_model: str
    mode: Literal["manual", "auto_if_incomplete"]
    depth: Literal["standard", "deep"] = "standard"
    query_hint: str | None = Field(default=None, max_length=500)
    evidence: list[EvidenceRecord] = Field(min_length=1)
    budget: ResearchBudget


class ResearchBackendOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[DiscoveredSourcePayload]
    brief: CandidateResearchBrief


class ResearchUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal = Field(ge=Decimal("0"))
    queries: int = Field(ge=0)
    pages: int = Field(ge=0)
    fetched_characters: int = Field(ge=0)


class ResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_profile_id: UUID
    provider_type: Literal["fake", "codex", "openrouter"]
    requested_model: str
    resolved_model: str
    output: ResearchBackendOutput
    usage: ResearchUsage
    elapsed_ms: int = Field(ge=0)
    sanitized_events: list[dict[str, object]]


class ResearchBackend(Protocol):
    name: str

    async def research(self, request: ResearchRequest) -> ResearchResult: ...


__all__ = [
    "ResearchBackend",
    "ResearchBackendOutput",
    "ResearchBudgetExceeded",
    "ResearchRequest",
    "ResearchResult",
    "ResearchUsage",
]
