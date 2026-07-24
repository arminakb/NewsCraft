import pytest
from pydantic import ValidationError

from app.llm_providers.schemas import LLMProviderCreate, LLMProviderSettings


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
