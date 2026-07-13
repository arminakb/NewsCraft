from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.generation.telegram_schema import TelegramEvidenceCitation, TelegramVariantContent


class RevisionValidationError(ValueError):
    pass


class RevisionGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: str = Field(min_length=1)
    ok: bool
    reason: str | None

    @model_validator(mode="before")
    @classmethod
    def normalize_historical_reason(cls, value: Any):
        if isinstance(value, dict) and "reason" not in value:
            value = {**value, "reason": None}
        return value


def validate_approvable_revision(revision: Any) -> None:
    try:
        TelegramVariantContent.model_validate(revision.content)
        citations = [TelegramEvidenceCitation.model_validate(item) for item in revision.evidence_map]
        gates = [RevisionGate.model_validate(item) for item in revision.validation_results]
    except AttributeError, TypeError, ValidationError:
        raise RevisionValidationError("Revision validation contract is invalid") from None
    if not citations:
        raise RevisionValidationError("Revision evidence map is empty")
    if not gates:
        raise RevisionValidationError("Revision validation results are empty")
    if any(not gate.ok for gate in gates):
        raise RevisionValidationError("Revision has a failed validation gate")
