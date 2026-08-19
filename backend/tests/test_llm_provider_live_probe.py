from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

import app.llm_providers.service as provider_service
from app.core.config import Settings
from app.generation.models import AIProviderProfile
from app.llm_providers.models import LLMProvider
from app.llm_providers.readiness import provider_readiness
from app.llm_providers.schemas import LLMProviderSettings
from app.security.auth import TEST_ADMIN
from app.security.models import EncryptedSecret
from app.security.secret_store import EncryptedSecretStore, MasterKeyRing


class ProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SessionStub:
    def __init__(self) -> None:
        self.secret: EncryptedSecret | None = None
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, EncryptedSecret):
            self.secret = value

    async def get(self, model, _identifier):
        if model is EncryptedSecret:
            return self.secret
        if model is AIProviderProfile:
            return None
        return None


def _key(byte: int = 2) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def _config() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        secret_key_version="v1",
        secret_master_key=_key(),
        security_internal_scopes="jobs:read,jobs:write,providers:read",
    )


def _provider(*, now: datetime | None = None) -> LLMProvider:
    checked = now or datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    return LLMProvider(
        id=uuid4(),
        name="Live provider",
        protocol="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-5-mini",
        enabled=False,
        secret_id=None,
        settings=LLMProviderSettings().model_dump(mode="json"),
        health_status="unchecked",
        generation_capability="unknown",
        research_capability="unknown",
        failure_code=None,
        failure_message=None,
        last_checked_at=None,
        last_successful_test_at=None,
        last_test_latency_ms=None,
        last_tested_model=None,
        ownership="operator_managed",
        created_at=checked,
        updated_at=checked,
    )


def _secret(session: SessionStub, provider: LLMProvider, config: Settings) -> None:
    stored = EncryptedSecretStore(session, MasterKeyRing.from_settings(config)).create(
        purpose="provider_api_key",
        owner_type="llm_provider",
        owner_id=provider.id,
        value="TEST_PROVIDER_KEY_MUST_NOT_LEAK",
        principal=TEST_ADMIN,
        required_scope="providers:write",
    )
    provider.secret_id = stored.id


@pytest.mark.asyncio
async def test_default_probe_runs_generation_and_research_contracts_without_tools(monkeypatch):
    requests: list[httpx.Request] = []
    generation_output = {"ok": True}
    research_output = {
        "action": "finish",
        "brief": {
            "summary": "",
            "verified_facts": [],
            "disagreements": [],
            "missing_information": [],
            "suggested_angles": [],
            "discovered_evidence_keys": [],
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        output = generation_output if len(requests) == 1 else research_output
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-5-mini",
                "choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
            request=request,
        )

    monkeypatch.setattr(
        provider_service,
        "build_outbound_http_client",
        lambda **_kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    provider = _provider()
    result = await provider_service._default_probe(provider, "TEST_PROVIDER_KEY_MUST_NOT_LEAK", LLMProviderSettings())

    assert len(requests) == 2
    assert all(request.headers["authorization"] == "Bearer TEST_PROVIDER_KEY_MUST_NOT_LEAK" for request in requests)
    payloads = [json.loads(request.content) for request in requests]
    assert payloads[0]["model"] == provider.default_model
    assert payloads[0]["response_format"]["json_schema"]["name"] == "connection_test"
    assert payloads[1]["response_format"]["json_schema"]["name"] == "research_action"
    assert payloads[1]["response_format"]["json_schema"]["schema"]["$defs"]
    assert payloads[1]["messages"][0]["role"] == "system"
    assert "search or fetch" in payloads[1]["messages"][1]["content"]
    assert result.generation.resolved_model == provider.default_model
    assert result.research.resolved_model == provider.default_model
    assert result.latency_ms >= 0
    assert payloads[0]["max_tokens"] == provider_service.GENERATION_PROBE_TOKENS
    assert payloads[1]["max_tokens"] == provider_service.RESEARCH_PROBE_TOKENS


@pytest.mark.asyncio
async def test_probe_reports_truncation_when_reasoning_exhausts_output_budget(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-5-mini",
                "choices": [{"message": {"content": None}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 71, "completion_tokens": 32},
            },
            request=request,
        )

    monkeypatch.setattr(
        provider_service,
        "build_outbound_http_client",
        lambda **_kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    assert provider_service.GENERATION_PROBE_TOKENS >= 1_024
    assert provider_service.RESEARCH_PROBE_TOKENS >= provider_service.GENERATION_PROBE_TOKENS

    provider = _provider()
    with pytest.raises(provider_service.ProviderProbeFailure) as error:
        await provider_service._default_probe(
            provider,
            "TEST_PROVIDER_KEY_MUST_NOT_LEAK",
            LLMProviderSettings(),
        )

    assert error.value.capability == "generation"
    cause = error.value.__cause__
    assert isinstance(cause, Exception)
    assert provider_service.connection_failure_code(cause) == "output_truncated"


@pytest.mark.asyncio
async def test_research_probe_failure_keeps_generation_enablement_available():
    config = _config()
    session = SessionStub()
    provider = _provider()
    _secret(session, provider, config)

    async def probe(_provider, _api_key, _settings):
        raise provider_service.ProviderProbeFailure(
            "research",
            ProviderError("openrouter_output_invalid_schema"),
            generation=provider_service.CapabilityProbeResult(
                requested_model=provider.default_model,
                resolved_model=provider.default_model,
                latency_ms=18,
            ),
            latency_ms=31,
        )

    service = provider_service.LLMProviderService(
        session,
        principal=TEST_ADMIN,
        key_ring=MasterKeyRing.from_settings(config),
        config=config,
        probe=probe,
        clock=lambda: datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
    )

    await service.test_connection(provider)
    await service.enable(provider)

    assert provider.enabled is True
    assert provider.health_status == "degraded"
    assert provider.generation_capability == "ready"
    assert provider.research_capability == "unavailable"
    assert provider.failure_code == "research_invalid_configuration"
    assert provider.failure_message is not None
    assert provider.last_test_latency_ms == 31
    assert provider.last_successful_test_at is not None


@pytest.mark.asyncio
async def test_generation_probe_failure_blocks_enablement_with_safe_reason():
    config = _config()
    session = SessionStub()
    provider = _provider()
    _secret(session, provider, config)

    async def probe(_provider, _api_key, _settings):
        raise provider_service.ProviderProbeFailure(
            "generation",
            ProviderError("openrouter_http_401"),
            latency_ms=11,
        )

    service = provider_service.LLMProviderService(
        session,
        principal=TEST_ADMIN,
        key_ring=MasterKeyRing.from_settings(config),
        config=config,
        probe=probe,
    )

    await service.test_connection(provider)

    with pytest.raises(provider_service.ProviderNotReady) as error:
        await service.enable(provider)

    assert error.value.readiness.code == "generation_unavailable"
    assert error.value.readiness.message == "The provider rejected the API credential."
    assert provider.enabled is False
    assert provider.failure_code == "authentication_failed"
    assert provider.failure_message is not None
    assert "TEST_PROVIDER_KEY_MUST_NOT_LEAK" not in provider.failure_message


@pytest.mark.asyncio
async def test_provider_edge_403_is_not_reported_as_bad_credential():
    config = _config()
    session = SessionStub()
    provider = _provider()
    _secret(session, provider, config)

    async def probe(_provider, _api_key, _settings):
        raise provider_service.ProviderProbeFailure(
            "generation",
            ProviderError("openai_compatible_http_403"),
            latency_ms=14,
        )

    service = provider_service.LLMProviderService(
        session,
        principal=TEST_ADMIN,
        key_ring=MasterKeyRing.from_settings(config),
        config=config,
        probe=probe,
    )

    await service.test_connection(provider)

    assert provider.failure_code == "provider_blocked"
    assert provider.failure_message is not None
    assert "credential" in provider.failure_message
    assert provider.failure_message != "The provider rejected the API credential."
    assert provider.enabled is False


def test_provider_readiness_expires_and_does_not_require_research():
    now = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    provider = _provider(now=now - timedelta(hours=2))
    provider.generation_capability = "ready"
    provider.research_capability = "unavailable"
    provider.health_status = "degraded"
    provider.last_successful_test_at = now - timedelta(hours=2)
    provider.last_tested_model = provider.default_model

    readiness = provider_readiness(provider, now=now, ttl_seconds=3600)

    assert readiness.ready is False
    assert readiness.code == "test_stale"
