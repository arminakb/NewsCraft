from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PERSIAN_RE = re.compile(r"[\u0600-\u06ff]")
LETTER_RE = re.compile(r"[A-Za-z\u0600-\u06ff]")
INSTRUCTION_MARKERS = (
    "هشدار تحریریه",
    "دستور داخلی",
    "do not",
    "system prompt",
    "editorial instruction",
)


@dataclass(frozen=True)
class LLMRequest:
    operation: str
    instructions: str
    evidence: list[dict]
    output_schema: dict
    timeout_seconds: float
    max_output_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    output: dict
    provider_name: str
    model_name: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: float
    response_id: str | None = None


class LLMProvider(Protocol):
    provider_name: str

    async def generate(self, request: LLMRequest) -> LLMResponse: ...


class LLMProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool, diagnostics: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.diagnostics = diagnostics or {}


class OpenAIResponsesProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise LLMProviderError("provider_unavailable", retryable=False)
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = client

    async def generate(self, request: LLMRequest) -> LLMResponse:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient()
        started = time.perf_counter()
        try:
            response = await client.post(
                f"{self.base_url}/responses",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "instructions": request.instructions,
                    "input": json.dumps({"evidence": request.evidence}, ensure_ascii=False),
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": f"newscraft_{request.operation}",
                            "schema": request.output_schema,
                            "strict": True,
                        }
                    },
                    "max_output_tokens": request.max_output_tokens,
                    "store": False,
                },
                timeout=request.timeout_seconds,
            )
            if response.status_code == 401:
                raise LLMProviderError("authentication_failed", retryable=False)
            if response.status_code == 429:
                raise LLMProviderError("rate_limited", retryable=True)
            if response.status_code >= 500:
                raise LLMProviderError("provider_unavailable", retryable=True)
            if response.status_code >= 400:
                raise LLMProviderError(f"provider_http_{response.status_code}", retryable=False)
            try:
                payload = response.json()
            except JSONDecodeError as exc:
                raise LLMProviderError("malformed_provider_response", retryable=False) from exc
            diagnostics = _response_diagnostics(payload, http_status=response.status_code)
            _raise_for_response_status(payload, diagnostics)
            text = _response_output_text(payload, diagnostics)
            try:
                output = json.loads(text)
            except (TypeError, JSONDecodeError) as exc:
                code = (
                    "markdown_wrapped_json"
                    if diagnostics.get("output_text_prefix_class") == "markdown_json_fence"
                    else "text_not_valid_json"
                )
                raise LLMProviderError(code, retryable=False, diagnostics=diagnostics) from exc
            if not isinstance(output, dict):
                raise LLMProviderError("structured_output_not_object", retryable=False, diagnostics=diagnostics)
            usage = payload.get("usage") or {}
            return LLMResponse(
                output=output,
                provider_name=self.provider_name,
                model_name=str(payload.get("model") or self.model),
                input_tokens=_optional_int(usage.get("input_tokens", usage.get("prompt_tokens"))),
                output_tokens=_optional_int(usage.get("output_tokens", usage.get("completion_tokens"))),
                total_tokens=_optional_int(usage.get("total_tokens")),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                response_id=_optional_str(payload.get("id")),
            )
        except httpx.TimeoutException as exc:
            raise LLMProviderError("provider_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("provider_network_error", retryable=True) from exc
        finally:
            if owns_client:
                await client.aclose()


class OpenRouterChatCompletionsProvider:
    provider_name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise LLMProviderError("provider_unavailable", retryable=False)
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise LLMProviderError("invalid_provider_base_url", retryable=False)
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = client

    async def generate(self, request: LLMRequest) -> LLMResponse:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient()
        started = time.perf_counter()
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": request.instructions},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "evidence": request.evidence,
                                    "output_requirements": {
                                        "operation": request.operation,
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
                            "name": f"newscraft_{request.operation}",
                            "strict": True,
                            "schema": request.output_schema,
                        },
                    },
                    "max_completion_tokens": request.max_output_tokens,
                },
                timeout=request.timeout_seconds,
            )
            payload = _json_response(response)
            error_type = _openrouter_error_type(payload)
            _raise_for_openrouter_http_status(response.status_code, error_type)
            diagnostics = _openrouter_diagnostics(payload, http_status=response.status_code, error_type=error_type)
            if error_type:
                raise LLMProviderError(
                    _openrouter_embedded_error_code(error_type),
                    retryable=_openrouter_embedded_error_retryable(error_type),
                    diagnostics=diagnostics,
                )
            choices = payload.get("choices")
            if not isinstance(choices, list):
                raise LLMProviderError("malformed_provider_response", retryable=False, diagnostics=diagnostics)
            if not choices:
                raise LLMProviderError("no_choices", retryable=False, diagnostics=diagnostics)
            choice = choices[0]
            if not isinstance(choice, dict):
                raise LLMProviderError("malformed_provider_response", retryable=False, diagnostics=diagnostics)
            choice_error_type = _openrouter_error_type(choice)
            if choice_error_type or choice.get("finish_reason") == "error":
                code = _openrouter_embedded_error_code(choice_error_type)
                raise LLMProviderError(
                    code,
                    retryable=_openrouter_embedded_error_retryable(choice_error_type),
                    diagnostics={**diagnostics, "provider_error_type": choice_error_type},
                )
            message = choice.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise LLMProviderError("missing_assistant_message", retryable=False, diagnostics=diagnostics)
            if message.get("refusal"):
                raise LLMProviderError("provider_refusal", retryable=False, diagnostics=diagnostics)
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise LLMProviderError("empty_assistant_content", retryable=False, diagnostics=diagnostics)
            diagnostics.update(
                {
                    "assistant_content_char_length": len(content),
                    "assistant_content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                }
            )
            try:
                output = json.loads(content)
            except JSONDecodeError as exc:
                raise LLMProviderError("text_not_valid_json", retryable=False, diagnostics=diagnostics) from exc
            if not isinstance(output, dict):
                raise LLMProviderError("structured_output_not_object", retryable=False, diagnostics=diagnostics)
            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
            return LLMResponse(
                output=output,
                provider_name=self.provider_name,
                model_name=str(payload.get("model") or self.model),
                input_tokens=_optional_int(usage.get("prompt_tokens")),
                output_tokens=_optional_int(usage.get("completion_tokens")),
                total_tokens=_optional_int(usage.get("total_tokens")),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                response_id=_optional_str(payload.get("id")),
            )
        except httpx.TimeoutException as exc:
            raise LLMProviderError("provider_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("provider_network_error", retryable=True) from exc
        finally:
            if owns_client:
                await client.aclose()


class GroundedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)


class GroundedContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)


class BriefGenerationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    central_claim: str = Field(min_length=1, max_length=1000)
    why_it_matters: str = Field(min_length=1, max_length=1000)
    key_facts: list[GroundedFact] = Field(min_length=1, max_length=8)
    important_entities: list[str] = Field(max_length=20)
    source_context: list[GroundedContext] = Field(max_length=6)
    uncertainties: list[str] = Field(max_length=10)
    prohibited_claims: list[str] = Field(max_length=10)
    persian_angle: str = Field(min_length=1, max_length=1000)
    suggested_structure: list[str] = Field(min_length=1, max_length=8)

    def validate_evidence_ids(self, evidence_ids: set[str]) -> BriefGenerationOutput:
        referenced = {
            evidence_id
            for row in [*self.key_facts, *self.source_context]
            for evidence_id in row.evidence_ids
        }
        unknown = referenced - evidence_ids
        if unknown:
            raise ValueError(f"unknown evidence references: {sorted(unknown)}")
        return self


class SourceAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2000)


class DraftGenerationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(min_length=8, max_length=180)
    body: str = Field(min_length=120, max_length=3000)
    source_attribution: list[SourceAttribution] = Field(min_length=1, max_length=5)
    hashtags: list[str] = Field(max_length=5)
    referenced_evidence_ids: list[str] = Field(min_length=1, max_length=12)
    uncertainty_flags: list[str] = Field(max_length=8)
    final_text: str = Field(min_length=180, max_length=4096)

    def validate_content(self, evidence_ids: set[str], source_urls: set[str]) -> DraftGenerationOutput:
        if set(self.referenced_evidence_ids) - evidence_ids:
            raise ValueError("draft references unknown evidence")
        if {row.url for row in self.source_attribution} - source_urls:
            raise ValueError("draft contains unsupported source URL")
        letters = LETTER_RE.findall(f"{self.headline} {self.body}")
        ratio = len(PERSIAN_RE.findall(f"{self.headline} {self.body}")) / max(len(letters), 1)
        if ratio < 0.65:
            raise ValueError("Persian-character ratio is below 0.65")
        normalized = self.final_text.casefold()
        if any(marker in normalized for marker in INSTRUCTION_MARKERS):
            raise ValueError("internal instruction leakage detected")
        if any(tag.casefold() == "#هوش_مصنوعی" for tag in self.hashtags) and not _ai_relevant(evidence_ids, self.body):
            raise ValueError("irrelevant hashtag")
        return self


class QualityEvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factual_fidelity: int = Field(ge=1, le=5)
    evidence_coverage: int = Field(ge=1, le=5)
    persian_readability: int = Field(ge=1, le=5)
    naturalness: int = Field(ge=1, le=5)
    concision: int = Field(ge=1, le=5)
    structure: int = Field(ge=1, le=5)
    headline_quality: int = Field(ge=1, le=5)
    source_attribution: int = Field(ge=1, le=5)
    unsupported_claim_risk: int = Field(ge=1, le=5)
    publication_readiness: int = Field(ge=1, le=5)
    unsupported_claims: list[str] = Field(max_length=20)
    missing_essential_facts: list[str] = Field(max_length=20)
    awkward_persian_phrases: list[str] = Field(max_length=20)
    misleading_certainty: list[str] = Field(max_length=20)
    irrelevant_content: list[str] = Field(max_length=20)
    internal_instruction_leakage: list[str] = Field(max_length=20)
    recommendation: Literal["pass", "human_review_required", "reject"]


def quality_gate_status(output: QualityEvaluationOutput) -> str:
    critical = bool(output.unsupported_claims or output.internal_instruction_leakage)
    if (
        critical
        or output.factual_fidelity < 4
        or output.persian_readability < 4
        or output.publication_readiness < 4
        or output.recommendation == "reject"
    ):
        return "failed"
    if output.recommendation == "human_review_required" or output.source_attribution < 4:
        return "revision_requested"
    return "passed"


def response_metadata(response: LLMResponse, operation: str, prompt_hash: str, evidence_ids: list[str]) -> dict:
    metadata = {
        "provider": response.provider_name,
        "model": response.model_name,
        "operation": operation,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "total_tokens": response.total_tokens,
        "latency_ms": response.latency_ms,
        "prompt_hash": prompt_hash,
        "evidence_ids": evidence_ids,
    }
    if response.response_id:
        metadata["response_id"] = response.response_id
    return metadata


def output_schema(model: type[BaseModel]) -> dict:
    return model.model_json_schema()


def schema_validation_diagnostics(exc: Exception) -> dict:
    if not isinstance(exc, ValidationError):
        return {"schema_validation_error_paths": ["__root__"]}
    paths = [".".join(str(part) for part in error["loc"]) or "__root__" for error in exc.errors()]
    return {"schema_validation_error_paths": paths[:20]}


def prompt_hash(instructions: str, evidence: list[dict]) -> str:
    payload = json.dumps(
        {"instructions": instructions, "evidence": evidence},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _raise_for_response_status(payload: dict, diagnostics: dict) -> None:
    status = payload.get("status")
    if status in {"failed", "cancelled"}:
        raise LLMProviderError("provider_response_failed", retryable=False, diagnostics=diagnostics)
    if status == "incomplete":
        raise LLMProviderError("incomplete_output", retryable=False, diagnostics=diagnostics)


def _response_output_text(payload: dict, diagnostics: dict) -> str:
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "refusal":
                raise LLMProviderError("provider_refusal", retryable=False, diagnostics=diagnostics)
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                text = content["text"]
                diagnostics["output_text_found"] = True
                diagnostics["output_text_char_length"] = len(text)
                diagnostics["output_text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
                diagnostics["output_text_prefix_class"] = _text_prefix_class(text)
                return text
    raise LLMProviderError("no_output_text_found", retryable=False, diagnostics=diagnostics)


def _response_diagnostics(payload: dict, *, http_status: int) -> dict:
    output = payload.get("output")
    output_items = output if isinstance(output, list) else []
    content_parts = [
        part
        for item in output_items
        if isinstance(item, dict)
        for part in item.get("content") or []
        if isinstance(part, dict)
    ]
    usage = payload.get("usage") or {}
    error = payload.get("error") or {}
    error_type = error.get("type") if isinstance(error, dict) else None
    return {
        "http_status": http_status,
        "response_id": payload.get("id"),
        "response_status": payload.get("status"),
        "response_object_keys": sorted(payload.keys()),
        "output_item_count": len(output_items),
        "output_item_types": _bounded_list(item.get("type") for item in output_items if isinstance(item, dict)),
        "content_part_types": _bounded_list(part.get("type") for part in content_parts),
        "output_text_found": False,
        "provider_error_type": payload.get("error_type") or error_type,
        "provider_model": payload.get("model"),
        "usage_keys": sorted(usage.keys()) if isinstance(usage, dict) else [],
    }


def _bounded_list(values, limit: int = 20) -> list:
    return list(values)[:limit]


def _text_prefix_class(text: str) -> str:
    stripped = text.lstrip()
    lowered = stripped.casefold()
    if stripped.startswith("{"):
        return "json_object"
    if lowered.startswith("```json"):
        return "markdown_json_fence"
    if lowered.startswith("i can't") or lowered.startswith("i cannot") or "نمی‌توانم" in lowered:
        return "refusal"
    return "prose"


def _optional_int(value) -> int | None:
    return int(value) if value is not None else None


def _optional_str(value) -> str | None:
    return str(value) if value is not None else None


def _json_response(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except JSONDecodeError as exc:
        raise LLMProviderError("malformed_provider_response", retryable=False) from exc
    if not isinstance(payload, dict):
        raise LLMProviderError("malformed_provider_response", retryable=False)
    return payload


def _openrouter_error_type(payload: dict) -> str | None:
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    metadata = error.get("metadata")
    value = metadata.get("error_type") if isinstance(metadata, dict) else None
    return str(value) if value else None


def _raise_for_openrouter_http_status(status: int, error_type: str | None) -> None:
    if status < 400:
        return
    if status == 401:
        raise LLMProviderError("authentication_failed", retryable=False, diagnostics={"http_status": status})
    if status == 408:
        raise LLMProviderError("provider_timeout", retryable=True, diagnostics={"http_status": status})
    if status == 429:
        raise LLMProviderError("rate_limited", retryable=True, diagnostics={"http_status": status})
    if status == 502 or error_type in {"model_not_found", "model_unavailable"}:
        raise LLMProviderError("model_unavailable", retryable=True, diagnostics={"http_status": status})
    if status >= 500:
        raise LLMProviderError("provider_unavailable", retryable=True, diagnostics={"http_status": status})
    if status == 400 and error_type in {"unsupported_parameter", "invalid_response_format"}:
        raise LLMProviderError(
            "unsupported_structured_output",
            retryable=False,
            diagnostics={"http_status": status, "provider_error_type": error_type},
        )
    raise LLMProviderError(f"provider_http_{status}", retryable=False, diagnostics={"http_status": status})


def _openrouter_diagnostics(payload: dict, *, http_status: int, error_type: str | None) -> dict:
    choices = payload.get("choices")
    usage = payload.get("usage")
    return {
        "http_status": http_status,
        "response_id": payload.get("id"),
        "provider_model": payload.get("model"),
        "choice_count": len(choices) if isinstance(choices, list) else None,
        "provider_error_type": error_type,
        "usage_keys": sorted(usage) if isinstance(usage, dict) else [],
    }


def _openrouter_embedded_error_code(error_type: str | None) -> str:
    if error_type in {"rate_limit_exceeded", "rate_limited"}:
        return "rate_limited"
    if error_type in {"request_timeout", "provider_timeout"}:
        return "provider_timeout"
    if error_type in {"model_not_found", "model_unavailable", "provider_unavailable"}:
        return "model_unavailable"
    if error_type in {"unsupported_parameter", "invalid_response_format"}:
        return "unsupported_structured_output"
    return "provider_response_failed"


def _openrouter_embedded_error_retryable(error_type: str | None) -> bool:
    return error_type in {
        "rate_limit_exceeded",
        "rate_limited",
        "request_timeout",
        "provider_timeout",
        "model_unavailable",
        "provider_unavailable",
    }


def _ai_relevant(evidence_ids: set[str], body: str) -> bool:
    text = body.casefold()
    return any(term in text for term in ("هوش مصنوعی", "مدل", "chatgpt", "openai", "codex"))
