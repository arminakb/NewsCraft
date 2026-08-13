from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.generation_helpers import _evidence_record
from app.jobs.errors import NeedsReviewJobError
from app.jobs.registry import JobContext
from app.research.citations import validate_citations
from app.research.schemas import CitationRef, Claim
from app.stories.evidence import EvidenceRecord
from app.stories.models import StoryEvidenceSnapshot, StoryRevision

LockedEvidenceStage = Literal[
    "citations_invalid",
    "citations_missing",
    "evidence_missing",
    "citation_integrity",
]

_LOCKED_CLAIM_TEXT = "Locked canonical story"


class LockedStoryEvidenceError(ValueError):
    """The locked citations of a story revision do not resolve to intact evidence.

    ``stage`` names which step failed so each caller can translate the one failure
    into its own error taxonomy (job needs-review vs API request rejection).
    """

    def __init__(self, stage: LockedEvidenceStage) -> None:
        super().__init__(stage)
        self.stage: LockedEvidenceStage = stage


async def load_locked_story_evidence(
    session: AsyncSession,
    story_revision: StoryRevision,
) -> tuple[list[CitationRef], dict[UUID, EvidenceRecord]]:
    """Resolve a story revision's locked citations into verified evidence records.

    This is the single implementation of the locked-evidence integrity contract:
    citations parse, they are present, every referenced snapshot still belongs to
    the story, and the citations still validate against those snapshots.
    """

    try:
        citations = [CitationRef.model_validate(item) for item in story_revision.citations]
    except TypeError, ValueError:
        raise LockedStoryEvidenceError("citations_invalid") from None
    if not citations:
        raise LockedStoryEvidenceError("citations_missing")
    snapshot_ids = {item.evidence_snapshot_id for item in citations}
    snapshots = list(
        await session.scalars(
            select(StoryEvidenceSnapshot).where(
                StoryEvidenceSnapshot.id.in_(snapshot_ids),
                StoryEvidenceSnapshot.story_id == story_revision.story_id,
            )
        )
    )
    records = {row.id: _evidence_record(row) for row in snapshots}
    if set(records) != snapshot_ids:
        raise LockedStoryEvidenceError("evidence_missing")
    try:
        validate_citations([Claim(text=_LOCKED_CLAIM_TEXT, citations=citations)], records)
    except ValueError:
        raise LockedStoryEvidenceError("citation_integrity") from None
    return citations, records


_NEEDS_REVIEW_FAILURES: dict[LockedEvidenceStage, tuple[str, str]] = {
    "citations_invalid": ("generation_citations_invalid", "Canonical story citations are invalid"),
    "citations_missing": ("generation_citations_missing", "Canonical story citations are missing"),
    "evidence_missing": ("citation_integrity", "Canonical story evidence is missing"),
    "citation_integrity": ("citation_integrity", "Canonical story citations failed integrity validation"),
}


async def locked_story_evidence(
    context: JobContext,
    story_revision: StoryRevision,
) -> tuple[list[CitationRef], dict[UUID, EvidenceRecord]]:
    try:
        return await load_locked_story_evidence(context.session, story_revision)
    except LockedStoryEvidenceError as error:
        code, message = _NEEDS_REVIEW_FAILURES[error.stage]
        raise NeedsReviewJobError(code=code, message=message) from None
