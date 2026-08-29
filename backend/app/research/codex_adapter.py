from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.core.codex_exec import CodexExecutionError, CodexExecutor
from app.core.redaction import redact_secrets
from app.normalization.urls import normalize_url
from app.research.base import (
    ResearchBackendOutput,
    ResearchRequest,
    ResearchResult,
    ResearchUsage,
)
from app.research.deadline import elapsed_ms, with_deadline
from app.research.prompts import build_research_prompt, compose_system_policy
from app.research.safe_fetch import SafeArticleFetcher, SafeArticleFetchError
from app.research.schemas import (
    CandidateCitation,
    CandidateClaim,
    CandidateResearchBrief,
    DiscoveredSourcePayload,
)

_SAFE_EXECUTION_ERROR_CODE = re.compile(r"codex_[a-z0-9_]{1,100}\Z")
_SAFE_EXECUTION_CLASSIFICATIONS = {"retryable", "needs_review", "permanent"}


class ResearchBackendError(CodexExecutionError):
    """A classified, fixed-message Codex research failure."""


class CodexSourceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    title: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None


class CodexCandidateCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str | None = Field(default=None, min_length=1, max_length=2_300)
    source_url: HttpUrl | None = None
    quote: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def references_exactly_one_evidence_input(self) -> CodexCandidateCitation:
        if (self.evidence_key is None) == (self.source_url is None):
            raise ValueError("citation must reference one existing evidence key or one discovered source URL")
        return self


class CodexCandidateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    citations: list[CodexCandidateCitation] = Field(min_length=1)


class CodexCandidateBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    verified_facts: list[CodexCandidateClaim]
    disagreements: list[CodexCandidateClaim]
    missing_information: list[str]
    suggested_angles: list[str]


class CodexResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[CodexSourceCandidate]
    brief: CodexCandidateBrief


class CodexResearchBackend:
    name = "codex"

    def __init__(
        self,
        *,
        executor: CodexExecutor,
        fetcher: SafeArticleFetcher,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.executor = executor
        self.fetcher = fetcher
        self.monotonic = monotonic

    async def research(self, request: ResearchRequest) -> ResearchResult:
        started = self.monotonic()
        deadline = started + request.budget.max_elapsed_seconds
        # ponytail: codex protocol has no system role; layer the saved prompt above the task input
        prompt = build_research_prompt(request)
        if request.system_prompt:
            prompt = f"{compose_system_policy(request.system_prompt)}\n\n{prompt}"
        try:
            execution = await self._within_deadline(
                self.executor.run(
                    prompt,
                    CodexResearchOutput.model_json_schema(),
                    request.budget,
                    resolved_model=request.requested_model,
                    allow_web=True,
                ),
                deadline=deadline,
                started=started,
            )
        except ResearchBackendError as exc:
            exc.add_metadata(elapsed_ms=elapsed_ms(self.monotonic, started))
            raise
        except CodexExecutionError as exc:
            safe_metadata = redact_secrets(exc.metadata)
            safe_code = redact_secrets(exc.code)
            normalized_code = (
                safe_code
                if isinstance(safe_code, str) and _SAFE_EXECUTION_ERROR_CODE.fullmatch(safe_code)
                else "codex_execution_failed"
            )
            classification = (
                exc.classification
                if isinstance(exc.classification, str) and exc.classification in _SAFE_EXECUTION_CLASSIFICATIONS
                else "needs_review"
            )
            raise ResearchBackendError(
                "codex research execution failed",
                classification=classification,
                code=normalized_code,
                metadata={
                    **(safe_metadata if isinstance(safe_metadata, dict) else {}),
                    "elapsed_ms": elapsed_ms(self.monotonic, started),
                },
            ) from None
        try:
            safe_structured_output = redact_secrets(execution.structured_output)
            raw = CodexResearchOutput.model_validate(safe_structured_output)
            sources, source_keys = await self._materialize_sources(
                raw.sources,
                request,
                deadline=deadline,
                started=started,
            )
            evidence_text = {record.evidence_key: record.content_text for record in request.evidence}
            evidence_text.update({source.evidence_key: source.content_text for source in sources})
            claims = {
                "verified_facts": self._materialize_claims(
                    raw.brief.verified_facts,
                    source_keys=source_keys,
                    evidence_text=evidence_text,
                    deadline=deadline,
                    started=started,
                ),
                "disagreements": self._materialize_claims(
                    raw.brief.disagreements,
                    source_keys=source_keys,
                    evidence_text=evidence_text,
                    deadline=deadline,
                    started=started,
                ),
            }
        except ResearchBackendError as exc:
            exc.add_metadata(elapsed_ms=elapsed_ms(self.monotonic, started))
            raise
        except (SafeArticleFetchError, ValueError) as exc:
            raise ResearchBackendError(
                "codex research evidence could not be verified",
                classification="needs_review",
                code="codex_evidence_invalid",
                metadata={
                    "status": "evidence_invalid",
                    "elapsed_ms": elapsed_ms(self.monotonic, started),
                },
            ) from exc

        self._assert_within_deadline(deadline=deadline, started=started)
        output = ResearchBackendOutput(
            sources=sources,
            brief=CandidateResearchBrief(
                summary=raw.brief.summary,
                verified_facts=claims["verified_facts"],
                disagreements=claims["disagreements"],
                missing_information=raw.brief.missing_information,
                suggested_angles=raw.brief.suggested_angles,
                discovered_evidence_keys=[source.evidence_key for source in sources],
            ),
        )
        safe_resolved_model = redact_secrets(execution.resolved_model)
        safe_events = redact_secrets(execution.sanitized_events)
        provisional_result = ResearchResult(
            provider_profile_id=request.provider_profile_id,
            provider_type="codex",
            requested_model=request.requested_model,
            resolved_model=(safe_resolved_model if isinstance(safe_resolved_model, str) else "[REDACTED]"),
            output=output,
            usage=ResearchUsage(
                model_calls=1,
                input_tokens=execution.usage["input_tokens"],
                output_tokens=execution.usage["output_tokens"],
                estimated_cost_usd=Decimal("0"),
                queries=0,
                pages=len(sources),
                fetched_characters=sum(len(source.content_text) for source in sources),
            ),
            elapsed_ms=0,
            sanitized_events=safe_events if isinstance(safe_events, list) else [],
        )
        total_elapsed_ms = self._elapsed_within_deadline(deadline=deadline, started=started)
        return provisional_result.model_copy(
            update={
                "elapsed_ms": total_elapsed_ms,
                "sanitized_events": [
                    *provisional_result.sanitized_events,
                    {
                        "type": "codex_research_total",
                        "elapsed_ms": total_elapsed_ms,
                    },
                ],
            }
        )

    def _assert_within_deadline(self, *, deadline: float, started: float) -> None:
        if self.monotonic() >= deadline:
            raise self._elapsed_budget_error(started)

    def _elapsed_within_deadline(self, *, deadline: float, started: float) -> int:
        now = self.monotonic()
        if now >= deadline:
            raise ResearchBackendError(
                "codex research elapsed budget exceeded",
                classification="needs_review",
                code="codex_elapsed_budget_exceeded",
                metadata={
                    "status": "over_budget",
                    "elapsed_ms": max(0, round((now - started) * 1000)),
                },
            )
        return max(0, round((now - started) * 1000))

    async def _within_deadline(self, awaitable, *, deadline: float, started: float):
        return await with_deadline(
            awaitable,
            remaining_seconds=deadline - self.monotonic(),
            on_expired=lambda: self._elapsed_budget_error(started),
        )

    def _elapsed_budget_error(self, started: float) -> ResearchBackendError:
        return ResearchBackendError(
            "codex research elapsed budget exceeded",
            classification="needs_review",
            code="codex_elapsed_budget_exceeded",
            metadata={"status": "over_budget", "elapsed_ms": elapsed_ms(self.monotonic, started)},
        )

    async def _materialize_sources(
        self,
        candidates: list[CodexSourceCandidate],
        request: ResearchRequest,
        *,
        deadline: float,
        started: float,
    ) -> tuple[list[DiscoveredSourcePayload], dict[str, str]]:
        if len(candidates) > request.budget.max_pages:
            raise ResearchBackendError(
                "codex research page budget exceeded",
                classification="needs_review",
                code="codex_page_budget_exceeded",
            )
        sources: list[DiscoveredSourcePayload] = []
        source_keys: dict[str, str] = {}
        seen: set[str] = set()
        for candidate in candidates:
            candidate_url = normalize_url(str(candidate.url))
            if candidate_url in seen:
                raise ValueError("duplicate returned source URL")
            seen.add(candidate_url)
            fetched = await self._within_deadline(
                self.fetcher.fetch(str(candidate.url)),
                deadline=deadline,
                started=started,
            )
            fetched_url = normalize_url(str(fetched.url))
            if any(
                normalize_url(str(source.url)) == fetched_url or source.evidence_key == fetched.evidence_key
                for source in sources
            ):
                raise ResearchBackendError(
                    "codex returned a duplicate materialized source",
                    classification="needs_review",
                    code="codex_duplicate_materialized_source",
                )
            sources.append(fetched)
            if sum(len(source.content_text) for source in sources) > request.budget.max_total_chars:
                raise ResearchBackendError(
                    "codex research character budget exceeded",
                    classification="needs_review",
                    code="codex_character_budget_exceeded",
                )
            source_keys[candidate_url] = fetched.evidence_key
        return sources, source_keys

    def _materialize_claims(
        self,
        claims: list[CodexCandidateClaim],
        *,
        source_keys: dict[str, str],
        evidence_text: dict[str, str],
        deadline: float,
        started: float,
    ) -> list[CandidateClaim]:
        self._assert_within_deadline(deadline=deadline, started=started)
        materialized: list[CandidateClaim] = []
        for claim in claims:
            citations: list[CandidateCitation] = []
            for citation in claim.citations:
                if citation.source_url is not None:
                    try:
                        evidence_key = source_keys[normalize_url(str(citation.source_url))]
                    except KeyError:
                        raise ValueError("citation source URL was not returned") from None
                else:
                    evidence_key = citation.evidence_key or ""
                try:
                    content_text = evidence_text[evidence_key]
                except KeyError:
                    raise ValueError("citation evidence key is unknown") from None
                self._assert_within_deadline(deadline=deadline, started=started)
                if content_text.count(citation.quote) != 1:
                    raise ValueError("citation quote must occur exactly once")
                start = content_text.index(citation.quote)
                citations.append(
                    CandidateCitation(
                        evidence_key=evidence_key,
                        locator=f"chars:{start}-{start + len(citation.quote)}",
                        excerpt_sha256=sha256(citation.quote.encode("utf-8")).hexdigest(),
                    )
                )
            materialized.append(CandidateClaim(text=claim.text, citations=citations))
        return materialized


__all__ = [
    "CodexCandidateCitation",
    "CodexResearchBackend",
    "CodexResearchOutput",
    "CodexSourceCandidate",
    "ResearchBackendError",
]
