from __future__ import annotations

import hashlib
from pathlib import Path

from app.research.base import (
    ResearchBackendOutput,
    ResearchBudgetExceeded,
    ResearchRequest,
    ResearchResult,
    ResearchUsage,
)
from app.research.schemas import CandidateCitation, CandidateClaim, CandidateResearchBrief


class FakeResearchBackend:
    name = "fake"

    def __init__(self, *, output: ResearchBackendOutput) -> None:
        self._output = ResearchBackendOutput.model_validate(output.model_dump())

    @classmethod
    def from_fixture(cls, path: str | Path) -> FakeResearchBackend:
        output = ResearchBackendOutput.model_validate_json(Path(path).read_text(encoding="utf-8"))
        cited_claims = [*output.brief.verified_facts, *output.brief.disagreements]
        if any(not claim.citations for claim in cited_claims):
            raise ValueError("fixture claims must have citations")
        return cls(output=output)

    async def research(self, request: ResearchRequest) -> ResearchResult:
        output = self._output_for(request)
        _validate_output(request, output)
        usage = self._build_usage(output)
        elapsed_ms = self._elapsed_ms()
        _validate_budget(request, usage, elapsed_ms)
        return ResearchResult(
            provider_profile_id=request.provider_profile_id,
            provider_type="fake",
            requested_model=request.requested_model,
            resolved_model=request.requested_model,
            output=output,
            usage=usage,
            elapsed_ms=elapsed_ms,
            sanitized_events=[
                {"event": "fixture_loaded", "source_count": len(output.sources)}
            ],
        )

    def _output_for(self, request: ResearchRequest) -> ResearchBackendOutput:
        del request
        return ResearchBackendOutput.model_validate(self._output.model_dump())

    def _build_usage(self, output: ResearchBackendOutput) -> ResearchUsage:
        return ResearchUsage(
            model_calls=1,
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=0,
            queries=0,
            pages=len(output.sources),
            fetched_characters=sum(len(source.content_text) for source in output.sources),
        )

    def _elapsed_ms(self) -> int:
        return 0


class EvidenceGroundedFakeResearchBackend(FakeResearchBackend):
    """Build deterministic, citation-valid research from the request evidence."""

    def __init__(self) -> None:
        super().__init__(
            output=ResearchBackendOutput(
                sources=[],
                brief=CandidateResearchBrief(
                    summary="Deterministic research is grounded in the supplied evidence.",
                    verified_facts=[],
                    disagreements=[],
                    missing_information=[],
                    suggested_angles=[],
                    discovered_evidence_keys=[],
                ),
            )
        )

    def _output_for(self, request: ResearchRequest) -> ResearchBackendOutput:
        evidence = next((item for item in request.evidence if item.content_text), None)
        if evidence is None:
            return ResearchBackendOutput(
                sources=[],
                brief=CandidateResearchBrief(
                    summary=(
                        "The deterministic research backend found no textual evidence "
                        "that could be cited."
                    ),
                    verified_facts=[],
                    disagreements=[],
                    missing_information=[
                        "The supplied evidence contains no textual content to cite."
                    ],
                    suggested_angles=[],
                    discovered_evidence_keys=[],
                ),
            )
        content = evidence.content_text
        return ResearchBackendOutput(
            sources=[],
            brief=CandidateResearchBrief(
                summary=(
                    "The deterministic research backend verified the supplied immutable "
                    "evidence without network access."
                ),
                verified_facts=[
                    CandidateClaim(
                        text=content,
                        citations=[
                            CandidateCitation(
                                evidence_key=evidence.evidence_key,
                                locator=f"chars:0-{len(content)}",
                                excerpt_sha256=hashlib.sha256(content.encode()).hexdigest(),
                            )
                        ],
                    )
                ],
                disagreements=[],
                missing_information=[],
                suggested_angles=["Explain the verified evidence and its operational context."],
                discovered_evidence_keys=[],
            ),
        )


def _validate_output(request: ResearchRequest, output: ResearchBackendOutput) -> None:
    source_keys = [source.evidence_key for source in output.sources]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("Research output contains duplicate source evidence keys")

    discovered_keys = output.brief.discovered_evidence_keys
    if len(discovered_keys) != len(set(discovered_keys)):
        raise ValueError("Research output contains duplicate discovered evidence keys")
    if set(discovered_keys) != set(source_keys):
        raise ValueError("Research output discovered evidence keys do not match returned sources")

    permitted_citation_keys = {
        *(record.evidence_key for record in request.evidence),
        *source_keys,
    }
    claims = [*output.brief.verified_facts, *output.brief.disagreements]
    if any(
        citation.evidence_key not in permitted_citation_keys
        for claim in claims
        for citation in claim.citations
    ):
        raise ValueError("Research output contains unknown citation evidence keys")


def _validate_budget(
    request: ResearchRequest,
    usage: ResearchUsage,
    elapsed_ms: int,
) -> None:
    budget = request.budget
    exceeded = (
        usage.model_calls > budget.max_model_calls
        or usage.input_tokens > budget.max_input_tokens
        or usage.output_tokens > budget.max_output_tokens
        or usage.estimated_cost_usd > budget.max_cost_usd
        or usage.queries > budget.max_queries
        or usage.pages > budget.max_pages
        or usage.fetched_characters > budget.max_total_chars
        or elapsed_ms > budget.max_elapsed_seconds * 1_000
    )
    if exceeded:
        raise ResearchBudgetExceeded("Research budget exceeded")


__all__ = ["EvidenceGroundedFakeResearchBackend", "FakeResearchBackend"]
