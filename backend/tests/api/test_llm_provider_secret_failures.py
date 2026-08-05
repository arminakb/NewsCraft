from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError, ProgrammingError

import app.api.llm_providers as llm_api
from app.api.llm_providers import router
from app.core.config import Settings
from app.db.session import get_session
from app.llm_providers.models import LLMProvider
from app.llm_providers.schemas import LLMProviderSettings
from app.security import secret_store
from app.security.auth import TEST_ADMIN
from app.security.models import EncryptedSecret
from app.security.secret_store import EncryptedSecretStore, MasterKeyRing


class UnusedSession:
    def __init__(
        self,
        *,
        flush_error: Exception | None = None,
        provider: LLMProvider | None = None,
        secret: EncryptedSecret | None = None,
    ) -> None:
        self.rolled_back = False
        self.values = []
        self.flush_error = flush_error
        self.provider = provider
        self.secret = secret

    def add(self, value) -> None:
        self.values.append(value)

    async def rollback(self) -> None:
        self.rolled_back = True

    async def flush(self, _values=None) -> None:
        if self.flush_error is not None:
            raise self.flush_error

    async def scalar(self, _statement):
        return self.provider

    async def get(self, model, _identifier):
        if model is EncryptedSecret:
            return self.secret
        return None

    async def commit(self) -> None:
        pass

    async def refresh(self, _value) -> None:
        pass


def _app(session: UnusedSession | None = None) -> FastAPI:
    api = FastAPI()
    api.include_router(router)
    request_session = session or UnusedSession()

    async def session_override():
        yield request_session

    api.dependency_overrides[get_session] = session_override
    return api


async def test_missing_master_key_returns_safe_configuration_error(monkeypatch):
    monkeypatch.setattr(
        llm_api,
        "settings",
        Settings(_env_file=None, app_env="test", secret_master_key=None),
    )

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post(
            "/llm-providers",
            json={
                "name": "Configured provider",
                "base_url": "https://llm.example/v1",
                "default_model": "vendor/model",
                "api_key": "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK",
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "secret_store_configuration_invalid"}}
    assert "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK" not in response.text


async def test_wrong_key_returns_decryption_error_without_changing_ciphertext(monkeypatch):
    old_key = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE"
    new_key = "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI"
    session = UnusedSession()
    owner_id = uuid4()
    stored = EncryptedSecretStore(
        session,
        MasterKeyRing.from_settings(Settings(_env_file=None, secret_master_key=old_key)),
    ).create(
        purpose="provider_api_key",
        owner_type="llm_provider",
        owner_id=owner_id,
        value="TEST_OLD_PROVIDER_KEY_MUST_NOT_LEAK",
        principal=TEST_ADMIN,
        required_scope="providers:write",
    )
    original_ciphertext = stored.ciphertext
    now = datetime(2026, 7, 31, tzinfo=UTC)
    session.provider = LLMProvider(
        id=owner_id,
        name="Existing provider",
        protocol="openai_compatible",
        base_url="https://llm.example/v1",
        default_model="vendor/model",
        enabled=False,
        secret_id=stored.id,
        settings=LLMProviderSettings().model_dump(mode="json"),
        health_status="unchecked",
        generation_capability="unknown",
        research_capability="unknown",
        failure_code=None,
        last_checked_at=None,
        ownership="operator_managed",
        created_at=now,
        updated_at=now,
    )
    session.secret = stored
    monkeypatch.setattr(
        llm_api,
        "settings",
        Settings(_env_file=None, app_env="test", secret_master_key=new_key),
    )

    async with AsyncClient(
        transport=ASGITransport(app=_app(session), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/llm-providers/{owner_id}/test")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "secret_decryption_failed"}}
    assert session.rolled_back is True
    assert stored.ciphertext == original_ciphertext
    assert "TEST_OLD_PROVIDER_KEY_MUST_NOT_LEAK" not in response.text


async def test_invalid_master_key_returns_same_safe_configuration_error(monkeypatch):
    monkeypatch.setattr(
        llm_api,
        "settings",
        Settings(_env_file=None, app_env="test", secret_master_key="not-a-valid-key"),
    )

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post(
            "/llm-providers",
            json={
                "name": "Configured provider",
                "base_url": "https://llm.example/v1",
                "default_model": "vendor/model",
                "api_key": "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK",
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "secret_store_configuration_invalid"}}


async def test_missing_secret_store_dependency_fails_closed(monkeypatch):
    monkeypatch.setattr(
        llm_api,
        "settings",
        Settings(
            _env_file=None,
            app_env="development",
            secret_master_key="AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI",
        ),
    )

    async with AsyncClient(
        transport=ASGITransport(app=_app(), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/llm-providers",
            json={
                "name": "Configured provider",
                "base_url": "https://llm.example/v1",
                "default_model": "vendor/model",
                "api_key": "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK",
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "secret_store_unavailable"}}


async def test_encryption_failure_rolls_back_and_returns_safe_code(monkeypatch):
    monkeypatch.setattr(
        llm_api,
        "settings",
        Settings(
            _env_file=None,
            app_env="test",
            secret_master_key="AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI",
        ),
    )
    monkeypatch.setattr(
        secret_store.AESGCM,
        "encrypt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("TEST_MASTER_KEY_MUST_NOT_LEAK")),
    )
    session = UnusedSession()

    async with AsyncClient(
        transport=ASGITransport(app=_app(session), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/llm-providers",
            json={
                "name": "Configured provider",
                "base_url": "https://llm.example/v1",
                "default_model": "vendor/model",
                "api_key": "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK",
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "secret_encryption_failed"}}
    assert session.rolled_back is True
    assert "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK" not in response.text
    assert "TEST_MASTER_KEY_MUST_NOT_LEAK" not in response.text


class MissingRelationError(Exception):
    sqlstate = "42P01"


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (
            OperationalError("statement", {}, ConnectionError("postgresql://user:password@db/private")),
            "secret_database_unavailable",
        ),
        (
            ProgrammingError("statement", {}, MissingRelationError("encrypted_secrets missing")),
            "secret_schema_unavailable",
        ),
    ],
)
async def test_secret_persistence_failures_are_safe_distinct_and_rolled_back(
    monkeypatch,
    failure,
    expected_code,
):
    monkeypatch.setattr(
        llm_api,
        "settings",
        Settings(
            _env_file=None,
            app_env="test",
            secret_master_key="AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI",
        ),
    )
    session = UnusedSession(flush_error=failure)

    async with AsyncClient(
        transport=ASGITransport(app=_app(session), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/llm-providers",
            json={
                "name": "Configured provider",
                "base_url": "https://llm.example/v1",
                "default_model": "vendor/model",
                "api_key": "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK",
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": expected_code}}
    assert session.rolled_back is True
    assert "password" not in response.text
    assert "statement" not in response.text


async def test_add_key_rotation_preserves_provider_and_specific_error_on_encryption_failure(monkeypatch):
    monkeypatch.setattr(
        llm_api,
        "settings",
        Settings(
            _env_file=None,
            app_env="test",
            secret_master_key="AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI",
        ),
    )
    monkeypatch.setattr(
        secret_store.AESGCM,
        "encrypt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("TEST_OLD_PROVIDER_KEY_MUST_NOT_LEAK")),
    )
    now = datetime(2026, 7, 31, tzinfo=UTC)
    provider = LLMProvider(
        id=uuid4(),
        name="Existing provider",
        protocol="openai_compatible",
        base_url="https://llm.example/v1",
        default_model="vendor/model",
        enabled=False,
        secret_id=None,
        settings=LLMProviderSettings().model_dump(mode="json"),
        health_status="unchecked",
        generation_capability="unknown",
        research_capability="unknown",
        failure_code=None,
        last_checked_at=None,
        ownership="operator_managed",
        created_at=now,
        updated_at=now,
    )
    session = UnusedSession(provider=provider)

    async with AsyncClient(
        transport=ASGITransport(app=_app(session), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/llm-providers/{provider.id}/rotate-secret",
            json={"secret": "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "secret_encryption_failed"}}
    assert session.rolled_back is True
    assert provider.secret_id is None
    assert "TEST_PROVIDER_API_KEY_MUST_NOT_LEAK" not in response.text
