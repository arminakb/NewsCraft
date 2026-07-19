import json
from uuid import uuid4

import httpx
import pytest

from app.generation.default_prompts import manual_generation_provider_schema
from app.generation.platform_schemas import InstagramVariantPayload
from app.generation.providers.base import GenerationProviderRequest, ProviderMessage
from app.generation.providers.openrouter import (
    OpenRouterNeedsReviewError,
    OpenRouterPermanentError,
    OpenRouterProvider,
    OpenRouterRetryableError,
)
from app.generation.telegram_schema import TelegramRewriteOutput


def provider_request() -> GenerationProviderRequest:
    return GenerationProviderRequest(
        run_id=uuid4(),
        purpose="telegram_rewrite",
        requested_model="openai/gpt-5-mini",
        messages=(ProviderMessage(role="user", content="Rewrite"),),
        response_schema=TelegramRewriteOutput.model_json_schema(),
        metadata={},
    )


def provider_with_response(payload, *, status=200):
    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return OpenRouterProvider(http_client=client, api_key="test-key"), requests, client


async def test_openrouter_posts_json_schema_and_returns_normalized_result():
    provider, requests, client = provider_with_response(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"body":"بازنویسی","parse_mode":"HTML","buttons":[]}'
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            "model": "openai/gpt-5-mini",
        }
    )
    try:
        result = await provider.generate(provider_request())
    finally:
        await client.aclose()

    sent = json.loads(requests[0].content)
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert requests[0].headers["authorization"] == "Bearer test-key"
    assert result.output["body"] == "بازنویسی"
    assert result.resolved_model == "openai/gpt-5-mini"
    assert result.usage == {"input_tokens": 10, "output_tokens": 4, "cost_usd": 0}


async def test_openrouter_accepts_object_content_and_maps_transport_failure_retryably():
    provider, _, client = provider_with_response(
        {
            "choices": [
                {
                    "message": {
                        "content": {"body": "Object", "parse_mode": "HTML", "buttons": []}
                    },
                    "finish_reason": "stop",
                }
            ],
            "model": "model",
        }
    )
    try:
        assert (await provider.generate(provider_request())).output["body"] == "Object"
    finally:
        await client.aclose()

    async def fail(request):
        raise httpx.ConnectError("Bearer test-key", request=request)

    failing_client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    failing = OpenRouterProvider(http_client=failing_client, api_key="test-key")
    try:
        with pytest.raises(OpenRouterRetryableError) as caught:
            await failing.generate(provider_request())
    finally:
        await failing_client.aclose()
    assert "test-key" not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, OpenRouterPermanentError),
        (403, OpenRouterPermanentError),
        (408, OpenRouterRetryableError),
        (429, OpenRouterRetryableError),
        (500, OpenRouterRetryableError),
    ],
)
async def test_openrouter_maps_http_failures_without_leaking_authorization(status, error_type):
    provider, _, client = provider_with_response(
        {"error": {"message": "Bearer test-key upstream"}}, status=status
    )
    try:
        with pytest.raises(error_type) as caught:
            await provider.generate(provider_request())
    finally:
        await client.aclose()
    assert "test-key" not in str(caught.value)
    assert "Bearer" not in str(caught.value)


@pytest.mark.parametrize(
    "content",
    ["not-json", '{"body":"<script>x</script>","parse_mode":"HTML","buttons":[]}'],
)
async def test_openrouter_maps_invalid_json_or_schema_to_needs_review(content):
    provider, _, client = provider_with_response(
        {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "model": "model",
        }
    )
    try:
        with pytest.raises(OpenRouterNeedsReviewError):
            await provider.generate(provider_request())
    finally:
        await client.aclose()


async def test_openrouter_honors_nontelegram_schema_and_classifies_malformed_usage():
    provider, _, client = provider_with_response(
        {
            "choices": [
                {"message": {"content": '{"status":"ok"}'}, "finish_reason": "stop"}
            ],
            "usage": {},
            "model": "model",
        }
    )
    request = provider_request()
    request = GenerationProviderRequest(
        run_id=request.run_id,
        purpose="generic_status",
        requested_model=request.requested_model,
        messages=request.messages,
        response_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        },
        metadata={},
    )
    try:
        assert (await provider.generate(request)).output == {"status": "ok"}
    finally:
        await client.aclose()

    malformed, _, malformed_client = provider_with_response(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"body":"ok","parse_mode":"HTML","buttons":[]}'
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": "invalid"},
            "model": "model",
        }
    )
    try:
        with pytest.raises(OpenRouterNeedsReviewError):
            await malformed.generate(provider_request())
    finally:
        await malformed_client.aclose()


async def test_openrouter_provider_boundary_accepts_reviewable_manual_platform_overage():
    output = {
        "hook": "x" * 181,
        "caption": "Grounded",
        "cta": "Read",
        "hashtags": [],
        "alt_text": "Grounded",
        "carousel": [],
        "citations": [
            {
                "evidence_key": "evidence:one",
                "evidence_snapshot_id": str(uuid4()),
                "source_url": "https://example.com/report",
                "locator": "chars:0-8",
                "excerpt_sha256": "a" * 64,
            }
        ],
        "manual_checklist": ["Verify"],
    }
    provider, requests, client = provider_with_response(
        {
            "choices": [
                {"message": {"content": json.dumps(output)}, "finish_reason": "stop"}
            ],
            "model": "model",
        }
    )
    base = provider_request()
    schema = manual_generation_provider_schema(InstagramVariantPayload)
    request = GenerationProviderRequest(
        run_id=base.run_id,
        purpose="instagram_pack",
        requested_model=base.requested_model,
        messages=base.messages,
        response_schema=schema,
        metadata={},
    )
    try:
        result = await provider.generate(request)
    finally:
        await client.aclose()

    sent = json.loads(requests[0].content)
    assert sent["response_format"]["json_schema"]["schema"] == schema
    assert result.output["hook"] == "x" * 181


async def test_openrouter_uses_draft_202012_formats_and_redacts_success_fields():
    invalid, _, invalid_client = provider_with_response(
        {
            "choices": [
                {
                    "message": {"content": '{"email":"not-an-email","extra":true}'},
                    "finish_reason": "stop",
                }
            ],
            "model": "model",
        }
    )
    request = provider_request()
    format_request = GenerationProviderRequest(
        run_id=request.run_id,
        purpose="format_check",
        requested_model=request.requested_model,
        messages=request.messages,
        response_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"email": {"type": "string", "format": "email"}},
            "required": ["email"],
            "unevaluatedProperties": False,
        },
        metadata={},
    )
    try:
        with pytest.raises(OpenRouterNeedsReviewError):
            await invalid.generate(format_request)
    finally:
        await invalid_client.aclose()

    safe, _, safe_client = provider_with_response(
        {
            "choices": [
                {
                    "message": {"content": '{"value":"test-key"}'},
                    "finish_reason": "test-key",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 1.25},
            "model": "test-key",
        }
    )
    secret_request = GenerationProviderRequest(
        run_id=request.run_id,
        purpose="secret_echo",
        requested_model=request.requested_model,
        messages=request.messages,
        response_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        metadata={},
    )
    try:
        result = await safe.generate(secret_request)
    finally:
        await safe_client.aclose()
    for value in (
        result.output,
        result.raw_text,
        result.resolved_model,
        result.usage,
        result.finish_reason,
    ):
        assert "test-key" not in str(value)


async def test_openrouter_rejects_invalid_application_schema_before_http():
    provider, requests, client = provider_with_response({})
    request = provider_request()
    invalid = GenerationProviderRequest(
        run_id=request.run_id,
        purpose=request.purpose,
        requested_model=request.requested_model,
        messages=request.messages,
        response_schema={"type": "unsupported-json-type"},
        metadata={},
    )
    try:
        with pytest.raises(OpenRouterPermanentError):
            await provider.generate(invalid)
    finally:
        await client.aclose()
    assert requests == []


async def test_openrouter_revalidates_redacted_output_against_exact_schema():
    provider, _, client = provider_with_response(
        {
            "choices": [
                {
                    "message": {"content": '{"value":"test-key"}'},
                    "finish_reason": "stop",
                }
            ],
            "model": "model",
        }
    )
    request = provider_request()
    exact = GenerationProviderRequest(
        run_id=request.run_id,
        purpose="exact_secret_echo",
        requested_model=request.requested_model,
        messages=request.messages,
        response_schema={
            "type": "object",
            "properties": {"value": {"const": "test-key"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        metadata={},
    )
    try:
        with pytest.raises(OpenRouterNeedsReviewError):
            await provider.generate(exact)
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    ("payload", "stage"),
    [
        ({}, "choices"),
        ({"choices": [{}]}, "message"),
        ({"choices": [{"message": {"content": []}}]}, "content_type"),
        ({"choices": [{"message": {"content": "private-invalid-value"}}]}, "content_json"),
        (
            {"choices": [{"message": {"content": {"parse_mode": "HTML", "buttons": []}}}]},
            "schema",
        ),
        (
            {
                "choices": [
                    {
                        "message": {
                            "content": {"body": "<script>x</script>", "parse_mode": "HTML", "buttons": []}
                        }
                    }
                ]
            },
            "telegram_schema",
        ),
        (
            {
                "choices": [
                    {"message": {"content": {"body": "ok", "parse_mode": "HTML", "buttons": []}}}
                ],
                "usage": {"prompt_tokens": "private-invalid-value"},
            },
            "usage",
        ),
        (
            {
                "choices": [
                    {
                        "message": {"content": {"body": "ok", "parse_mode": "HTML", "buttons": []}},
                        "finish_reason": {"private": "value"},
                    }
                ]
            },
            "finish_reason",
        ),
        (
            {
                "choices": [
                    {"message": {"content": {"body": "ok", "parse_mode": "HTML", "buttons": []}}}
                ],
                "model": {"private": "value"},
            },
            "resolved_model",
        ),
    ],
)
async def test_openrouter_diagnostics_identify_safe_failure_stage_without_raw_values(payload, stage):
    provider, _, client = provider_with_response(payload)
    try:
        with pytest.raises(OpenRouterNeedsReviewError) as caught:
            await provider.generate(provider_request())
    finally:
        await client.aclose()

    diagnostic = caught.value.diagnostic
    assert caught.value.code == f"openrouter_output_invalid_{stage}"
    assert diagnostic["stage"] == stage
    assert diagnostic["response_bytes"] > 0
    assert len(diagnostic["response_sha256"]) == 64
    assert diagnostic["requested_model"] == "openai/gpt-5-mini"
    assert "private-invalid-value" not in str(diagnostic)
    assert "test-key" not in str(diagnostic)


async def test_openrouter_diagnostic_handles_non_json_body_and_safe_request_id():
    async def respond(request):
        return httpx.Response(
            200,
            content=b"private-invalid-value",
            headers={"X-Request-ID": "request-123"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = OpenRouterProvider(http_client=client, api_key="test-key")
    try:
        with pytest.raises(OpenRouterNeedsReviewError) as caught:
            await provider.generate(provider_request())
    finally:
        await client.aclose()
    assert caught.value.diagnostic["stage"] == "body_json"
    assert caught.value.diagnostic["request_id"] == "request-123"
    assert "private-invalid-value" not in str(caught.value.diagnostic)


async def test_openrouter_honors_bounded_retry_after_without_exposing_response():
    async def respond(request):
        return httpx.Response(
            429,
            json={"error": "private-invalid-value"},
            headers={"Retry-After": "9999"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = OpenRouterProvider(http_client=client, api_key="test-key")
    try:
        with pytest.raises(OpenRouterRetryableError) as caught:
            await provider.generate(provider_request())
    finally:
        await client.aclose()
    assert caught.value.retry_after_seconds == 300
    assert caught.value.diagnostic["stage"] == "http_status"
    assert "private-invalid-value" not in str(caught.value.diagnostic)


async def test_openrouter_optional_quarantine_receives_invalid_bytes_only_when_configured():
    stored = []

    class Quarantine:
        async def store(self, content, **metadata):
            stored.append((content, metadata))

    async def respond(request):
        return httpx.Response(200, content=b"invalid-private-output", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = OpenRouterProvider(
        http_client=client,
        api_key="test-key",
        invalid_output_quarantine=Quarantine(),
    )
    try:
        with pytest.raises(OpenRouterNeedsReviewError) as caught:
            await provider.generate(provider_request())
    finally:
        await client.aclose()

    assert stored[0][0] == b"invalid-private-output"
    assert stored[0][1]["stage"] == "body_json"
    assert len(stored[0][1]["response_sha256"]) == 64
    assert "invalid-private-output" not in str(caught.value.diagnostic)


@pytest.mark.parametrize(
    ("usage", "finish_reason"),
    [
        ({"prompt_tokens": 1, "completion_tokens": 1, "cost": "1.25"}, "stop"),
        ({"prompt_tokens": 1, "completion_tokens": 1, "cost": True}, "stop"),
        ({"prompt_tokens": 1, "completion_tokens": 1, "cost": 1.25}, 123),
    ],
)
async def test_openrouter_rejects_malformed_cost_or_finish_metadata(usage, finish_reason):
    provider, _, client = provider_with_response(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"body":"ok","parse_mode":"HTML","buttons":[]}'
                    },
                    "finish_reason": finish_reason,
                }
            ],
            "usage": usage,
            "model": "model",
        }
    )
    try:
        with pytest.raises(OpenRouterNeedsReviewError):
            await provider.generate(provider_request())
    finally:
        await client.aclose()


@pytest.mark.parametrize("usage", [[], "", False, 0])
async def test_openrouter_rejects_falsey_supplied_nonmapping_usage(usage):
    provider, _, client = provider_with_response(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"body":"ok","parse_mode":"HTML","buttons":[]}'
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
            "model": "model",
        }
    )
    try:
        with pytest.raises(OpenRouterNeedsReviewError):
            await provider.generate(provider_request())
    finally:
        await client.aclose()


async def test_openrouter_classifies_enormous_integer_cost_as_needs_review():
    provider, _, client = provider_with_response(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"body":"ok","parse_mode":"HTML","buttons":[]}'
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "cost": 10**1_000,
            },
            "model": "model",
        }
    )
    try:
        with pytest.raises(OpenRouterNeedsReviewError):
            await provider.generate(provider_request())
    finally:
        await client.aclose()
