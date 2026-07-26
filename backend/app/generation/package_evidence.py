from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.generation.generation_helpers import _evidence_record
from app.jobs.errors import NeedsReviewJobError
from app.jobs.registry import JobContext
from app.research.citations import CitationIntegrityError, validate_citations
from app.research.schemas import CitationRef, Claim
from app.stories.evidence import EvidenceRecord
from app.stories.models import StoryEvidenceSnapshot, StoryRevision


async def locked_story_evidence(
    context: JobContext,
    story_revision: StoryRevision,
) -> tuple[list[CitationRef], dict[UUID, EvidenceRecord]]:
    try:
        citations = [CitationRef.model_validate(item) for item in story_revision.citations]
    except TypeError, ValueError:
        raise NeedsReviewJobError(
            code="generation_citations_invalid",
            message="Canonical story citations are invalid",
        ) from None
    if not citations:
        raise NeedsReviewJobError(
            code="generation_citations_missing",
            message="Canonical story citations are missing",
        )
    snapshot_ids = {item.evidence_snapshot_id for item in citations}
    snapshots = list(
        await context.session.scalars(
            select(StoryEvidenceSnapshot).where(
                StoryEvidenceSnapshot.id.in_(snapshot_ids),
                StoryEvidenceSnapshot.story_id == story_revision.story_id,
            )
        )
    )
    records = {row.id: _evidence_record(row) for row in snapshots}
    if set(records) != snapshot_ids:
        raise NeedsReviewJobError(
            code="citation_integrity",
            message="Canonical story evidence is missing",
        )
    try:
        validate_citations([Claim(text="Locked canonical story", citations=citations)], records)
    except CitationIntegrityError:
        raise NeedsReviewJobError(
            code="citation_integrity",
            message="Canonical story citations failed integrity validation",
        ) from None
    return citations, records
