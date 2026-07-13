from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.codex_exec import (
    CodexExecutionError,
    CodexExecutionResult,
    CodexExecutor,
    ProcessRunResult,
)
from app.generation.provider_settings import default_codex_provider_settings
from app.generation.providers.base import GenerationProviderRequest, ProviderMessage
from app.generation.providers.codex import CodexGenerationProvider
from app.generation.providers.openrouter import OpenRouterPermanentError, OpenRouterProvider
from app.publishing.telegram.client import TelegramBotClient, TelegramPermanentError
from app.publishing.telegram.contracts import TelegramPublishOperation
from app.research.base import ResearchRequest
from app.research.codex_adapter import CodexResearchBackend, ResearchBackendError
from app.research.schemas import ResearchBudget
from app.stories.evidence import EvidenceRecord, build_evidence_key

OPENROUTER_CANARY = "openrouter-boundary-canary"
CODEX_CANARY = "codex-boundary-canary"
CODEX_PLAIN_SECRET = "sk-proj-plain-output-canary"
TELEGRAM_CANARY = "123456789:abcdefghijklmnopqrstuvwxyzABCDEFGH"


def _generation_request() -> GenerationProviderRequest:
    return GenerationProviderRequest(
        run_id=uuid4(),
        purpose="boundary_check",
        requested_model="safe-model",
        messages=(ProviderMessage(role="user", content="Return a status"),),
        response_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        },
        metadata={},
    )


def _research_request() -> ResearchRequest:
    evidence_text = "Existing supplied evidence."
    digest = sha256(evidence_text.encode()).hexdigest()
    return ResearchRequest(
        run_id=uuid4(),
        story_id=uuid4(),
        provider_profile_id=uuid4(),
        requested_model="safe-model",
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
                content_text=evidence_text,
                content_sha256=digest,
                source_url="https://input.example/report",
                authors=(),
                published_at=None,
                captured_at=datetime.now(UTC),
            )
        ],
        budget=ResearchBudget(max_model_calls=1),
    )


class _UnusedFetcher:
    async def fetch(self, url: str):  # pragma: no cover - no returned sources
        raise AssertionError(f"unexpected fetch: {url}")


class _LeakyExecutor:
    async def run(self, *args, **kwargs) -> CodexExecutionResult:
        del args, kwargs
        return CodexExecutionResult(
            structured_output={
                "sources": [],
                "brief": {
                    "summary": f"api_key={CODEX_CANARY}",
                    "verified_facts": [],
                    "disagreements": [],
                    "missing_information": [],
                    "suggested_angles": [f"token={CODEX_CANARY}"],
                },
            },
            raw_text=f'{{"api_key":"{CODEX_CANARY}"}}',
            resolved_model=f"safe-model?api_key={CODEX_CANARY}",
            usage={"input_tokens": 1, "output_tokens": 1},
            codex_cli_version="codex-cli",
            exit_code=0,
            elapsed_ms=1,
            sanitized_events=[
                {
                    "type": "codex_process",
                    "status": f"api_key={CODEX_CANARY}",
                    "authorization": f"Bearer {CODEX_CANARY}",
                }
            ],
        )


class _LeakyFailingExecutor:
    async def run(self, *args, **kwargs) -> CodexExecutionResult:
        del args, kwargs
        error = CodexExecutionError(
            f"authentication response api_key={CODEX_CANARY}",
            classification="permanent",
            code="codex_auth_failed",
        )
        error.metadata = {
            "provider_message": f"token={CODEX_CANARY}",
            "authorization": f"Bearer {CODEX_CANARY}",
        }
        raise error


class _MalformedFailingExecutor:
    async def run(self, *args, **kwargs) -> CodexExecutionResult:
        del args, kwargs
        raise CodexExecutionError(
            "malformed classified failure",
            classification="retry-without-review",  # type: ignore[arg-type]
            code=f"api_key={CODEX_CANARY}",
        )


def _real_executor_with_output(
    structured_output: dict[str, object],
) -> CodexExecutor:
    async def runner(**kwargs) -> ProcessRunResult:
        del kwargs
        return ProcessRunResult(
            exit_code=0,
            stdout=('{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'),
            stderr="",
            elapsed_ms=1,
            structured_output=structured_output,
            token_usage={"input_tokens": 1, "output_tokens": 1},
            codex_cli_version="codex-cli",
        )

    return CodexExecutor(
        process_runner=runner,
        executable="codex",
        environment={"OPENAI_API_KEY": CODEX_PLAIN_SECRET},
    )


def _research_output_with_plain_secret() -> dict[str, object]:
    return {
        "sources": [],
        "brief": {
            "summary": CODEX_PLAIN_SECRET,
            "verified_facts": [],
            "disagreements": [],
            "missing_information": [],
            "suggested_angles": [CODEX_PLAIN_SECRET],
        },
    }


async def test_openrouter_auth_failure_ignores_raw_response_body_and_credentials():
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": f"Bearer {OPENROUTER_CANARY}",
                    "debug": {"api_key": OPENROUTER_CANARY},
                }
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        provider = OpenRouterProvider(http_client=http, api_key=OPENROUTER_CANARY)
        with pytest.raises(OpenRouterPermanentError) as caught:
            await provider.generate(_generation_request())

    exposed = f"{caught.value!s} {caught.value!r} {caught.value.__dict__!r}"
    assert OPENROUTER_CANARY not in exposed
    assert "debug" not in exposed
    assert caught.value.code == "openrouter_http_401"
    assert str(caught.value) == "OpenRouter request failed with HTTP 401"


async def test_codex_adapter_resanitizes_injected_executor_success_output():
    result = await CodexResearchBackend(
        executor=_LeakyExecutor(),
        fetcher=_UnusedFetcher(),
    ).research(_research_request())

    serialized = result.model_dump_json()
    assert CODEX_CANARY not in serialized
    assert "[REDACTED]" in serialized
    assert result.usage.input_tokens == 1
    assert result.usage.output_tokens == 1


async def test_codex_adapter_resanitizes_and_unchains_injected_executor_errors():
    with pytest.raises(ResearchBackendError) as caught:
        await CodexResearchBackend(
            executor=_LeakyFailingExecutor(),
            fetcher=_UnusedFetcher(),
        ).research(_research_request())

    exposed = f"{caught.value!s} {caught.value.metadata!r}"
    assert CODEX_CANARY not in exposed
    assert "[REDACTED]" in exposed
    assert caught.value.classification == "permanent"
    assert caught.value.code == "codex_auth_failed"
    assert caught.value.__suppress_context__ is True


async def test_codex_executor_sanitizes_known_literals_and_returns_canonical_raw_json():
    output = {"status": CODEX_PLAIN_SECRET}
    execution = await _real_executor_with_output(output).run(
        "Return a status",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        },
        ResearchBudget(max_model_calls=1),
        resolved_model=CODEX_PLAIN_SECRET,
        allow_web=False,
    )

    assert CODEX_PLAIN_SECRET not in repr(execution)
    assert execution.structured_output == {"status": "[REDACTED]"}
    assert execution.resolved_model == "[REDACTED]"
    assert execution.raw_text == '{"status":"[REDACTED]"}'
    assert json.loads(execution.raw_text) == execution.structured_output


async def test_codex_executor_revalidates_output_after_literal_redaction():
    executor = _real_executor_with_output({"status": CODEX_PLAIN_SECRET})
    with pytest.raises(CodexExecutionError) as caught:
        await executor.run(
            "Return the exact status",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["status"],
                "properties": {"status": {"const": CODEX_PLAIN_SECRET}},
            },
            ResearchBudget(max_model_calls=1),
            resolved_model="safe-model",
            allow_web=False,
        )

    assert caught.value.code == "codex_output_invalid"
    assert CODEX_PLAIN_SECRET not in str(caught.value)
    assert CODEX_PLAIN_SECRET not in repr(caught.value.metadata)


async def test_plain_codex_auth_literal_cannot_escape_research_result():
    result = await CodexResearchBackend(
        executor=_real_executor_with_output(_research_output_with_plain_secret()),
        fetcher=_UnusedFetcher(),
    ).research(_research_request())

    serialized = result.model_dump_json()
    assert CODEX_PLAIN_SECRET not in serialized
    assert result.output.brief.summary == "[REDACTED]"
    assert result.output.brief.suggested_angles == ["[REDACTED]"]


async def test_plain_codex_auth_literal_cannot_escape_generation_contract():
    profile_id = uuid4()
    profile = SimpleNamespace(
        id=profile_id,
        provider_type="codex",
        default_model="safe-model",
        secret_ref=None,
        enabled=True,
        settings=default_codex_provider_settings().model_dump(mode="json"),
    )
    provider = CodexGenerationProvider(
        executor=_real_executor_with_output({"status": CODEX_PLAIN_SECRET}),
        profile=profile,
    )
    result = await provider.generate(
        replace(
            _generation_request(),
            metadata={"provider_profile_id": str(profile_id)},
        )
    )

    exposed = json.dumps(
        {
            "output": result.output,
            "raw_text": result.raw_text,
            "resolved_model": result.resolved_model,
            "usage": result.usage,
        },
        sort_keys=True,
    )
    assert CODEX_PLAIN_SECRET not in exposed
    assert result.output == {"status": "[REDACTED]"}
    assert json.loads(result.raw_text) == result.output


async def test_codex_adapter_normalizes_canary_code_and_invalid_classification():
    with pytest.raises(ResearchBackendError) as caught:
        await CodexResearchBackend(
            executor=_MalformedFailingExecutor(),
            fetcher=_UnusedFetcher(),
        ).research(_research_request())

    assert CODEX_CANARY not in repr(caught.value.__dict__)
    assert caught.value.code == "codex_execution_failed"
    assert caught.value.classification == "needs_review"
    assert caught.value.__suppress_context__ is True


async def test_telegram_failure_metadata_is_token_safe_and_body_narrowed():
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "description": f"bot_token={TELEGRAM_CANARY}",
                "parameters": {
                    "authorization": f"Bearer {TELEGRAM_CANARY}",
                    "retry_after": 3,
                },
                "raw_debug_body": TELEGRAM_CANARY,
            },
            request=request,
        )

    operation = TelegramPublishOperation(
        0,
        "operation-0",
        "sendMessage",
        {"chat_id": "@target", "text": "safe"},
        (),
        "a" * 64,
        (),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(TelegramPermanentError) as caught:
            await TelegramBotClient(http).execute(operation, TELEGRAM_CANARY)

    exposed = json.dumps(caught.value.metadata, sort_keys=True) + str(caught.value)
    assert TELEGRAM_CANARY not in exposed
    assert "raw_debug_body" not in exposed
    assert caught.value.metadata["http_status"] == 400
    assert caught.value.metadata["parameters"]["retry_after"] == 3
    assert "[REDACTED]" in exposed
