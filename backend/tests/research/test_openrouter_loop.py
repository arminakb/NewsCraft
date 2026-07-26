from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest

from app.generation.models import AIProviderProfile
from app.generation.providers.base import GenerationProviderResult
from app.research.base import ResearchBudgetExceeded, ResearchRequest
from app.research.schemas import DiscoveredSourcePayload, ResearchBudget
from app.stories.evidence import EvidenceRecord, build_evidence_key


def _brief(*, evidence_key: str, text: str, quote: str) -> dict[str, object]:
    start = text.index(quote)
    return {
        "summary": "Verified summary",
        "verified_facts": [
            {
                "text": "Verified fact",
                "citations": [
                    {
                        "evidence_key": evidence_key,
                        "locator": f"chars:{start}-{start + len(quote)}",
                        "excerpt_sha256": sha256(quote.encode()).hexdigest(),
                    }
                ],
            }
        ],
        "disagreements": [],
        "missing_information": [],
        "suggested_angles": [],
        "discovered_evidence_keys": [],
    }


def _request(**budget_changes) -> ResearchRequest:
    text = "Existing supplied evidence has an announced release date."
    digest = sha256(text.encode()).hexdigest()
    budget = ResearchBudget().model_copy(update=budget_changes)
    return ResearchRequest(
        run_id=uuid4(),
        story_id=uuid4(),
        provider_profile_id=uuid4(),
        requested_model="openai/test",
        mode="manual",
        evidence=[
            EvidenceRecord(
                evidence_key=build_evidence_key(
                    content_item_id=None,
                    source_url="https://input.example/report",
                    content_sha256=digest,
                ),
                evidence_snapshot_id=uuid4(),
                content_item_id=None,
                title="Input",
                content_text=text,
                content_sha256=digest,
                source_url="https://input.example/report",
                authors=(),
                published_at=None,
                captured_at=datetime.now(UTC),
            )
        ],
        budget=budget,
    )


def _profile(profile_id, **settings_changes) -> AIProviderProfile:
    settings = {
        "pricing": {
            "input_usd_per_million": "1.00",
            "output_usd_per_million": "2.00",
        },
        "research_budgets": {
            "standard": ResearchBudget().model_dump(mode="json"),
            "deep": ResearchBudget().model_dump(mode="json"),
        },
        **settings_changes,
    }
    return AIProviderProfile(
        id=profile_id,
        name="OpenRouter research",
        provider_type="openrouter",
        default_model="openai/test",
        secret_ref="env:OPENROUTER_API_KEY",
        settings=settings,
        enabled=True,
    )


class ScriptedModel:
    provider_name = "openrouter"

    def __init__(self, *outputs, usages=None):
        self.outputs = list(outputs)
        self.usages = list(usages or [{"input_tokens": 100, "output_tokens": 50}] * len(outputs))
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        output = self.outputs.pop(0)
        usage = self.usages.pop(0)
        return GenerationProviderResult(
            provider="openrouter",
            requested_model=request.requested_model,
            resolved_model=request.requested_model or "openai/test",
            output=output,
            raw_text="{}",
            usage=usage,
            finish_reason="stop",
        )


class FakeSearch:
    def __init__(self):
        self.queries = []
        self.timeouts = []

    async def search(self, query, *, limit, timeout_seconds):
        from app.research.duckduckgo import SearchResult

        self.queries.append(query)
        self.timeouts.append(timeout_seconds)
        return [SearchResult(title="Hit", url="https://one.example/report", snippet="snippet")]


class FakeFetcher:
    def __init__(self):
        self.urls = []

    async def fetch(self, url):
        self.urls.append(url)
        text = "Safely fetched source contains exact verified phrase."
        digest = sha256(text.encode()).hexdigest()
        return DiscoveredSourcePayload(
            evidence_key=build_evidence_key(content_item_id=None, source_url=url, content_sha256=digest),
            url=url,
            title="Fetched",
            retrieved_at=datetime.now(UTC),
            content_text=text,
            content_sha256=digest,
            extraction_status="ok",
        )


async def test_loop_enforces_query_page_and_character_budgets():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request(max_queries=1, max_pages=1, max_total_chars=10_000)
    finish_brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )
    fetched_text = "Safely fetched source contains exact verified phrase."
    finish_brief["discovered_evidence_keys"] = [
        build_evidence_key(
            content_item_id=None,
            source_url="https://one.example/report",
            content_sha256=sha256(fetched_text.encode()).hexdigest(),
        )
    ]
    model = ScriptedModel(
        {"action": "search", "query": "agent release"},
        {"action": "search", "query": "second query"},
        {"action": "fetch", "url": "https://one.example/report"},
        {"action": "fetch", "url": "https://two.example/report"},
        {"action": "finish", "brief": finish_brief},
    )
    search = FakeSearch()
    fetcher = FakeFetcher()
    backend = OpenRouterResearchBackend(
        model=model,
        search_client=search,
        fetcher=fetcher,
        profile=_profile(request.provider_profile_id),
    )

    result = await backend.research(request)

    assert search.queries == ["agent release"]
    assert fetcher.urls == ["https://one.example/report"]
    assert result.sanitized_events[-1]["budget_exhausted"] is True


async def test_final_answer_cannot_cite_search_result_that_was_not_fetched():
    from app.research.codex_adapter import ResearchBackendError
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request()
    unfetched = "url:https://unfetched.example/story:" + "0" * 64
    brief = _brief(evidence_key=unfetched, text="quote", quote="quote")
    backend = OpenRouterResearchBackend(
        model=ScriptedModel({"action": "finish", "brief": brief}),
        search_client=FakeSearch(),
        fetcher=FakeFetcher(),
        profile=_profile(request.provider_profile_id),
    )

    with pytest.raises(ResearchBackendError, match="citation URL was not fetched") as error:
        await backend.research(request)
    assert error.value.classification == "needs_review"


async def test_loop_enforces_exact_model_call_token_and_cost_budgets():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request(
        max_model_calls=1,
        max_input_tokens=1_000,
        max_output_tokens=500,
        max_cost_usd=Decimal("0.001"),
    )
    model = ScriptedModel(
        {"action": "search", "query": "agent release"},
        usages=[{"input_tokens": 1_000, "output_tokens": 1}],
    )
    backend = OpenRouterResearchBackend(
        model=model,
        search_client=FakeSearch(),
        fetcher=FakeFetcher(),
        profile=_profile(request.provider_profile_id),
    )

    with pytest.raises(ResearchBudgetExceeded, match="cost budget exhausted"):
        await backend.research(request)
    assert len(model.requests) == 1
    assert model.requests[0].metadata["max_output_tokens"] == 500


async def test_finish_validates_locator_and_excerpt_hash_and_returns_fetched_source():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request()
    fetcher = FakeFetcher()
    fetched = await fetcher.fetch("https://one.example/report")
    fetcher.urls.clear()
    brief = _brief(
        evidence_key=fetched.evidence_key,
        text=fetched.content_text,
        quote="exact verified phrase",
    )
    brief["discovered_evidence_keys"] = [fetched.evidence_key]
    model = ScriptedModel(
        {"action": "fetch", "url": "https://one.example/report"},
        {"action": "finish", "brief": brief},
    )
    backend = OpenRouterResearchBackend(
        model=model,
        search_client=FakeSearch(),
        fetcher=fetcher,
        profile=_profile(request.provider_profile_id),
    )

    result = await backend.research(request)

    assert result.output.sources[0].evidence_key == fetched.evidence_key
    assert result.output.brief == result.output.brief.model_validate(brief)
    assert result.usage.pages == 1


@pytest.mark.parametrize("usage", [{}, {"input_tokens": 1}, {"output_tokens": 1}])
async def test_model_usage_is_required(usage):
    from app.research.codex_adapter import ResearchBackendError
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request()
    backend = OpenRouterResearchBackend(
        model=ScriptedModel({"action": "search", "query": "query"}, usages=[usage]),
        search_client=FakeSearch(),
        fetcher=FakeFetcher(),
        profile=_profile(request.provider_profile_id),
    )

    with pytest.raises(ResearchBackendError, match="usage is unavailable") as error:
        await backend.research(request)
    assert error.value.classification == "needs_review"


def test_profile_requires_enabled_openrouter_nested_pricing_and_budgets():
    from app.research.codex_adapter import ResearchBackendError
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request()
    disabled = _profile(request.provider_profile_id)
    disabled.enabled = False
    wrong_type = _profile(request.provider_profile_id)
    wrong_type.provider_type = "fake"
    cases = [
        disabled,
        wrong_type,
        _profile(request.provider_profile_id, pricing=None),
        _profile(request.provider_profile_id, research_budgets=None),
        _profile(request.provider_profile_id, input_cost_per_million="1"),
    ]
    for profile in cases:
        with pytest.raises(ResearchBackendError):
            OpenRouterResearchBackend(
                model=ScriptedModel(),
                search_client=FakeSearch(),
                fetcher=FakeFetcher(),
                profile=profile,
            )


async def test_remaining_output_allowance_reaches_openrouter_transport():
    from app.generation.providers.openrouter import OpenRouterProvider
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request(max_output_tokens=500)
    brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )
    captured = {}

    async def handler(http_request):
        captured.update(__import__("json").loads(http_request.content))
        return httpx.Response(
            200,
            json={
                "model": "openai/test",
                "choices": [
                    {
                        "message": {"content": __import__("json").dumps({"action": "finish", "brief": brief})},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = OpenRouterResearchBackend(
            model=OpenRouterProvider(http_client=client, api_key="test-key"),
            search_client=FakeSearch(),
            fetcher=FakeFetcher(),
            profile=_profile(request.provider_profile_id),
        )
        await backend.research(request)

    assert captured["max_tokens"] == 500


async def test_zero_pricing_allows_zero_cost_budget():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request(max_cost_usd=Decimal("0"))
    brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )
    backend = OpenRouterResearchBackend(
        model=ScriptedModel({"action": "finish", "brief": brief}),
        search_client=FakeSearch(),
        fetcher=FakeFetcher(),
        profile=_profile(
            request.provider_profile_id,
            pricing={"input_usd_per_million": "0", "output_usd_per_million": "0"},
        ),
    )

    result = await backend.research(request)

    assert result.usage.estimated_cost_usd == Decimal("0")


async def test_rejected_fetch_consumes_page_action_budget():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    class RejectFirstFetcher(FakeFetcher):
        async def fetch(self, url):
            self.urls.append(url)
            if len(self.urls) == 1:
                raise RuntimeError("forbidden detail")
            return await super().fetch(url)

    request = _request(max_pages=1)
    brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )
    fetcher = RejectFirstFetcher()
    backend = OpenRouterResearchBackend(
        model=ScriptedModel(
            {"action": "fetch", "url": "https://blocked.example/report"},
            {"action": "fetch", "url": "https://must-not-run.example/report"},
            {"action": "finish", "brief": brief},
        ),
        search_client=FakeSearch(),
        fetcher=fetcher,
        profile=_profile(request.provider_profile_id),
    )

    result = await backend.research(request)

    assert fetcher.urls == ["https://blocked.example/report"]
    assert result.usage.pages == 1
    assert result.sanitized_events[-1]["budget_exhausted"] is True


async def test_transport_missing_usage_is_needs_review():
    from app.generation.providers.openrouter import OpenRouterProvider
    from app.research.codex_adapter import ResearchBackendError
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request()
    brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )

    async def handler(_request):
        return httpx.Response(
            200,
            json={
                "model": "openai/test",
                "choices": [
                    {
                        "message": {"content": __import__("json").dumps({"action": "finish", "brief": brief})},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = OpenRouterResearchBackend(
            model=OpenRouterProvider(http_client=client, api_key="test-key"),
            search_client=FakeSearch(),
            fetcher=FakeFetcher(),
            profile=_profile(request.provider_profile_id),
        )
        with pytest.raises(ResearchBackendError, match="usage is unavailable") as error:
            await backend.research(request)
    assert error.value.classification == "needs_review"


async def test_elapsed_budget_is_checked_after_model_finishes():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    class Clock:
        value = 0.0

        def __call__(self):
            return self.value

    class AdvancingModel(ScriptedModel):
        async def generate(self, request):
            clock.value = 10.0
            return await super().generate(request)

    request = _request(max_elapsed_seconds=10)
    brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )
    clock = Clock()
    backend = OpenRouterResearchBackend(
        model=AdvancingModel({"action": "finish", "brief": brief}),
        search_client=FakeSearch(),
        fetcher=FakeFetcher(),
        profile=_profile(request.provider_profile_id),
        monotonic=clock,
    )

    with pytest.raises(ResearchBudgetExceeded, match="elapsed time budget exhausted"):
        await backend.research(request)


async def test_provider_failures_are_classified_without_leaking_details():
    from app.generation.providers.openrouter import OpenRouterRetryableError
    from app.research.codex_adapter import ResearchBackendError
    from app.research.openrouter_loop import OpenRouterResearchBackend

    class FailingModel:
        provider_name = "openrouter"

        async def generate(self, _request):
            raise OpenRouterRetryableError(
                code="secret-code",
                message="provider detail with bearer super-secret",
            )

    request = _request()
    backend = OpenRouterResearchBackend(
        model=FailingModel(),
        search_client=FakeSearch(),
        fetcher=FakeFetcher(),
        profile=_profile(request.provider_profile_id),
    )

    with pytest.raises(ResearchBackendError) as error:
        await backend.research(request)

    assert error.value.classification == "retryable"
    assert str(error.value) == "openrouter research provider failed"
    assert "secret" not in str(error.value)


async def test_exhausted_character_budget_prevents_another_fetch():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    class FullBudgetFetcher(FakeFetcher):
        async def fetch(self, url):
            self.urls.append(url)
            text = "x" * 10_000
            digest = sha256(text.encode()).hexdigest()
            return DiscoveredSourcePayload(
                evidence_key=build_evidence_key(
                    content_item_id=None,
                    source_url=url,
                    content_sha256=digest,
                ),
                url=url,
                retrieved_at=datetime.now(UTC),
                content_text=text,
                content_sha256=digest,
                extraction_status="ok",
            )

    request = _request(max_total_chars=10_000)
    source_key = build_evidence_key(
        content_item_id=None,
        source_url="https://one.example/report",
        content_sha256=sha256(("x" * 10_000).encode()).hexdigest(),
    )
    brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )
    brief["discovered_evidence_keys"] = [source_key]
    fetcher = FullBudgetFetcher()
    backend = OpenRouterResearchBackend(
        model=ScriptedModel(
            {"action": "fetch", "url": "https://one.example/report"},
            {"action": "fetch", "url": "https://two.example/report"},
            {"action": "finish", "brief": brief},
        ),
        search_client=FakeSearch(),
        fetcher=fetcher,
        profile=_profile(request.provider_profile_id),
    )

    result = await backend.research(request)

    assert fetcher.urls == ["https://one.example/report"]
    assert result.usage.fetched_characters == 10_000


async def test_terminal_citation_scan_remains_inside_one_deadline():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    class CrossingClock:
        def __init__(self, cross_on_call):
            self.calls = 0
            self.cross_on_call = cross_on_call

        def __call__(self):
            self.calls += 1
            return 10.0 if self.calls >= self.cross_on_call else 0.0

    request = _request(max_elapsed_seconds=10)
    brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )
    clock = CrossingClock(cross_on_call=8)
    backend = OpenRouterResearchBackend(
        model=ScriptedModel({"action": "finish", "brief": brief}),
        search_client=FakeSearch(),
        fetcher=FakeFetcher(),
        profile=_profile(request.provider_profile_id),
        monotonic=clock,
    )

    with pytest.raises(ResearchBudgetExceeded, match="elapsed time budget exhausted"):
        await backend.research(request)


async def test_terminal_result_just_under_deadline_succeeds_with_final_elapsed():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    class JustUnderClock:
        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            return 0.0 if self.calls == 1 else 9.999

    request = _request(max_elapsed_seconds=10)
    brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )
    backend = OpenRouterResearchBackend(
        model=ScriptedModel({"action": "finish", "brief": brief}),
        search_client=FakeSearch(),
        fetcher=FakeFetcher(),
        profile=_profile(request.provider_profile_id),
        monotonic=JustUnderClock(),
    )

    result = await backend.research(request)

    assert result.elapsed_ms == 9_999


async def test_loop_passes_exact_remaining_deadline_to_search_transport():
    from app.research.openrouter_loop import OpenRouterResearchBackend

    request = _request(max_elapsed_seconds=10)
    brief = _brief(
        evidence_key=request.evidence[0].evidence_key,
        text=request.evidence[0].content_text,
        quote="announced release date",
    )
    search = FakeSearch()
    backend = OpenRouterResearchBackend(
        model=ScriptedModel(
            {"action": "search", "query": "agent release"},
            {"action": "finish", "brief": brief},
        ),
        search_client=search,
        fetcher=FakeFetcher(),
        profile=_profile(request.provider_profile_id),
        monotonic=lambda: 0.0,
    )

    await backend.research(request)

    assert search.timeouts == [10.0]
