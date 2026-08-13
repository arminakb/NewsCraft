from __future__ import annotations

import base64
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.llm_providers as llm_api
from app.core.config import Settings
from app.core.secrets import EnvironmentSecretResolver
from app.db.session import get_session
from app.generation.models import AIProviderProfile
from app.generation.provider_identity import is_qualified_generation_profile
from app.generation.providers.profiles import ProviderProfileResolver
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.models import WorkflowJob
from app.llm_providers.models import LLMProvider
from app.llm_providers.schemas import LLMProviderCreate, LLMProviderPatch, LLMProviderSettings
from app.llm_providers.service import (
    LLMProviderService,
    ProviderDependencyConflict,
    provider_out,
)
from app.main import app
from app.security.auth import TEST_ADMIN
from app.security.models import EncryptedSecret
from app.security.secret_store import MasterKeyRing


def _encoded(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def _config() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        secret_key_version="v1",
        secret_master_key=_encoded(2),
        security_internal_scopes="jobs:read,jobs:write,providers:read",
    )


async def test_generic_provider_api_accepts_key_once_and_never_returns_it(
    db_session: AsyncSession,
    monkeypatch,
):
    monkeypatch.setattr(llm_api, "settings", _config())
    response = await _request(
        db_session,
        "POST",
        "/llm-providers",
        json={
            "name": "Generic API",
            "base_url": "https://llm.example/v1/",
            "default_model": "model-one",
            "api_key": "api-secret-canary",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["configured"] is True
    assert payload["enabled"] is False
    assert payload["base_url"] == "https://llm.example/v1"
    assert payload["research_capability"] == "unknown"
    assert "api-secret-canary" not in response.text
    assert "secret_id" not in payload

    provider = await db_session.get(LLMProvider, payload["id"])
    shadow = await db_session.get(AIProviderProfile, payload["id"])
    secret = await db_session.get(EncryptedSecret, provider.secret_id)
    assert shadow.id == provider.id
    assert shadow.secret_ref is None
    assert b"api-secret-canary" not in secret.ciphertext

    listed = await _request(db_session, "GET", "/llm-providers")
    assert listed.status_code == 200
    assert "api-secret-canary" not in listed.text


async def test_lifecycle_worker_resolution_rotation_and_dependency_protection(db_session: AsyncSession):
    config = _config()
    observed: list[str] = []

    async def probe(_provider, api_key, _settings):
        observed.append(api_key)

    service = LLMProviderService(
        db_session,
        principal=TEST_ADMIN,
        key_ring=MasterKeyRing.from_settings(config),
        config=config,
        probe=probe,
    )
    provider = await service.create(
        LLMProviderCreate(
            name="Worker Generic",
            base_url="https://llm.example/v1",
            default_model="model-one",
            api_key="first-secret-canary",
        )
    )
    await service.patch(provider, LLMProviderPatch(settings={"timeout_seconds": 45}))
    await service.test_connection(provider)
    await service.enable(provider)
    await db_session.commit()
    await db_session.refresh(provider)

    assert observed == ["first-secret-canary"]
    assert provider_out(provider).generation_ready is True
    assert provider_out(provider).research_ready is True
    assert provider.settings["research_budgets"]["standard"]["max_model_calls"] >= 1

    resolver = ProviderProfileResolver(
        secret_resolver=EnvironmentSecretResolver({}),
        http_client_factory=lambda **_kwargs: httpx.AsyncClient(),
        provider_registry=build_default_provider_registry(),
        application_settings=config,
    )
    shadow = await db_session.get(AIProviderProfile, provider.id)
    resolved = await resolver.resolve_with_session(shadow, None, session=db_session)
    assert resolved.provider_type == "openai_compatible"
    assert resolved.model == "model-one"
    assert resolved.provider.api_key == "first-secret-canary"
    assert is_qualified_generation_profile(shadow, application_settings=config) is True
    assert resolved.max_output_tokens == provider.settings["max_output_tokens"]
    assert resolved.max_attempts is not None
    assert resolved.max_pack_cost_usd is not None
    assert resolved.max_elapsed_seconds is not None
    assert resolved.pricing_input_usd_per_million is not None
    assert resolved.pricing_output_usd_per_million is not None
    await resolved.provider.http_client.aclose()

    first_ciphertext = (await db_session.get(EncryptedSecret, provider.secret_id)).ciphertext
    await service.rotate_secret(provider, "second-secret-canary")
    await db_session.commit()
    await db_session.refresh(provider)
    assert provider.enabled is False
    assert (await db_session.get(EncryptedSecret, provider.secret_id)).ciphertext != first_ciphertext

    job = WorkflowJob(
        job_type="content_pack.generate",
        payload={"generation_provider_profile_id": str(provider.id)},
        idempotency_key=f"provider-dependency:{uuid4()}",
        origin="test",
    )
    db_session.add(job)
    await db_session.commit()
    dependencies = await service.dependencies(provider.id)
    assert dependencies.active_jobs == 1
    with pytest.raises(ProviderDependencyConflict):
        await service.delete(provider)

    await db_session.delete(job)
    await db_session.commit()
    await service.delete(provider)
    await db_session.commit()
    assert await db_session.get(LLMProvider, provider.id) is None
    assert await db_session.scalar(select(EncryptedSecret).where(EncryptedSecret.owner_id == provider.id)) is None


async def test_add_rotate_and_restart_preserve_encrypted_provider_secret(
    session_factory: async_sessionmaker[AsyncSession],
):
    config = _config()
    provider_id = uuid4()
    provider = LLMProvider(
        id=provider_id,
        name="Restart-safe provider",
        protocol="openai_compatible",
        base_url="https://llm.example/v1",
        default_model="model-one",
        enabled=False,
        secret_id=None,
        settings=LLMProviderSettings().model_dump(mode="json"),
        health_status="unchecked",
        generation_capability="unknown",
        research_capability="unknown",
        ownership="operator_managed",
    )
    async with session_factory() as session:
        session.add(provider)
        await session.commit()

        service = LLMProviderService(
            session,
            principal=TEST_ADMIN,
            key_ring=MasterKeyRing.from_settings(config),
            config=config,
        )
        await service.rotate_secret(provider, "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK")
        provider.secret_id = uuid4()  # force provider update failure after secret insertion
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async with session_factory() as session:
        provider = await session.get(LLMProvider, provider_id)
        assert provider is not None
        assert provider.secret_id is None
        assert await session.scalar(
            select(func.count()).select_from(EncryptedSecret).where(EncryptedSecret.owner_id == provider_id)
        ) == 0

        observed: list[str] = []

        async def probe(_provider, api_key, _settings):
            observed.append(api_key)

        service = LLMProviderService(
            session,
            principal=TEST_ADMIN,
            key_ring=MasterKeyRing.from_settings(config),
            config=config,
            probe=probe,
        )
        await service.rotate_secret(provider, "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK")
        await session.commit()
        await session.refresh(provider)
        secret_id = provider.secret_id
        assert secret_id is not None
        stored = await session.get(EncryptedSecret, secret_id)
        assert stored is not None
        assert b"TEST_PROVIDER_API_KEY_MUST_NOT_LEAK" not in stored.ciphertext

        await service.rotate_secret(provider, "TEST_OLD_PROVIDER_KEY_MUST_NOT_LEAK")
        await session.commit()
        assert provider.secret_id == secret_id
        assert await session.scalar(
            select(func.count()).select_from(EncryptedSecret).where(EncryptedSecret.owner_id == provider_id)
        ) == 1

    # A new key ring and session model an API-process restart with the same stable key.
    async with session_factory() as restarted_session:
        restarted_provider = await restarted_session.get(LLMProvider, provider_id)
        assert restarted_provider is not None
        restarted_service = LLMProviderService(
            restarted_session,
            principal=TEST_ADMIN,
            key_ring=MasterKeyRing.from_settings(_config()),
            config=_config(),
            probe=probe,
        )
        await restarted_service.test_connection(restarted_provider)

    assert observed == ["TEST_OLD_PROVIDER_KEY_MUST_NOT_LEAK"]


async def test_fake_provider_api_supports_full_operator_lifecycle(
    db_session: AsyncSession,
    monkeypatch,
):
    monkeypatch.setattr(llm_api, "settings", _config())
    created = await _request(
        db_session,
        "POST",
        "/llm-providers",
        json={
            "name": "API Fake",
            "protocol": "fake",
            "default_model": "fake-v1",
        },
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]

    tested = await _request(db_session, "POST", f"/llm-providers/{provider_id}/test")
    enabled = await _request(db_session, "POST", f"/llm-providers/{provider_id}/enable")
    dependencies = await _request(db_session, "GET", f"/llm-providers/{provider_id}/dependencies")
    disabled = await _request(db_session, "POST", f"/llm-providers/{provider_id}/disable")
    deleted = await _request(db_session, "DELETE", f"/llm-providers/{provider_id}")

    assert tested.json()["generation_capability"] == "ready"
    assert enabled.json()["generation_ready"] is True
    assert dependencies.json()["blocked"] is False
    assert disabled.json()["enabled"] is False
    assert deleted.status_code == 204
    assert await db_session.get(LLMProvider, provider_id) is None


async def _request(session: AsyncSession, method: str, path: str, **kwargs):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.clear()
