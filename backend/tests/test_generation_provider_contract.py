from __future__ import annotations

import json
from dataclasses import fields
from typing import get_type_hints
from uuid import uuid4

import pytest

from app.generation.providers.base import (
    GenerationProvider,
    GenerationProviderRequest,
    GenerationProviderResult,
    ProviderMessage,
)
from app.generation.providers.fake import DeterministicFakeProvider
from app.generation.providers.registry import (
    DuplicateProviderError,
    ProviderRegistry,
    UnknownProviderError,
    build_default_provider_registry,
)


def _request() -> GenerationProviderRequest:
    return GenerationProviderRequest(
        run_id=uuid4(),
        purpose="rewrite",
        requested_model="requested-v1",
        messages=(ProviderMessage(role="user", content="Rewrite this."),),
        response_schema={"type": "object"},
        metadata={"story_id": "story-1"},
    )


def test_locked_provider_value_objects_have_exact_fields():
    assert tuple(field.name for field in fields(ProviderMessage)) == ("role", "content")
    assert tuple(field.name for field in fields(GenerationProviderRequest)) == (
        "run_id",
        "purpose",
        "requested_model",
        "messages",
        "response_schema",
        "metadata",
    )
    assert tuple(field.name for field in fields(GenerationProviderResult)) == (
        "provider",
        "requested_model",
        "resolved_model",
        "output",
        "raw_text",
        "usage",
        "finish_reason",
    )
    assert get_type_hints(GenerationProvider)["provider_name"] is str


async def test_fake_provider_is_deterministic_and_preserves_locked_result_contract():
    request = _request()
    provider = DeterministicFakeProvider(output={"z": 1, "text": "rewritten"}, resolved_model="fake-v1")

    first = await provider.generate(request)
    second = await provider.generate(request)

    expected_output = {"z": 1, "text": "rewritten"}
    assert first == second == GenerationProviderResult(
        provider="fake",
        requested_model="requested-v1",
        resolved_model="fake-v1",
        output=expected_output,
        raw_text=json.dumps(expected_output, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0},
        finish_reason="stop",
    )


async def test_fake_provider_deep_copies_constructor_input_and_each_result():
    configured_output = {"items": [{"title": "original"}]}
    provider = DeterministicFakeProvider(output=configured_output)
    configured_output["items"][0]["title"] = "mutated by caller"

    first = await provider.generate(_request())
    first.output["items"][0]["title"] = "mutated result"
    second = await provider.generate(_request())

    assert second.output == {"items": [{"title": "original"}]}
    assert second.raw_text == '{"items":[{"title":"original"}]}'


async def test_fake_provider_default_output_is_stable():
    result = await DeterministicFakeProvider().generate(_request())

    assert result.output == {"status": "ok"}
    assert result.raw_text == '{"status":"ok"}'


def test_provider_registry_registers_and_returns_exact_provider():
    provider = DeterministicFakeProvider()
    registry = ProviderRegistry()

    registry.register(provider)

    assert registry.get("fake") is provider
    assert registry.names() == ("fake",)


def test_provider_registry_rejects_duplicate_names():
    registry = ProviderRegistry()
    registry.register(DeterministicFakeProvider())

    with pytest.raises(DuplicateProviderError, match="fake"):
        registry.register(DeterministicFakeProvider())


def test_provider_registry_reports_unknown_provider():
    with pytest.raises(UnknownProviderError, match="openrouter"):
        ProviderRegistry().get("openrouter")


def test_provider_registry_names_are_sorted():
    class ZProvider:
        provider_name = "z-provider"

        async def generate(self, request: GenerationProviderRequest) -> GenerationProviderResult:
            raise NotImplementedError

    registry = ProviderRegistry()
    registry.register(ZProvider())
    registry.register(DeterministicFakeProvider())

    assert registry.names() == ("fake", "z-provider")


def test_default_provider_registry_contains_only_the_fake_provider():
    registry = build_default_provider_registry()

    assert registry.names() == ("fake",)


def test_default_provider_registry_contains_internal_codex_factory():
    registry = build_default_provider_registry()
    assert registry.factory_names() == ("codex",)
