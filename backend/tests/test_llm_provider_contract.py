from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.generation.models import AIProviderProfile
from app.generation.provider_identity import is_qualified_generation_profile
from app.llm_providers.models import LLMProvider
from app.llm_providers.schemas import LLMProviderCreate, LLMProviderSettings
from app.llm_providers.service import _legacy_settings, connection_failure_code, provider_out


class ProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("openai_compatible_http_401", "authentication_failed"),
        ("openai_compatible_http_403", "provider_blocked"),
        ("openrouter_http_403", "provider_blocked"),
        ("openrouter_http_404", "model_unavailable"),
        ("openai_compatible_model_missing", "model_unavailable"),
        ("openrouter_transport_failed", "connection_failed"),
        ("openrouter_output_invalid_resolved_model", "invalid_configuration"),
        ("openrouter_output_truncated", "output_truncated"),
        ("openai_compatible_output_truncated", "output_truncated"),
        ("upstream mentioned 401 in prose", "connection_failed"),
        ("not_a_model_error", "connection_failed"),
    ],
)
def test_connection_failure_code_uses_exact_provider_codes(code, expected):
    assert connection_failure_code(ProviderError(code)) == expected


def test_simple_connection_defaults_are_research_ready_and_secret_is_write_only():
    body = LLMProviderCreate.model_validate(
        {
            "name": "Generic",
            "base_url": "https://llm.example/v1",
            "default_model": "model-one",
            "api_key": "secret-canary",
        }
    )

    assert body.enabled is False
    assert body.settings.research_budgets.standard.max_model_calls >= 1
    assert (
        body.settings.research_budgets.deep.max_output_tokens
        > body.settings.research_budgets.standard.max_output_tokens
    )
    assert body.settings.pricing.input_usd_per_million == 0
    assert "secret-canary" not in body.model_dump_json()


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Codex", "protocol": "codex", "default_model": "gpt"},
        {
            "name": "Unsafe",
            "base_url": "http://llm.example/v1",
            "default_model": "model",
            "api_key": "secret",
        },
        {
            "name": "Credentials",
            "base_url": "https://user:password@llm.example/v1",
            "default_model": "model",
            "api_key": "secret",
        },
    ],
)
def test_contract_rejects_codex_and_unsafe_base_urls(payload):
    with pytest.raises(ValidationError):
        LLMProviderCreate.model_validate(payload)


def test_advanced_settings_reject_unknown_fields():
    with pytest.raises(ValidationError):
        LLMProviderSettings.model_validate({"api_key": "never-store-here"})


def test_provider_output_recovers_legacy_null_advanced_settings():
    now = datetime.now(UTC)
    provider = LLMProvider(
        id=uuid4(),
        name="Legacy OpenRouter",
        protocol="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/model",
        enabled=False,
        secret_id=None,
        settings={"pricing": None, "research_budgets": None},
        health_status="unchecked",
        generation_capability="unavailable",
        research_capability="unavailable",
        failure_code="credential_import_required",
        last_checked_at=None,
        ownership="operator_managed",
        created_at=now,
        updated_at=now,
    )

    output = provider_out(provider)

    assert output.settings.pricing.input_usd_per_million == 0
    assert output.settings.research_budgets.standard.max_model_calls >= 1


def test_operator_provider_shadow_profile_is_generation_qualified_with_budgets():
    now = datetime.now(UTC)
    provider = LLMProvider(
        id=uuid4(),
        name="Worker Generic",
        protocol="openai_compatible",
        base_url="https://llm.example/v1",
        default_model="model-one",
        enabled=True,
        secret_id=uuid4(),
        settings=LLMProviderSettings(max_output_tokens=9_000).model_dump(mode="json"),
        health_status="healthy",
        generation_capability="ready",
        research_capability="ready",
        failure_code=None,
        last_checked_at=now,
        ownership="operator_managed",
        created_at=now,
        updated_at=now,
    )

    shadow_settings = _legacy_settings(provider)
    shadow = AIProviderProfile(
        id=provider.id,
        name=provider.name,
        provider_type="openrouter",
        default_model=provider.default_model,
        secret_ref=None,
        settings=shadow_settings,
        enabled=True,
    )

    assert shadow_settings["generation_policy"]["qualification_status"] == "qualified"
    assert shadow_settings["generation_policy"]["max_output_tokens"] == 9_000
    assert is_qualified_generation_profile(shadow) is True
