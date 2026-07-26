from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.research.citations import validate_citations
from app.research.schemas import Claim
from app.stories.evidence import EvidenceRecord


class CanonicalStoryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1, max_length=300)
    narrative: str = Field(min_length=50)
    facts: list[Claim] = Field(min_length=1)
    disagreements: list[Claim]
    angles: list[str]
    missing_information: list[str]


def validate_canonical_output(
    output: CanonicalStoryOutput,
    snapshots: Mapping[UUID, EvidenceRecord],
) -> CanonicalStoryOutput:
    validate_citations([*output.facts, *output.disagreements], snapshots)
    return output
