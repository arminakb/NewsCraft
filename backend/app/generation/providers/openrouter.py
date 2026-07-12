from __future__ import annotations

import json
import math
from collections.abc import Mapping

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from app.core.redaction import redact_secrets
from app.generation.providers.base import GenerationProviderRequest, GenerationProviderResult
from app.generation.telegram_schema import TelegramRewriteOutput


class OpenRouterError(RuntimeError):
    error_class: str

    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class OpenRouterRetryableError(OpenRouterError):
    error_class = "retryable"


class OpenRouterNeedsReviewError(OpenRouterError):
    error_class = "needs_review"


class OpenRouterPermanentError(OpenRouterError):
    error_class = "permanent"


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
    ) -> None:
        self.http_client = http_client
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.http_referer = http_referer
        self.app_title = app_title

    @property
    def api_key(self) -> str:
        return self._api_key

    def __repr__(self) -> str:
        return (
            f"OpenRouterProvider(base_url={self.base_url!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, app_title={self.app_title!r})"
        )

    async def generate(self, request: GenerationProviderRequest) -> GenerationProviderResult:
        if not request.requested_model:
            raise OpenRouterPermanentError(
                code="openrouter_model_missing",
                message="OpenRouter request requires a model",
            )
        try:
            Draft202012Validator.check_schema(request.response_schema)
        except SchemaError:
            raise OpenRouterPermanentError(
                code="openrouter_schema_invalid",
                message="OpenRouter request schema is invalid",
            ) from None
        validator = Draft202012Validator(
            request.response_schema,
            format_checker=FormatChecker(),
        )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": self.app_title,
        }
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        payload = {
            "model": request.requested_model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.purpose,
                    "strict": True,
                    "schema": request.response_schema,
                },
            },
        }
        try:
            response = await self.http_client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            raise OpenRouterRetryableError(
                code="openrouter_transport_failed",
                message="OpenRouter transport failed",
            ) from None
        if response.status_code >= 400:
            self._raise_http_error(response.status_code)
        try:
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"]["content"]
            if isinstance(content, str):
                output = json.loads(content)
            elif isinstance(content, dict):
                output = content
            else:
                raise TypeError
            validator.validate(output)
            if request.purpose == "telegram_rewrite":
                safe_output = TelegramRewriteOutput.model_validate(output).model_dump(mode="json")
            else:
                safe_output = output
            supplied_usage = body.get("usage")
            usage = {} if supplied_usage is None else supplied_usage
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
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None and not isinstance(finish_reason, str):
                raise TypeError
            normalized_usage = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
            }
            resolved_model = body.get("model") or request.requested_model
            if not isinstance(resolved_model, str):
                raise TypeError
            safe_output = redact_secrets(safe_output, secrets=(self._api_key,))
            validator.validate(safe_output)
            if request.purpose == "telegram_rewrite":
                safe_output = TelegramRewriteOutput.model_validate(safe_output).model_dump(mode="json")
            safe_raw_text = json.dumps(
                safe_output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            safe_usage = redact_secrets(normalized_usage, secrets=(self._api_key,))
            safe_model = str(redact_secrets(resolved_model, secrets=(self._api_key,)))
            safe_finish_reason = redact_secrets(
                finish_reason,
                secrets=(self._api_key,),
            )
            safe_requested_model = str(
                redact_secrets(request.requested_model, secrets=(self._api_key,))
            )
        except (
            JsonSchemaValidationError,
            OverflowError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            ValidationError,
        ):
            raise OpenRouterNeedsReviewError(
                code="openrouter_output_invalid",
                message="OpenRouter returned invalid structured output",
            ) from None
        return GenerationProviderResult(
            provider=self.provider_name,
            requested_model=safe_requested_model,
            resolved_model=safe_model,
            output=safe_output,
            raw_text=safe_raw_text,
            usage=safe_usage,
            finish_reason=safe_finish_reason,
        )

    def _raise_http_error(self, status_code: int) -> None:
        error_type: type[OpenRouterError]
        if status_code in {408, 429} or status_code >= 500:
            error_type = OpenRouterRetryableError
        else:
            error_type = OpenRouterPermanentError
        safe_status = redact_secrets(str(status_code), secrets=(self._api_key,))
        raise error_type(
            code=f"openrouter_http_{status_code}",
            message=f"OpenRouter request failed with HTTP {safe_status}",
        )
