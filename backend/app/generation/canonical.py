from __future__ import annotations

from collections.abc import Mapping
from typing import Any
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


async def generate_canonical_revision(
    value: CanonicalStoryOutput | Any,
    provider_or_snapshots: Any,
    *,
    snapshots: Mapping[UUID, EvidenceRecord] | None = None,
) -> CanonicalStoryOutput:
    """Validate a provider canonical result against its immutable evidence snapshot.

    Accepting an already parsed output keeps the integrity boundary independently
    testable; handlers pass provider output through the same path.
    """
    if isinstance(value, CanonicalStoryOutput):
        output = value
        evidence = provider_or_snapshots if snapshots is None else snapshots
    else:
        result = await provider_or_snapshots.generate(value)
        output = CanonicalStoryOutput.model_validate(result.output)
        evidence = snapshots or {}
    return validate_canonical_output(output, evidence)
