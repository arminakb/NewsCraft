"""Research persistence and evidence integrity contracts."""

from app.research.citations import CitationIntegrityError, resolve_candidate_brief, validate_citations
from app.research.completeness import CompletenessEvidence, evaluate_completeness
from app.research.schemas import (
    CandidateCitation,
    CandidateClaim,
    CandidateResearchBrief,
    CitationRef,
    Claim,
    CompletenessReport,
    DiscoveredSourcePayload,
    ResearchBrief,
    ResearchBudget,
)

__all__ = [
    "CandidateCitation",
    "CandidateClaim",
    "CandidateResearchBrief",
    "CitationIntegrityError",
    "CitationRef",
    "Claim",
    "CompletenessEvidence",
    "CompletenessReport",
    "DiscoveredSourcePayload",
    "ResearchBrief",
    "ResearchBudget",
    "evaluate_completeness",
    "resolve_candidate_brief",
    "validate_citations",
]
