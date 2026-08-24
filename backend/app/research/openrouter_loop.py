from __future__ import annotations

import json
import time
from collections.abc import Callable
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, ValidationError

from app.generation.models import AIProviderProfile
from app.generation.provider_settings import OpenRouterProviderSettings, ResearchBudgetSettings
from app.generation.providers.base import GenerationProvider, GenerationProviderRequest, ProviderMessage
from app.generation.providers.openrouter import (
    OpenRouterNeedsReviewError,
    OpenRouterPermanentError,
    OpenRouterRetryableError,
)
from app.normalization.urls import normalize_url
from app.research.base import (
    ResearchBackendOutput,
    ResearchBudgetExceeded,
    ResearchRequest,
    ResearchResult,
    ResearchUsage,
)
from app.research.codex_adapter import ResearchBackendError
from app.research.deadline import elapsed_ms as deadline_elapsed_ms
from app.research.deadline import with_deadline
from app.research.duckduckgo import DuckDuckGoSearchClient
from app.research.prompts import compose_system_policy as _compose_system_policy
from app.research.safe_fetch import SafeArticleFetcher
from app.research.schemas import CandidateResearchBrief, DiscoveredSourcePayload, ResearchBudget

MAX_ACTIONS = 12


class SearchAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["search"]
    query: str = Field(min_length=2, max_length=200)


class FetchAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["fetch"]
    url: HttpUrl


class FinishAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["finish"]
    brief: CandidateResearchBrief


ResearchAction = Annotated[SearchAction | FetchAction | FinishAction, Field(discriminator="action")]
_ACTION_ADAPTER: TypeAdapter[ResearchAction] = TypeAdapter(ResearchAction)


def research_action_schema() -> dict[str, Any]:
    """Return the exact structured-action schema used by the research loop."""

    return _ACTION_ADAPTER.json_schema()


class OpenRouterResearchBackend:
    name = "openrouter"

    def __init__(
        self,
        *,
        model: GenerationProvider,
        search_client: DuckDuckGoSearchClient,
        fetcher: SafeArticleFetcher,
        profile: AIProviderProfile,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.model = model
        self.search_client = search_client
        self.fetcher = fetcher
        self.profile = profile
        self.monotonic = monotonic
        self.settings = self._validate_profile(profile)
        assert self.settings.pricing is not None
        assert self.settings.research_budgets is not None
        self.pricing = self.settings.pricing

    async def research(self, request: ResearchRequest) -> ResearchResult:
        if request.provider_profile_id != self.profile.id:
            raise _needs_review("openrouter research profile does not match request", "profile_mismatch")
        selected = getattr(self.settings.research_budgets, request.depth)
        _validate_request_budget(request.budget, selected)

        started = self.monotonic()
        usage = _MutableUsage()
        sources: list[DiscoveredSourcePayload] = []
        observations: list[dict[str, object]] = []
        events: list[dict[str, object]] = []
        resolved_model = request.requested_model

        for _ in range(MAX_ACTIONS):
            self._check_elapsed(request.budget, started)
            self._check_before_model(request.budget, usage)
            remaining_output = request.budget.max_output_tokens - usage.output_tokens
            provider_request = GenerationProviderRequest(
                run_id=request.run_id,
                purpose="research_action",
                requested_model=request.requested_model,
                messages=(
                    ProviderMessage(role="system", content=_compose_system_policy(request.system_prompt)),
                    ProviderMessage(
                        role="user",
                        content=_build_loop_input(request, observations),
                    ),
                ),
                response_schema=_ACTION_ADAPTER.json_schema(),
                metadata={"max_output_tokens": remaining_output},
            )
            try:
                result = await self._within_deadline(
                    self.model.generate(provider_request),
                    budget=request.budget,
                    started=started,
                )
            except OpenRouterRetryableError:
                raise _provider_error("retryable") from None
            except OpenRouterNeedsReviewError:
                raise _provider_error("needs_review") from None
            except OpenRouterPermanentError:
                raise _provider_error("permanent") from None
            self._check_elapsed(request.budget, started)
            resolved_model = result.resolved_model
            input_tokens, output_tokens = _required_usage(result.usage)
            usage.model_calls += 1
            usage.input_tokens += input_tokens
            usage.output_tokens += output_tokens
            usage.cost += (
                Decimal(input_tokens) * self.pricing.input_usd_per_million
                + Decimal(output_tokens) * self.pricing.output_usd_per_million
            ) / Decimal(1_000_000)
            self._check_after_model(request.budget, usage)
            try:
                action = _ACTION_ADAPTER.validate_python(result.output)
            except ValidationError:
                raise _needs_review(
                    "openrouter research returned an invalid action",
                    "invalid_action",
                ) from None
            self._check_elapsed(request.budget, started)

            if isinstance(action, FinishAction):
                output = _validated_finish(
                    request,
                    action.brief,
                    sources,
                    check_deadline=lambda: self._check_elapsed(request.budget, started),
                )
                self._check_elapsed(request.budget, started)
                elapsed_ms = deadline_elapsed_ms(self.monotonic, started)
                final_result = ResearchResult(
                    provider_profile_id=request.provider_profile_id,
                    provider_type="openrouter",
                    requested_model=request.requested_model,
                    resolved_model=resolved_model,
                    output=output,
                    usage=usage.freeze(),
                    elapsed_ms=elapsed_ms,
                    sanitized_events=events,
                )
                self._check_elapsed(request.budget, started)
                return final_result
            if isinstance(action, SearchAction):
                if usage.queries >= request.budget.max_queries:
                    _record_exhausted(observations, events, action="search")
                    continue
                usage.queries += 1
                try:
                    remaining = self._remaining_seconds(request.budget, started)
                    results = await self._within_deadline(
                        self.search_client.search(
                            action.query,
                            limit=request.budget.max_results_per_query,
                            timeout_seconds=remaining,
                        ),
                        budget=request.budget,
                        started=started,
                    )
                except ResearchBudgetExceeded:
                    raise
                except Exception:
                    observations.append({"action": "search", "status": "failed"})
                    events.append({"action": "search", "status": "failed"})
                else:
                    observations.append(
                        {
                            "action": "search",
                            "status": "ok",
                            "results": [item.model_dump(mode="json") for item in results],
                        }
                    )
                    events.append({"action": "search", "status": "ok", "result_count": len(results)})
                continue

            if usage.pages >= request.budget.max_pages or usage.fetched_characters >= request.budget.max_total_chars:
                _record_exhausted(observations, events, action="fetch")
                continue
            usage.pages += 1
            try:
                source = await self._within_deadline(
                    self.fetcher.fetch(str(action.url)),
                    budget=request.budget,
                    started=started,
                )
            except ResearchBudgetExceeded:
                raise
            except Exception:
                observations.append({"action": "fetch", "status": "rejected"})
                events.append({"action": "fetch", "status": "rejected"})
                continue
            if usage.fetched_characters + len(source.content_text) > request.budget.max_total_chars:
                _record_exhausted(observations, events, action="fetch")
                continue
            if any(
                existing.evidence_key == source.evidence_key
                or normalize_url(str(existing.url)) == normalize_url(str(source.url))
                for existing in sources
            ):
                observations.append({"action": "fetch", "status": "duplicate"})
                events.append({"action": "fetch", "status": "duplicate"})
                continue
            sources.append(source)
            usage.fetched_characters += len(source.content_text)
            observations.append(
                {
                    "action": "fetch",
                    "status": "ok",
                    "source": source.model_dump(mode="json"),
                    "content_chars": len(source.content_text),
                }
            )
            events.append({"action": "fetch", "status": "ok", "evidence_key": source.evidence_key})

        raise ResearchBudgetExceeded("action budget exhausted")

    @staticmethod
    def _validate_profile(profile: AIProviderProfile) -> OpenRouterProviderSettings:
        if not profile.enabled or profile.provider_type != "openrouter":
            raise _needs_review("openrouter research profile is unavailable", "profile_unavailable")
        try:
            settings = OpenRouterProviderSettings.model_validate(dict(profile.settings or {}))
        except ValidationError:
            raise _needs_review("openrouter research profile settings are invalid", "profile_invalid") from None
        if settings.pricing is None or settings.research_budgets is None:
            raise _needs_review("openrouter research pricing and budgets are required", "profile_incomplete")
        return settings

    def _check_elapsed(self, budget: ResearchBudget, started: float) -> None:
        if self.monotonic() >= started + budget.max_elapsed_seconds:
            raise ResearchBudgetExceeded("elapsed time budget exhausted")

    async def _within_deadline(self, awaitable, *, budget: ResearchBudget, started: float):
        return await with_deadline(
            awaitable,
            remaining_seconds=started + budget.max_elapsed_seconds - self.monotonic(),
            on_expired=lambda: ResearchBudgetExceeded("elapsed time budget exhausted"),
        )

    def _remaining_seconds(self, budget: ResearchBudget, started: float) -> float:
        remaining = started + budget.max_elapsed_seconds - self.monotonic()
        if remaining <= 0:
            raise ResearchBudgetExceeded("elapsed time budget exhausted")
        return remaining

    def _check_before_model(self, budget: ResearchBudget, usage: _MutableUsage) -> None:
        if usage.model_calls >= budget.max_model_calls:
            raise ResearchBudgetExceeded("model call budget exhausted")
        if usage.input_tokens >= budget.max_input_tokens:
            raise ResearchBudgetExceeded("input token budget exhausted")
        if usage.output_tokens >= budget.max_output_tokens:
            raise ResearchBudgetExceeded("output token budget exhausted")
        has_nonzero_rate = self.pricing.input_usd_per_million > 0 or self.pricing.output_usd_per_million > 0
        if has_nonzero_rate and usage.cost >= budget.max_cost_usd:
            raise ResearchBudgetExceeded("cost budget exhausted")

    @staticmethod
    def _check_after_model(budget: ResearchBudget, usage: _MutableUsage) -> None:
        if usage.input_tokens > budget.max_input_tokens:
            raise ResearchBudgetExceeded("input token budget exhausted")
        if usage.output_tokens > budget.max_output_tokens:
            raise ResearchBudgetExceeded("output token budget exhausted")
        if usage.cost > budget.max_cost_usd:
            raise ResearchBudgetExceeded("cost budget exhausted")


class _MutableUsage:
    def __init__(self) -> None:
        self.model_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost = Decimal("0")
        self.queries = 0
        self.pages = 0
        self.fetched_characters = 0

    def freeze(self) -> ResearchUsage:
        return ResearchUsage(
            model_calls=self.model_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            estimated_cost_usd=self.cost,
            queries=self.queries,
            pages=self.pages,
            fetched_characters=self.fetched_characters,
        )


def _required_usage(usage: dict[str, Any]) -> tuple[int, int]:
    if usage.get("usage_supplied") is False:
        raise _needs_review("openrouter research usage is unavailable", "usage_unavailable")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (input_tokens, output_tokens)
    ):
        raise _needs_review("openrouter research usage is unavailable", "usage_unavailable")
    assert isinstance(input_tokens, int)
    assert isinstance(output_tokens, int)
    return input_tokens, output_tokens


def _validate_request_budget(request: ResearchBudget, ceiling: ResearchBudgetSettings) -> None:
    dimensions = (
        "max_model_calls",
        "max_input_tokens",
        "max_output_tokens",
        "max_cost_usd",
        "max_queries",
        "max_results_per_query",
        "max_pages",
        "max_elapsed_seconds",
        "max_total_chars",
    )
    if any(getattr(request, field) > getattr(ceiling, field) for field in dimensions):
        raise _needs_review("openrouter research request exceeds profile budget", "budget_invalid")


def _validated_finish(
    request: ResearchRequest,
    brief: CandidateResearchBrief,
    sources: list[DiscoveredSourcePayload],
    *,
    check_deadline: Callable[[], None],
) -> ResearchBackendOutput:
    check_deadline()
    source_keys: list[str] = []
    for source in sources:
        check_deadline()
        source_keys.append(source.evidence_key)
    if len(source_keys) != len(set(source_keys)) or set(brief.discovered_evidence_keys) != set(source_keys):
        raise _needs_review("openrouter research discovered evidence is invalid", "evidence_invalid")
    check_deadline()
    evidence: dict[str, str] = {}
    for record in request.evidence:
        check_deadline()
        evidence[record.evidence_key] = record.content_text
    for source in sources:
        check_deadline()
        evidence[source.evidence_key] = source.content_text
    for claim in (*brief.verified_facts, *brief.disagreements):
        check_deadline()
        for citation in claim.citations:
            check_deadline()
            content = evidence.get(citation.evidence_key)
            if content is None:
                if citation.evidence_key.startswith("url:"):
                    raise _needs_review("citation URL was not fetched", "citation_unfetched")
                raise _needs_review("citation evidence key is unknown", "citation_unknown")
            parts = citation.locator.removeprefix("chars:").split("-")
            try:
                start, end = (int(value) for value in parts)
            except TypeError, ValueError:
                raise _needs_review("citation locator is invalid", "citation_invalid") from None
            if citation.locator != f"chars:{start}-{end}" or start < 0 or end <= start or end > len(content):
                raise _needs_review("citation locator is invalid", "citation_invalid")
            excerpt = content[start:end]
            if sha256(excerpt.encode()).hexdigest() != citation.excerpt_sha256:
                raise _needs_review("citation excerpt hash is invalid", "citation_invalid")
    output = ResearchBackendOutput(sources=sources, brief=brief)
    check_deadline()
    return output


def _build_loop_input(request: ResearchRequest, observations: list[dict[str, object]]) -> str:
    payload = {
        "request": {
            "query_hint": request.query_hint,
            "evidence": [
                {
                    "evidence_key": record.evidence_key,
                    "title": record.title,
                    "content_text": record.content_text,
                    "content_chars": len(record.content_text),
                    "content_sha256": record.content_sha256,
                    "source_url": record.source_url,
                }
                for record in request.evidence
            ],
        },
        "observations": observations,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _record_exhausted(
    observations: list[dict[str, object]],
    events: list[dict[str, object]],
    *,
    action: str,
) -> None:
    value = {"action": action, "status": "skipped", "budget_exhausted": True}
    observations.append(value)
    events.append(value.copy())


def _needs_review(message: str, code: str) -> ResearchBackendError:
    return ResearchBackendError(
        message,
        classification="needs_review",
        code=f"openrouter_{code}",
    )


def _provider_error(classification: Literal["retryable", "needs_review", "permanent"]) -> ResearchBackendError:
    return ResearchBackendError(
        "openrouter research provider failed",
        classification=classification,
        code="openrouter_provider_failed",
    )


__all__ = [
    "FetchAction",
    "FinishAction",
    "OpenRouterResearchBackend",
    "ResearchAction",
    "SearchAction",
    "research_action_schema",
]
