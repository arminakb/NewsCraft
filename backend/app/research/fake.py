from __future__ import annotations

from pathlib import Path

from app.research.base import (
    ResearchBackendOutput,
    ResearchBudgetExceeded,
    ResearchRequest,
    ResearchResult,
    ResearchUsage,
)


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
        output = ResearchBackendOutput.model_validate(self._output.model_dump())
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


__all__ = ["FakeResearchBackend"]
