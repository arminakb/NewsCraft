from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Any, Never

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from app.core.redaction import redact_secrets
from app.generation.providers.base import (
    GenerationProviderRequest,
    GenerationProviderResult,
)
from app.generation.telegram_schema import TelegramRewriteOutput

logger = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    error_class: str

    def __init__(
        self,
        *,
        code: str,
        message: str,
        diagnostic: dict[str, Any] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.code = code
        self.diagnostic = diagnostic or {}
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class OpenRouterRetryableError(OpenRouterError):
    error_class = "retryable"


class OpenRouterNeedsReviewError(OpenRouterError):
    error_class = "needs_review"


class OpenRouterPermanentError(OpenRouterError):
    error_class = "permanent"


_SAFE_PATH_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def _safe_path(parts: object) -> list[str | int]:
    safe: list[str | int] = []
    if not isinstance(parts, (list, tuple)):
        return safe
    for part in parts:
        if isinstance(part, int) and part >= 0:
            safe.append(part)
        elif isinstance(part, str) and _SAFE_PATH_PART.fullmatch(part):
            safe.append(part)
        else:
            safe.append("<field>")
    return safe[:12]


def _response_diagnostic(
    response: httpx.Response,
    *,
    stage: str,
    error_type: str,
    path: object = (),
    requested_model: str,
) -> dict[str, Any]:
    content = response.content
    request_id = next(
        (
            value
            for name in ("x-request-id", "x-openrouter-request-id")
            if (value := response.headers.get(name)) and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value)
        ),
        None,
    )
    return {
        "stage": stage,
        "error_type": error_type,
        "path": _safe_path(path),
        "response_bytes": len(content),
        "response_sha256": sha256(content).hexdigest(),
        "request_id": request_id,
        "requested_model": (requested_model if _SAFE_IDENTIFIER.fullmatch(requested_model) else "<redacted>"),
    }


class OpenRouterProvider:
    provider_name = "openrouter"

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: int = 60,
        http_referer: str | None = None,
        app_title: str = "NewsCraft",
        invalid_output_quarantine: Any | None = None,
    ) -> None:
        self.http_client = http_client
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.http_referer = http_referer
        self.app_title = app_title
        self.invalid_output_quarantine = invalid_output_quarantine

    @property
    def api_key(self) -> str:
        return self._api_key

    def __repr__(self) -> str:
        return (
            f"OpenRouterProvider(base_url={self.base_url!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, app_title={self.app_title!r})"
        )

    def _required_model(self, request: GenerationProviderRequest) -> str:
        if request.requested_model:
            return request.requested_model
        raise OpenRouterPermanentError(
            code="openrouter_model_missing",
            message="OpenRouter request requires a model",
        )

    def _response_validator(
        self,
        request: GenerationProviderRequest,
    ) -> Draft202012Validator:
        try:
            Draft202012Validator.check_schema(request.response_schema)
        except SchemaError:
            raise OpenRouterPermanentError(
                code="openrouter_schema_invalid",
                message="OpenRouter request schema is invalid",
            ) from None
        return Draft202012Validator(
            request.response_schema,
            format_checker=FormatChecker(),
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": self.app_title,
        }
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        return headers

    def _payload(
        self,
        request: GenerationProviderRequest,
        model: str,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [{"role": message.role, "content": message.content} for message in request.messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.purpose,
                    "strict": True,
                    "schema": request.response_schema,
                },
            },
        }
        max_output_tokens = request.metadata.get("max_output_tokens")
        if max_output_tokens is None:
            return payload
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or max_output_tokens < 1:
            raise OpenRouterPermanentError(
                code="openrouter_max_output_tokens_invalid",
                message="OpenRouter output token allowance is invalid",
            )
        payload["max_tokens"] = max_output_tokens
        return payload

    async def _post(
        self,
        request: GenerationProviderRequest,
        model: str,
    ) -> httpx.Response:
        try:
            response = await self.http_client.post(
                f"{self.base_url}/chat/completions",
                json=self._payload(request, model),
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException, httpx.TransportError:
            raise OpenRouterRetryableError(
                code="openrouter_transport_failed",
                message="OpenRouter transport failed",
            ) from None
        if response.status_code >= 400:
            self._raise_http_error(response, model)
        return response

    async def _invalid_output(
        self,
        response: httpx.Response,
        *,
        model: str,
        stage: str,
        error: Exception,
        path: object = (),
    ) -> Never:
        diagnostic = _response_diagnostic(
            response,
            stage=stage,
            error_type=type(error).__name__,
            path=path,
            requested_model=model,
        )
        if self.invalid_output_quarantine is not None:
            try:
                await self.invalid_output_quarantine.store(
                    response.content,
                    stage=stage,
                    response_sha256=diagnostic["response_sha256"],
                )
            except Exception:
                logger.warning(
                    "invalid provider output quarantine failed stage=%s response_sha256=%s",
                    stage,
                    diagnostic["response_sha256"],
                )
        raise OpenRouterNeedsReviewError(
            code=f"openrouter_output_invalid_{stage}",
            message="OpenRouter returned invalid structured output",
            diagnostic=diagnostic,
        ) from None

    async def _body(
        self,
        response: httpx.Response,
        model: str,
    ) -> Mapping[str, Any]:
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            await self._invalid_output(
                response,
                model=model,
                stage="body_json",
                error=exc,
            )
        if not isinstance(body, Mapping):
            await self._invalid_output(
                response,
                model=model,
                stage="body_json",
                error=TypeError(),
            )
        return body

    async def _choice(
        self,
        response: httpx.Response,
        *,
        model: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        try:
            choices = body["choices"]
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
                raise TypeError
            return choices[0]
        except (KeyError, IndexError, TypeError) as exc:
            await self._invalid_output(
                response,
                model=model,
                stage="choices",
                error=exc,
                path=("choices",),
            )

    async def _output(
        self,
        response: httpx.Response,
        *,
        model: str,
        choice: Mapping[str, Any],
    ) -> Any:
        try:
            message = choice["message"]
            if not isinstance(message, Mapping):
                raise TypeError
            content = message["content"]
        except (KeyError, TypeError) as exc:
            await self._invalid_output(
                response,
                model=model,
                stage="message",
                error=exc,
                path=("choices", 0, "message"),
            )
        if not isinstance(content, (str, dict)):
            await self._invalid_output(
                response,
                model=model,
                stage="content_type",
                error=TypeError(),
                path=("choices", 0, "message", "content"),
            )
        try:
            return json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, ValueError) as exc:
            await self._invalid_output(
                response,
                model=model,
                stage="content_json",
                error=exc,
                path=("choices", 0, "message", "content"),
            )

    async def _validate_schema(
        self,
        response: httpx.Response,
        *,
        model: str,
        validator: Draft202012Validator,
        output: Any,
        stage: str,
    ) -> None:
        try:
            validator.validate(output)
        except JsonSchemaValidationError as exc:
            await self._invalid_output(
                response,
                model=model,
                stage=stage,
                error=exc,
                path=exc.absolute_path,
            )

    async def _telegram_output(
        self,
        response: httpx.Response,
        *,
        model: str,
        request: GenerationProviderRequest,
        output: Any,
        stage: str,
    ) -> Any:
        if request.purpose != "telegram_rewrite":
            return output
        try:
            return TelegramRewriteOutput.model_validate(output).model_dump(mode="json")
        except ValidationError as exc:
            location = exc.errors(include_input=False, include_url=False)[0].get(
                "loc",
                (),
            )
            await self._invalid_output(
                response,
                model=model,
                stage=stage,
                error=exc,
                path=location,
            )

    async def _usage(
        self,
        response: httpx.Response,
        *,
        model: str,
        body: Mapping[str, Any],
        purpose: str,
    ) -> dict[str, Any]:
        try:
            supplied = body.get("usage")
            usage = {} if supplied is None else supplied
            if not isinstance(usage, Mapping):
                raise TypeError
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (input_tokens, output_tokens)
            ):
                raise TypeError
            cost_usd = usage.get("cost", 0)
            if (
                isinstance(cost_usd, bool)
                or not isinstance(cost_usd, (int, float))
                or not math.isfinite(cost_usd)
                or cost_usd < 0
            ):
                raise TypeError
        except (OverflowError, TypeError, ValueError) as exc:
            await self._invalid_output(
                response,
                model=model,
                stage="usage",
                error=exc,
                path=("usage",),
            )
        normalized = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        }
        if purpose == "research_action":
            normalized["usage_supplied"] = (
                supplied is not None and "prompt_tokens" in usage and "completion_tokens" in usage
            )
        return normalized

    async def _finish_reason(
        self,
        response: httpx.Response,
        *,
        model: str,
        choice: Mapping[str, Any],
    ) -> str | None:
        try:
            value = choice.get("finish_reason")
            if value is not None and not isinstance(value, str):
                raise TypeError
            return value
        except TypeError as exc:
            await self._invalid_output(
                response,
                model=model,
                stage="finish_reason",
                error=exc,
                path=("choices", 0, "finish_reason"),
            )

    async def _resolved_model(
        self,
        response: httpx.Response,
        *,
        requested_model: str,
        body: Mapping[str, Any],
    ) -> str:
        try:
            resolved = body.get("model") or requested_model
            if not isinstance(resolved, str):
                raise TypeError
            return resolved
        except TypeError as exc:
            await self._invalid_output(
                response,
                model=requested_model,
                stage="resolved_model",
                error=exc,
                path=("model",),
            )

    async def _safe_result(
        self,
        response: httpx.Response,
        *,
        request: GenerationProviderRequest,
        model: str,
        resolved_model: str,
        output: Any,
        usage: dict[str, Any],
        finish_reason: str | None,
        validator: Draft202012Validator,
    ) -> GenerationProviderResult:
        safe_output = redact_secrets(output, secrets=(self._api_key,))
        await self._validate_schema(
            response,
            model=model,
            validator=validator,
            output=safe_output,
            stage="redaction_schema",
        )
        safe_output = await self._telegram_output(
            response,
            model=model,
            request=request,
            output=safe_output,
            stage="redaction_telegram_schema",
        )
        try:
            safe_raw_text = json.dumps(
                safe_output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            safe_usage = redact_secrets(usage, secrets=(self._api_key,))
            safe_model = str(redact_secrets(resolved_model, secrets=(self._api_key,)))
            safe_finish_reason = redact_secrets(
                finish_reason,
                secrets=(self._api_key,),
            )
            safe_requested_model = str(redact_secrets(model, secrets=(self._api_key,)))
        except (OverflowError, TypeError, ValueError) as exc:
            await self._invalid_output(
                response,
                model=model,
                stage="normalization",
                error=exc,
            )
        if not isinstance(safe_usage, dict):
            await self._invalid_output(
                response,
                model=model,
                stage="normalization",
                error=TypeError(),
            )
        if safe_finish_reason is not None and not isinstance(safe_finish_reason, str):
            await self._invalid_output(
                response,
                model=model,
                stage="normalization",
                error=TypeError(),
            )
        return GenerationProviderResult(
            provider=self.provider_name,
            requested_model=safe_requested_model,
            resolved_model=safe_model,
            output=safe_output,
            raw_text=safe_raw_text,
            usage=safe_usage,
            finish_reason=safe_finish_reason,
        )

    async def generate(
        self,
        request: GenerationProviderRequest,
    ) -> GenerationProviderResult:
        model = self._required_model(request)
        validator = self._response_validator(request)
        response = await self._post(request, model)
        body = await self._body(response, model)
        choice = await self._choice(response, model=model, body=body)
        output = await self._output(response, model=model, choice=choice)
        await self._validate_schema(
            response,
            model=model,
            validator=validator,
            output=output,
            stage="schema",
        )
        output = await self._telegram_output(
            response,
            model=model,
            request=request,
            output=output,
            stage="telegram_schema",
        )
        usage = await self._usage(
            response,
            model=model,
            body=body,
            purpose=request.purpose,
        )
        finish_reason = await self._finish_reason(
            response,
            model=model,
            choice=choice,
        )
        resolved_model = await self._resolved_model(
            response,
            requested_model=model,
            body=body,
        )
        return await self._safe_result(
            response,
            request=request,
            model=model,
            resolved_model=resolved_model,
            output=output,
            usage=usage,
            finish_reason=finish_reason,
            validator=validator,
        )

    def _raise_http_error(
        self,
        response: httpx.Response,
        requested_model: str,
    ) -> None:
        status_code = response.status_code
        error_type: type[OpenRouterError]
        if status_code in {408, 429, 500, 502, 503, 504}:
            error_type = OpenRouterRetryableError
        else:
            error_type = OpenRouterPermanentError
        safe_status = redact_secrets(str(status_code), secrets=(self._api_key,))
        retry_after_seconds = None
        retry_after = response.headers.get("Retry-After")
        if error_type is OpenRouterRetryableError and retry_after:
            try:
                retry_after_seconds = int(retry_after)
            except ValueError:
                try:
                    retry_after_seconds = int(
                        (parsedate_to_datetime(retry_after).astimezone(UTC) - datetime.now(UTC)).total_seconds()
                    )
                except TypeError, ValueError, OverflowError:
                    retry_after_seconds = None
            if retry_after_seconds is not None:
                retry_after_seconds = min(300, max(1, retry_after_seconds))
        raise error_type(
            code=f"openrouter_http_{status_code}",
            message=f"OpenRouter request failed with HTTP {safe_status}",
            diagnostic=_response_diagnostic(
                response,
                stage="http_status",
                error_type=f"HTTP{status_code}",
                requested_model=requested_model,
            ),
            retry_after_seconds=retry_after_seconds,
        )
