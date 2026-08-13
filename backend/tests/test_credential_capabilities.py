from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.automations.models import TelegramSourceConfig
from app.core.config import Settings
from app.core.secrets import EnvironmentSecretResolver
from app.generation.models import AIProviderProfile
from app.jobs.credential_capabilities import (
    CapabilityObservation,
    WorkerCredentialCapabilityObserver,
    project_capability_status,
)
from app.jobs.models import RuntimeHeartbeat
from app.llm_providers.models import LLMProvider
from app.publishing.models import Destination
from app.security.models import EncryptedSecret

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _heartbeat(
    observation: CapabilityObservation,
    *,
    observed_at: datetime = NOW,
    capabilities: list[str] | None = None,
) -> RuntimeHeartbeat:
    return RuntimeHeartbeat(
        component_id="worker-source-generation",
        component_type="worker",
        capabilities=capabilities or ["generation", "source"],
        observed_at=observed_at,
        runtime_metadata={"external_capabilities": [observation.model_dump(mode="json")]},
    )


def _observation(*, available: bool = True) -> CapabilityObservation:
    return CapabilityObservation(
        resource_type="provider",
        resource_id=uuid4(),
        capability="generation",
        state="available" if available else "unavailable",
        failure_code="available" if available else "credential_missing",
    )


def test_worker_observation_projects_fresh_available_and_unavailable_states():
    available = _observation()
    unavailable = _observation(available=False)

    fresh = project_capability_status(
        [_heartbeat(available)],
        resource_type="provider",
        resource_id=available.resource_id,
        capability="generation",
        reference_time=NOW + timedelta(seconds=30),
        ttl_seconds=120,
    )
    missing = project_capability_status(
        [_heartbeat(unavailable)],
        resource_type="provider",
        resource_id=unavailable.resource_id,
        capability="generation",
        reference_time=NOW + timedelta(seconds=30),
        ttl_seconds=120,
    )

    assert fresh.status == "available"
    assert fresh.owner == "worker-source-generation"
    assert fresh.observed_at == NOW
    assert fresh.expires_at == NOW + timedelta(seconds=120)
    assert missing.status == "unavailable"
    assert missing.failure_code == "credential_missing"


def test_worker_observation_projects_stale_missing_and_ownership_mismatch():
    observation = _observation()
    stale = project_capability_status(
        [_heartbeat(observation, observed_at=NOW - timedelta(seconds=120))],
        resource_type="provider",
        resource_id=observation.resource_id,
        capability="generation",
        reference_time=NOW,
        ttl_seconds=120,
    )
    unknown = project_capability_status(
        [],
        resource_type="provider",
        resource_id=observation.resource_id,
        capability="generation",
        reference_time=NOW,
        ttl_seconds=120,
    )
    mismatch = project_capability_status(
        [_heartbeat(observation, capabilities=["publishing"])],
        resource_type="provider",
        resource_id=observation.resource_id,
        capability="generation",
        reference_time=NOW,
        ttl_seconds=120,
    )

    assert stale.status == "stale"
    assert stale.failure_code == "observation_stale"
    assert unknown.status == "unknown"
    assert unknown.failure_code == "observation_missing"
    assert mismatch.status == "unknown"
    assert mismatch.failure_code == "ownership_mismatch"


def test_provider_observation_contains_no_value_or_reference():
    canary = "provider-capability-canary"
    profile = AIProviderProfile(
        id=uuid4(),
        name="OpenRouter",
        provider_type="openrouter",
        default_model="openai/model",
        secret_ref="OPENROUTER_API_KEY",
        settings={},
        enabled=True,
    )
    observer = WorkerCredentialCapabilityObserver(
        SimpleNamespace(),
        secret_resolver=EnvironmentSecretResolver({"OPENROUTER_API_KEY": canary}),
        config=Settings(_env_file=None),
    )

    observations = observer._provider(profile)
    encoded = str([item.model_dump(mode="json") for item in observations])

    assert observations[0].state == "unavailable"
    assert observations[0].failure_code == "generation_profile_unqualified"
    assert canary not in encoded
    assert "OPENROUTER_API_KEY" not in encoded
    assert "secret_ref" not in encoded


async def test_generic_fake_provider_observation_uses_persisted_capabilities():
    profile = LLMProvider(
        id=uuid4(),
        name="Development Fake",
        protocol="fake",
        base_url=None,
        default_model="fake-v1",
        enabled=True,
        secret_id=None,
        settings={},
        health_status="healthy",
        generation_capability="ready",
        research_capability="ready",
    )
    observer = WorkerCredentialCapabilityObserver(
        SimpleNamespace(),
        secret_resolver=EnvironmentSecretResolver({}),
        config=Settings(_env_file=None),
    )

    observations = await observer._generic_provider(profile)

    assert [item.capability for item in observations] == ["generation", "research"]
    assert all(item.state == "available" for item in observations)
    assert all(item.failure_code == "available" for item in observations)


async def test_revoking_provider_credential_does_not_change_source_or_publishing_observations():
    provider = AIProviderProfile(
        id=uuid4(),
        name="OpenRouter",
        provider_type="openrouter",
        default_model="openai/model",
        secret_ref="OPENROUTER_API_KEY",
        settings={},
        enabled=True,
    )
    source = TelegramSourceConfig(
        source_id=uuid4(),
        access_mode="mtproto_user",
        channel_ref="private-source",
        api_id_secret_ref="TELEGRAM_SOURCE_EDITOR_API_ID",
        api_hash_secret_ref="TELEGRAM_SOURCE_EDITOR_API_HASH",
        session_secret_ref="TELEGRAM_SOURCE_EDITOR_SESSION",
    )
    destination = Destination(
        id=uuid4(),
        name="Destination",
        platform="telegram",
        target_ref="@destination",
        secret_ref="TELEGRAM_DESTINATION_NEWS_TOKEN",
        enabled=True,
        health_status="healthy",
        settings={},
    )
    remaining = {
        "TELEGRAM_SOURCE_EDITOR_API_ID": "12345",
        "TELEGRAM_SOURCE_EDITOR_API_HASH": "source-hash-canary",
        "TELEGRAM_SOURCE_EDITOR_SESSION": "source-session-canary",
        "TELEGRAM_DESTINATION_NEWS_TOKEN": "destination-token-canary",
    }
    observer = WorkerCredentialCapabilityObserver(
        SimpleNamespace(),
        secret_resolver=EnvironmentSecretResolver(remaining),
        config=Settings(_env_file=None),
    )

    provider_observations = observer._provider(provider)
    source_observation = observer._source(source)
    destination_observation = await observer._destination(destination)
    encoded = str(
        [
            *(item.model_dump(mode="json") for item in provider_observations),
            source_observation.model_dump(mode="json"),
            destination_observation.model_dump(mode="json"),
        ]
    )

    assert provider_observations[0].state == "unavailable"
    assert source_observation.state == "available"
    assert destination_observation.state == "available"
    assert not any(canary in encoded for canary in remaining.values())
    assert not any(reference in encoded for reference in remaining)


async def test_generic_provider_reports_key_ring_outage_as_invalid_configuration():
    stored = EncryptedSecret(
        id=uuid4(),
        purpose="llm_provider_api_key",
        owner_type="llm_provider",
        owner_id=uuid4(),
        ciphertext=b"0" * 32,
        nonce=b"0" * 12,
        key_version="v0",
    )
    profile = LLMProvider(
        id=uuid4(),
        name="OpenAI Compatible",
        protocol="openai_compatible",
        base_url="https://provider.invalid/v1",
        default_model="model-v1",
        enabled=True,
        secret_id=stored.id,
        settings={},
        health_status="healthy",
        generation_capability="ready",
        research_capability="ready",
    )

    class _KeylessSession:
        async def get(self, model: object, identifier: object) -> EncryptedSecret:
            return stored

    observer = WorkerCredentialCapabilityObserver(
        _KeylessSession(),
        secret_resolver=EnvironmentSecretResolver({}),
        config=Settings(_env_file=None, secret_master_key=None),
    )

    observations = await observer._generic_provider(profile)

    assert all(item.state == "unavailable" for item in observations)
    assert [item.failure_code for item in observations] == [
        "invalid_configuration",
        "invalid_configuration",
    ]
