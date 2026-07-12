from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.content_production.briefs import EditorialBriefService
from app.content_production.evidence import (
    build_evidence_bundle,
    evaluate_enrichment_relevance,
    relevant_enrichment_findings,
)
from app.content_production.llm import (
    BriefGenerationOutput,
    DraftGenerationOutput,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    OpenAIResponsesProvider,
    OpenRouterChatCompletionsProvider,
    QualityEvaluationOutput,
    output_schema,
    quality_gate_status,
)
from app.content_production.quality import DraftQualityService
from app.content_production.sufficiency import SufficiencyInputs, SufficiencyStage, evaluate_content_sufficiency
from app.content_production.telegram_drafts import TelegramDraftService
from app.core.config import Settings
from app.db.models import (
    ArticleExtractionResult,
    Base,
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    DraftQualityReport,
    EditorialBrief,
    TelegramDraft,
    WebEnrichmentResult,
)


@pytest.fixture
def content_item():
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="ChatGPT Sites",
        summary="OpenAI introduced a lightweight website workflow with Codex.",
        content_text="OpenAI introduced a lightweight website workflow with Codex.",
        canonical_url="https://openai.com/academy/chatgpt-sites",
        classification_metadata={"source_name": "OpenAI"},
        tags=["ai"],
        sort_at=datetime(2026, 7, 11, tzinfo=UTC),
        status="new",
    )


@pytest.fixture
def extraction_result(content_item):
    return ArticleExtractionResult(
        id=uuid4(),
        production_run_id=uuid4(),
        content_item_id=content_item.id,
        status="ok",
        source_url=content_item.canonical_url,
        final_url=content_item.canonical_url,
        content_text="متن کامل و مستند مقاله " * 500,
        warnings_json=[],
        metadata_json={},
    )


@pytest.fixture
def enrichment_result(content_item, extraction_result):
    return WebEnrichmentResult(
        id=uuid4(),
        production_run_id=extraction_result.production_run_id,
        content_item_id=content_item.id,
        provider_name="fake",
        status="ok",
        query_json={},
        findings_json=[
            {
                "title": "ChatGPT Sites launches for lightweight websites",
                "url": "https://source.test/chatgpt-sites",
                "snippet": "OpenAI introduced ChatGPT Sites as a Codex workflow.",
                "source_name": "Independent Source",
            }
        ],
        source_attribution_json=[],
        warnings_json=[],
    )


def test_exact_product_and_organization_matches_are_relevant():
    findings = [
        {
            "title": "ChatGPT Sites launches for lightweight websites",
            "url": "https://openai.com/news/chatgpt-sites",
            "snippet": "OpenAI introduced ChatGPT Sites as a Codex workflow.",
            "source_name": "OpenAI",
        }
    ]

    assessed = evaluate_enrichment_relevance(
        title="ChatGPT Sites",
        source_url="https://openai.com/academy/chatgpt-sites",
        source_name="OpenAI",
        findings=findings,
    )

    assert assessed[0]["relevance_status"] == "relevant"
    assert assessed[0]["accepted_for_evidence"] is True
    assert assessed[0]["relevance_score"] >= 0.65
    assert "title_term_overlap" in assessed[0]["matched_signals"]


def test_weak_keywords_and_result_count_inflation_are_rejected():
    findings = [
        {
            "title": f"General AI weekly update {index}",
            "url": f"https://source{index}.test/ai",
            "snippet": "A roundup of unrelated model and API announcements.",
            "source_name": f"Source {index}",
        }
        for index in range(10)
    ]

    assessed = evaluate_enrichment_relevance(
        title="ChatGPT Sites",
        source_url="https://openai.com/academy/chatgpt-sites",
        source_name="OpenAI",
        findings=findings,
    )

    assert relevant_enrichment_findings(assessed) == []
    assert all(row["relevance_status"] in {"weak", "unrelated"} for row in assessed)
    assert all(row["rejection_reason"] for row in assessed)


def test_multiple_moderate_independent_results_meet_policy_but_duplicates_do_not():
    common = {
        "title": "ChatGPT Sites details",
        "snippet": "ChatGPT Sites creates lightweight sites with Codex.",
        "source_name": "Independent",
    }
    rows = evaluate_enrichment_relevance(
        title="ChatGPT Sites for Codex",
        source_url="https://openai.com/academy/chatgpt-sites",
        source_name="OpenAI",
        findings=[
            {**common, "url": "https://one.test/story"},
            {**common, "url": "https://two.test/story"},
            {**common, "url": "https://one.test/duplicate"},
            {**common, "url": "https://openai.com/academy/chatgpt-sites"},
        ],
    )

    accepted = relevant_enrichment_findings(rows)
    assert {row["url"] for row in accepted} == {"https://one.test/story", "https://two.test/story"}


def test_evidence_bundle_is_bounded_and_keeps_source_identity(content_item, extraction_result, enrichment_result):
    enrichment_result.findings_json = evaluate_enrichment_relevance(
        title=content_item.title,
        source_url=content_item.canonical_url,
        source_name="Publisher",
        findings=enrichment_result.findings_json,
    )

    evidence = build_evidence_bundle(content_item, extraction_result, enrichment_result)

    assert evidence
    assert all(row["evidence_id"] and row["source_url"] for row in evidence)
    assert max(len(row["text"]) for row in evidence) <= 6000
    assert all("html" not in row for row in evidence)
    assert all(row["kind"] != "enrichment" or row["accepted"] for row in evidence)


def test_unrelated_result_count_cannot_raise_sufficiency(content_item, enrichment_result):
    content_item.summary = "خلاصه کوتاه"
    content_item.content_text = "خلاصه کوتاه"
    content_item.is_rewrite_ready = True
    enrichment_result.findings_json = evaluate_enrichment_relevance(
        title=content_item.title,
        source_url=content_item.canonical_url,
        source_name="OpenAI",
        findings=[
            {
                "title": f"General AI update {index}",
                "url": f"https://source{index}.test/story",
                "snippet": "Unrelated model announcements and industry news. " * 20,
            }
            for index in range(20)
        ],
    )
    inputs = SufficiencyInputs(
        stage=SufficiencyStage.POST_ENRICHMENT,
        run=ContentProductionRun(
            id=enrichment_result.production_run_id,
            request_id=uuid4(),
            content_item_id=content_item.id,
            state="enriched",
        ),
        item=content_item,
        source_event_id=uuid4(),
        enrichment=enrichment_result,
    )

    decision = evaluate_content_sufficiency(content_item, supplemental_text=inputs.supplemental_text)

    assert inputs.supplemental_text == ""
    assert decision.status != "sufficient"


async def test_openai_provider_returns_structured_output_and_metadata():
    output = {"value": "ساختار معتبر"}
    response = {
        "model": "gpt-5-mini-2025-08-07",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(output)}]}],
        "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAIResponsesProvider(api_key="secret-value", model="gpt-5-mini", client=client)
        result = await provider.generate(_request())

    assert result.output == output
    assert result.provider_name == "openai"
    assert result.model_name == "gpt-5-mini-2025-08-07"
    assert result.input_tokens == 120
    assert result.total_tokens == 150
    assert result.latency_ms >= 0


async def test_openai_provider_sends_responses_structured_output_request_shape():
    output = {"value": "ok"}
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_contract",
                "model": "openai/gpt-5-mini",
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(output)}]}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAIResponsesProvider(
            api_key="secret-value",
            model="openai/gpt-5-mini",
            base_url="https://openrouter.ai/api/v1",
            client=client,
        )
        await provider.generate(_request())

    assert captured["url"] == "https://openrouter.ai/api/v1/responses"
    assert captured["payload"]["model"] == "openai/gpt-5-mini"
    assert captured["payload"]["instructions"] == "Return the schema."
    assert isinstance(captured["payload"]["input"], str)
    assert captured["payload"]["text"]["format"] == {
        "type": "json_schema",
        "name": "newscraft_test",
        "schema": _request().output_schema,
        "strict": True,
    }
    assert captured["payload"]["max_output_tokens"] == 200
    assert captured["payload"]["store"] is False
    assert "response_format" not in captured["payload"]
    assert "Authorization" not in json.dumps(captured["payload"])


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(401, "authentication_failed", False), (429, "rate_limited", True)],
)
async def test_openai_provider_classifies_http_failures_without_leaking_secret(status, code, retryable):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"error": {"message": "secret-value should not escape"}})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAIResponsesProvider(api_key="secret-value", model="gpt-5-mini", client=client)
        with pytest.raises(LLMProviderError) as caught:
            await provider.generate(_request())

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "secret-value" not in str(caught.value)


async def test_openai_provider_classifies_timeout_and_malformed_json():
    def timeout(request):
        raise httpx.ReadTimeout("credential must not escape", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(LLMProviderError, match="provider_timeout") as caught:
            await OpenAIResponsesProvider(api_key="key", model="gpt-5-mini", client=client).generate(_request())
    assert caught.value.retryable is True

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "gpt-5-mini",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "{"}]}],
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(LLMProviderError, match="text_not_valid_json") as malformed:
            await OpenAIResponsesProvider(api_key="key", model="gpt-5-mini", client=client).generate(_request())
    assert malformed.value.retryable is False


async def test_openai_provider_uses_openrouter_usage_aliases():
    response = _provider_response(
        {"value": "ok"},
        usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await OpenAIResponsesProvider(api_key="key", model="gpt-5-mini", client=client).generate(_request())

    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.total_tokens == 18


async def test_openai_provider_ignores_non_message_output_items():
    response = {
        "model": "openai/gpt-5-mini",
        "status": "completed",
        "output": [
            {"type": "reasoning", "content": [{"type": "output_text", "text": "not json"}]},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps({"value": "ok"})}]},
        ],
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await OpenAIResponsesProvider(api_key="key", model="gpt-5-mini", client=client).generate(_request())

    assert result.output == {"value": "ok"}


async def test_openai_provider_classifies_observed_openrouter_reasoning_only_incomplete_response():
    response = {
        "background": False,
        "completed_at": None,
        "created_at": 0,
        "error": None,
        "frequency_penalty": None,
        "id": "resp_observed_openrouter",
        "incomplete_details": {"reason": "max_output_tokens"},
        "instructions": None,
        "max_output_tokens": 900,
        "max_tool_calls": None,
        "metadata": {},
        "model": "openai/gpt-5-mini-2025-08-07",
        "object": "response",
        "status": "incomplete",
        "output": [{"type": "reasoning"}],
        "parallel_tool_calls": False,
        "presence_penalty": None,
        "previous_response_id": None,
        "prompt_cache_key": None,
        "reasoning": {},
        "safety_identifier": None,
        "service_tier": None,
        "store": False,
        "temperature": None,
        "text": {},
        "tool_choice": "auto",
        "tools": [],
        "top_logprobs": None,
        "top_p": None,
        "truncation": None,
        "usage": {
            "cost": 0.0,
            "cost_details": {},
            "input_tokens": 289,
            "input_tokens_details": {},
            "is_byok": True,
            "output_tokens": 900,
            "output_tokens_details": {},
            "total_tokens": 1189,
        },
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(LLMProviderError) as caught:
            await OpenAIResponsesProvider(api_key="key", model="openai/gpt-5-mini", client=client).generate(
                _request()
            )

    assert caught.value.code == "incomplete_output"
    assert caught.value.retryable is False
    assert caught.value.diagnostics["http_status"] == 200
    assert caught.value.diagnostics["response_status"] == "incomplete"
    assert caught.value.diagnostics["output_item_count"] == 1
    assert caught.value.diagnostics["output_item_types"] == ["reasoning"]
    assert caught.value.diagnostics["content_part_types"] == []
    assert caught.value.diagnostics["output_text_found"] is False
    assert caught.value.diagnostics["provider_model"] == "openai/gpt-5-mini-2025-08-07"
    assert caught.value.diagnostics["usage_keys"] == [
        "cost",
        "cost_details",
        "input_tokens",
        "input_tokens_details",
        "is_byok",
        "output_tokens",
        "output_tokens_details",
        "total_tokens",
    ]
    assert "raw_output_text" not in caught.value.diagnostics


def _provider_response_text(text: str) -> dict:
    return {
        "model": "openai/gpt-5-mini",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
    }


@pytest.mark.parametrize(
    ("payload", "code", "diagnostic_subset"),
    [
        (
            {"id": "resp_failed", "status": "failed", "error_type": "unsupported_parameter", "output": []},
            "provider_response_failed",
            {"response_status": "failed", "provider_error_type": "unsupported_parameter"},
        ),
        (
            {"id": "resp_incomplete", "status": "incomplete", "output": []},
            "incomplete_output",
            {"response_status": "incomplete"},
        ),
        (
            {"status": "completed", "output": [{"type": "message", "content": []}]},
            "no_output_text_found",
            {"output_text_found": False, "output_item_count": 1},
        ),
        (
            {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
            "provider_refusal",
            {"content_part_types": ["refusal"]},
        ),
        (
            _provider_response_text("```json\n{\"value\":\"ok\"}\n```"),
            "markdown_wrapped_json",
            {"output_text_prefix_class": "markdown_json_fence", "output_text_found": True},
        ),
        (
            _provider_response_text("Here is the JSON: {\"value\":\"ok\"}"),
            "text_not_valid_json",
            {"output_text_prefix_class": "prose"},
        ),
    ],
)
async def test_openai_provider_classifies_malformed_response_shapes(payload, code, diagnostic_subset):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(LLMProviderError) as caught:
            await OpenAIResponsesProvider(api_key="key", model="gpt-5-mini", client=client).generate(_request())

    assert caught.value.code == code
    assert caught.value.retryable is False
    for key, value in diagnostic_subset.items():
        assert caught.value.diagnostics[key] == value
    assert "raw_output_text" not in caught.value.diagnostics
    assert "output_text_sha256" in caught.value.diagnostics or caught.value.diagnostics["output_text_found"] is False


async def test_openai_provider_preserves_bounded_json_parse_diagnostics_without_text_leakage():
    raw = '{"value":'
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=_provider_response_text(raw)))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(LLMProviderError) as caught:
            await OpenAIResponsesProvider(api_key="key", model="gpt-5-mini", client=client).generate(_request())

    assert caught.value.code == "text_not_valid_json"
    assert caught.value.diagnostics["http_status"] == 200
    assert caught.value.diagnostics["response_object_keys"] == ["model", "output", "status"]
    assert caught.value.diagnostics["output_text_char_length"] == len(raw)
    assert caught.value.diagnostics["output_text_sha256"]
    assert raw not in json.dumps(caught.value.diagnostics)


@pytest.mark.parametrize(
    ("operation", "schema_model"),
    [
        ("editorial_brief", BriefGenerationOutput),
        ("persian_telegram_draft", DraftGenerationOutput),
        ("draft_quality_evaluation", QualityEvaluationOutput),
    ],
)
async def test_openrouter_chat_provider_returns_schema_operation_output(operation, schema_model):
    captured = {}
    output = {
        "editorial_brief": lambda: _brief_output(["rss:title"]),
        "persian_telegram_draft": _draft_output,
        "draft_quality_evaluation": _quality_output,
    }[operation]()

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "gen-safe-response-id",
                "model": "openai/gpt-5-mini-2025-08-07",
                "choices": [{"message": {"role": "assistant", "content": json.dumps(output)}}],
                "usage": {"prompt_tokens": 21, "completion_tokens": 13, "total_tokens": 34},
            },
        )

    request = LLMRequest(
        operation=operation,
        instructions="Use only the bounded evidence.",
        evidence=[{"evidence_id": "rss:title", "text": "خبر"}],
        output_schema=output_schema(schema_model),
        timeout_seconds=10,
        max_output_tokens=900,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OpenRouterChatCompletionsProvider(
            api_key="secret-value",
            model="openai/gpt-5-mini",
            base_url="https://openrouter.ai/api/v1",
            client=client,
        ).generate(request)

    assert result.output == output
    assert result.provider_name == "openrouter"
    assert result.model_name == "openai/gpt-5-mini-2025-08-07"
    assert result.input_tokens == 21
    assert result.output_tokens == 13
    assert result.total_tokens == 34
    assert result.response_id == "gen-safe-response-id"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["payload"] == {
        "model": "openai/gpt-5-mini",
        "messages": [
            {"role": "system", "content": "Use only the bounded evidence."},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "evidence": request.evidence,
                        "output_requirements": {
                            "operation": operation,
                            "schema": request.output_schema,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": f"newscraft_{operation}",
                "strict": True,
                "schema": request.output_schema,
            },
        },
        "max_completion_tokens": 900,
    }
    assert "secret-value" not in json.dumps(captured["payload"])


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"choices": []}, "no_choices"),
        ({"choices": [{}]}, "missing_assistant_message"),
        ({"choices": [{"message": {"role": "assistant", "content": ""}}]}, "empty_assistant_content"),
        (
            {"choices": [{"message": {"role": "assistant", "content": "", "refusal": "not allowed"}}]},
            "provider_refusal",
        ),
        ({"choices": [{"message": {"role": "assistant", "content": "not-json"}}]}, "text_not_valid_json"),
        ({"choices": [{"message": {"role": "assistant", "content": "[]"}}]}, "structured_output_not_object"),
    ],
)
async def test_openrouter_chat_provider_classifies_invalid_response_shapes_without_body_leak(payload, code):
    payload = {"id": "gen-test", "model": "openai/gpt-5-mini", **payload}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(LLMProviderError) as caught:
            await OpenRouterChatCompletionsProvider(
                api_key="secret-value", model="openai/gpt-5-mini", client=client
            ).generate(_request())

    assert caught.value.code == code
    assert caught.value.retryable is False
    assert "not allowed" not in str(caught.value)
    assert "not allowed" not in json.dumps(caught.value.diagnostics)


@pytest.mark.parametrize(
    ("status", "error_type", "code", "retryable"),
    [
        (401, "invalid_api_key", "authentication_failed", False),
        (429, "rate_limit_exceeded", "rate_limited", True),
        (408, "request_timeout", "provider_timeout", True),
        (502, "provider_unavailable", "model_unavailable", True),
        (400, "unsupported_parameter", "unsupported_structured_output", False),
        (402, "insufficient_credits", "provider_http_402", False),
    ],
)
async def test_openrouter_chat_provider_classifies_http_failures(status, error_type, code, retryable):
    response = {"error": {"code": status, "message": "secret-value", "metadata": {"error_type": error_type}}}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=response))
    ) as client:
        with pytest.raises(LLMProviderError) as caught:
            await OpenRouterChatCompletionsProvider(
                api_key="secret-value", model="openai/gpt-5-mini", client=client
            ).generate(_request())

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "secret-value" not in str(caught.value)
    assert "secret-value" not in json.dumps(caught.value.diagnostics)


async def test_openrouter_chat_provider_classifies_network_timeout_and_malformed_envelope():
    def network_failure(request):
        raise httpx.ConnectError("secret-value", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(network_failure)) as client:
        with pytest.raises(LLMProviderError) as network:
            await OpenRouterChatCompletionsProvider(api_key="key", model="model", client=client).generate(_request())
    assert network.value.code == "provider_network_error"
    assert network.value.retryable is True

    def timeout(request):
        raise httpx.ReadTimeout("secret-value", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(LLMProviderError) as timed_out:
            await OpenRouterChatCompletionsProvider(api_key="key", model="model", client=client).generate(_request())
    assert timed_out.value.code == "provider_timeout"
    assert timed_out.value.retryable is True

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"not-json"))
    ) as client:
        with pytest.raises(LLMProviderError) as malformed:
            await OpenRouterChatCompletionsProvider(api_key="key", model="model", client=client).generate(_request())
    assert malformed.value.code == "malformed_provider_response"
    assert malformed.value.retryable is False


def test_brief_schema_rejects_unknown_evidence_reference():
    with pytest.raises(ValueError, match="unknown evidence"):
        BriefGenerationOutput.model_validate(_brief_output(["missing"])).validate_evidence_ids({"rss:title"})


async def test_editorial_brief_schema_failure_reports_validation_path(content_item, extraction_result):
    request = ContentProductionRequest(
        id=uuid4(),
        topic="فناوری",
        platform="telegram",
        language="fa",
        tone="professional",
        audience="مخاطبان فارسی‌زبان",
    )
    run = ContentProductionRun(
        id=extraction_result.production_run_id,
        request_id=request.id,
        content_item_id=content_item.id,
        platform="telegram",
        state="sufficiency_sufficient",
    )
    invalid = _brief_output(["rss:title"])
    del invalid["key_facts"]

    with pytest.raises(LLMProviderError) as caught:
        await EditorialBriefService(FakeSession(), provider=FakeLLMProvider([invalid])).create_brief(
            run=run,
            item=content_item,
            request=request,
            extraction=extraction_result,
        )

    assert caught.value.code == "schema_validation_failed"
    assert caught.value.diagnostics == {"schema_validation_error_paths": ["key_facts"]}


def test_persian_draft_schema_accepts_natural_output_and_rejects_english_or_instruction_leakage():
    valid = DraftGenerationOutput.model_validate(_draft_output())
    valid.validate_content({"rss:title", "rss:excerpt"}, {"https://example.com/story"})

    english = _draft_output()
    english["body"] = "This is an English draft that should never pass the Persian output gate. " * 4
    english["final_text"] = english["headline"] + "\n\n" + english["body"]
    with pytest.raises(ValueError, match="Persian-character ratio"):
        DraftGenerationOutput.model_validate(english).validate_content(
            {"rss:title", "rss:excerpt"}, {"https://example.com/story"}
        )

    leaked = _draft_output()
    leaked["body"] += " هشدار تحریریه: این دستور داخلی است."
    leaked["final_text"] += "\nهشدار تحریریه: این دستور داخلی است."
    with pytest.raises(ValueError, match="internal instruction"):
        DraftGenerationOutput.model_validate(leaked).validate_content(
            {"rss:title", "rss:excerpt"}, {"https://example.com/story"}
        )


def test_draft_schema_rejects_length_bad_refs_urls_and_irrelevant_hashtag():
    payload = _draft_output()
    payload["referenced_evidence_ids"] = ["unknown"]
    payload["source_attribution"] = [{"label": "منبع", "url": "https://unsupported.test"}]
    payload["hashtags"] = ["#هوش_مصنوعی"]
    with pytest.raises(ValueError):
        DraftGenerationOutput.model_validate(payload).validate_content(
            {"rss:title", "rss:excerpt"}, {"https://example.com/story"}
        )


def test_quality_policy_passes_strong_output_and_rejects_unsupported_or_poor_persian():
    strong = QualityEvaluationOutput.model_validate(_quality_output())
    assert quality_gate_status(strong) == "passed"

    unsupported = _quality_output()
    unsupported["unsupported_claims"] = ["ادعای بحرانی بدون منبع"]
    unsupported["recommendation"] = "pass"
    assert quality_gate_status(QualityEvaluationOutput.model_validate(unsupported)) == "failed"

    poor = _quality_output()
    poor["persian_readability"] = 2
    poor["publication_readiness"] = 2
    poor["recommendation"] = "pass"
    assert quality_gate_status(QualityEvaluationOutput.model_validate(poor)) == "failed"


def test_llm_configuration_is_explicit_and_missing_key_fails():
    assert Settings(_env_file=None).llm_provider == "none"
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(_env_file=None, llm_provider="openai", openai_api_key=None)
    configured = Settings(_env_file=None, llm_provider="openai", openai_api_key="test-key")
    assert configured.llm_model == "gpt-5-mini"
    assert "test-key" not in repr(configured)

    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        Settings(_env_file=None, llm_provider="openrouter", openrouter_api_key=None)
    openrouter = Settings(
        _env_file=None,
        llm_provider="openrouter",
        llm_model="openai/gpt-5-mini",
        llm_base_url="https://openrouter.ai/api/v1",
        openrouter_api_key="openrouter-test-key",
    )
    assert "openrouter-test-key" not in repr(openrouter)
    with pytest.raises(ValidationError, match="LLM_BASE_URL"):
        Settings(
            _env_file=None,
            llm_provider="openrouter",
            llm_base_url="not-a-url",
            openrouter_api_key="test-key",
        )


def test_step_8_artifact_metadata_columns_are_registered():
    assert {"evidence_ids_json", "generation_metadata_json"}.issubset(
        Base.metadata.tables["editorial_briefs"].c.keys()
    )
    assert {"evidence_ids_json", "generation_metadata_json"}.issubset(
        Base.metadata.tables["telegram_drafts"].c.keys()
    )
    assert {"rubric_json", "evaluation_metadata_json"}.issubset(
        Base.metadata.tables["draft_quality_reports"].c.keys()
    )


async def test_llm_services_create_grounded_brief_persian_draft_and_variable_quality(
    content_item, extraction_result
):
    request = ContentProductionRequest(
        id=uuid4(),
        topic="فناوری",
        platform="telegram",
        language="fa",
        tone="professional",
        audience="مخاطبان فارسی‌زبان",
    )
    run = ContentProductionRun(
        id=extraction_result.production_run_id,
        request_id=request.id,
        content_item_id=content_item.id,
        platform="telegram",
        state="sufficiency_sufficient",
    )
    draft_output = _draft_output()
    draft_output["source_attribution"] = [{"label": "منبع", "url": content_item.canonical_url}]
    draft_output["final_text"] = draft_output["final_text"].replace(
        "https://example.com/story", content_item.canonical_url
    )
    provider = FakeLLMProvider(
        [
            _brief_output(["rss:title", "extraction:" + str(extraction_result.id)]),
            draft_output,
            _quality_output(),
        ]
    )
    session = FakeSession()

    brief = await EditorialBriefService(session, provider=provider).create_brief(
        run=run,
        item=content_item,
        request=request,
        extraction=extraction_result,
    )
    draft = await TelegramDraftService(session, provider=provider).create_draft(run=run, brief=brief)
    quality = await DraftQualityService(session, provider=provider).check_draft(run=run, draft=draft, brief=brief)

    assert isinstance(brief, EditorialBrief)
    assert isinstance(draft, TelegramDraft)
    assert isinstance(quality, DraftQualityReport)
    assert brief.generation_metadata_json["provider"] == "fake-llm"
    assert draft.generation_metadata_json["input_tokens"] == 100
    assert quality.rubric_json["publication_readiness"] == 4
    assert quality.score != 1
    assert quality.status == "passed"
    assert "هشدار تحریریه" not in draft.draft_text
    assert [call.operation for call in provider.calls] == [
        "editorial_brief",
        "persian_telegram_draft",
        "draft_quality_evaluation",
    ]


def _request() -> LLMRequest:
    return LLMRequest(
        operation="test",
        instructions="Return the schema.",
        evidence=[{"evidence_id": "rss:title", "text": "خبر"}],
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        timeout_seconds=10,
        max_output_tokens=200,
    )


def _provider_response(output: dict, *, usage: dict | None = None) -> dict:
    return {
        "model": "openai/gpt-5-mini",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(output)}]}],
        "usage": usage or {},
    }


def _brief_output(refs):
    return {
        "central_claim": "یک خبر مستند",
        "why_it_matters": "اهمیت خبر برای مخاطب",
        "key_facts": [{"claim": "واقعیت اصلی", "evidence_ids": refs}],
        "important_entities": ["OpenAI"],
        "source_context": [{"context": "زمینه منبع", "evidence_ids": refs}],
        "uncertainties": [],
        "prohibited_claims": ["ادعای بدون منبع"],
        "persian_angle": "روایت روشن و دقیق",
        "suggested_structure": ["تیتر", "خلاصه", "منبع"],
    }


def _draft_output():
    body = (
        "این گزارش بر پایه اطلاعات منتشرشده توضیح می‌دهد که محصول جدید چگونه برای ساخت وب‌سایت‌های سبک "
        "به کار می‌رود. جزئیات موجود هنوز محدود است و نتیجه‌گیری فراتر از منبع انجام نشده است."
    )
    headline = "معرفی روشی تازه برای ساخت وب‌سایت‌های سبک"
    return {
        "headline": headline,
        "body": body,
        "source_attribution": [{"label": "منبع اصلی", "url": "https://example.com/story"}],
        "hashtags": ["#فناوری"],
        "referenced_evidence_ids": ["rss:title", "rss:excerpt"],
        "uncertainty_flags": ["جزئیات محدود است"],
        "final_text": f"{headline}\n\n{body}\n\nمنبع: https://example.com/story\n\n#فناوری",
    }


def _quality_output():
    return {
        "factual_fidelity": 5,
        "evidence_coverage": 4,
        "persian_readability": 5,
        "naturalness": 4,
        "concision": 4,
        "structure": 4,
        "headline_quality": 4,
        "source_attribution": 5,
        "unsupported_claim_risk": 5,
        "publication_readiness": 4,
        "unsupported_claims": [],
        "missing_essential_facts": [],
        "awkward_persian_phrases": [],
        "misleading_certainty": [],
        "irrelevant_content": [],
        "internal_instruction_leakage": [],
        "recommendation": "pass",
    }


class FakeLLMProvider:
    provider_name = "fake-llm"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def generate(self, request):
        self.calls.append(request)
        return LLMResponse(
            output=self.outputs.pop(0),
            provider_name=self.provider_name,
            model_name="fake-persian-model",
            input_tokens=100,
            output_tokens=40,
            total_tokens=140,
            latency_ms=12.5,
        )


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None
