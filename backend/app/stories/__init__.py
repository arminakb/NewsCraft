"""Editorial story grouping and immutable evidence contracts."""

from app.stories.evidence import (
    CapturedEvidence,
    EvidenceInput,
    EvidenceRecord,
    build_evidence_key,
    capture_evidence,
)
from app.stories.grouping import GroupingDecision, GroupingInput, decide_group
from app.stories.repository import EvidenceKeyCollision, StoryRepository

__all__ = [
    "CapturedEvidence",
    "EvidenceInput",
    "EvidenceKeyCollision",
    "EvidenceRecord",
    "GroupingDecision",
    "GroupingInput",
    "StoryRepository",
    "build_evidence_key",
    "capture_evidence",
    "decide_group",
]
