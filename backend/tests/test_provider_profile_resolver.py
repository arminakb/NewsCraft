from uuid import uuid4

import httpx
import pytest

from app.generation.models import AIProviderProfile
from app.generation.providers.base import GenerationProviderRequest, ProviderMessage
from app.generation.providers.profiles import (
    ProviderProfileConfigurationError,
    ProviderProfileResolver,
)
from app.generation.providers.registry import build_default_provider_registry
from app.generation.telegram_schema import TelegramRewriteOutput


class FakeSecrets:
    def __init__(self, values):
        self.values = values
        self.resolved = []

    def configured(self, reference):
        return bool(self.values.get(reference))

    def resolve(self, reference):
        self.resolved.append(reference)
        return self.values[reference]


class RecordingFactory:
    def __init__(self):
        self.last_kwargs = None
        self.clients = []

    def __call__(self, **kwargs):
        self.last_kwargs = kwargs
        client = httpx.AsyncClient()
        self.clients.append(client)
        return client


def profile(**overrides):
    values = {
        "id": uuid4(),
        "name": "Editor",
        "provider_type": "openrouter",
        "default_model": "anthropic/claude-sonnet-4.5",
        "secret_ref": "OPENROUTER_EDITOR_KEY",
        "settings": {
            "base_url": "https://openrouter.example/api/v1",
            "timeout_seconds": 45,
            "http_referer": "http://127.0.0.1:3000",
            "app_title": "NewsCraft",
            "pricing": {
                "input_usd_per_million": "1.25",
                "output_usd_per_million": "5.00",
            },
        },
        "enabled": True,
    }
    values.update(overrides)
    return AIProviderProfile(**values)


async def test_profile_resolver_honors_selected_secret_settings_and_default_model():
    secrets = FakeSecrets({"OPENROUTER_EDITOR_KEY": "editor-secret"})
    factory = RecordingFactory()
    resolver = ProviderProfileResolver(
        secret_resolver=secrets,
        http_client_factory=factory,
        provider_registry=build_default_provider_registry(),
    )

    resolved = await resolver.resolve(profile(), model_override=None)

    assert resolved.model == "anthropic/claude-sonnet-4.5"
    assert resolved.provider.base_url == "https://openrouter.example/api/v1"
    assert resolved.provider.timeout_seconds == 45
    assert resolved.provider.api_key == "editor-secret"
    assert secrets.resolved == ["OPENROUTER_EDITOR_KEY"]
    assert factory.last_kwargs == {
        "base_url": "https://openrouter.example/api/v1",
        "timeout_seconds": 45,
        "http_referer": "http://127.0.0.1:3000/",
        "app_title": "NewsCraft",
    }
    await factory.clients[0].aclose()


async def test_profile_resolver_uses_route_override_and_only_selected_profile_secret():
    secrets = FakeSecrets({"OPENROUTER_A_KEY": "key-a", "OPENROUTER_B_KEY": "key-b"})
    factory = RecordingFactory()
    resolver = ProviderProfileResolver(
        secret_resolver=secrets,
        http_client_factory=factory,
        provider_registry=build_default_provider_registry(),
    )

    selected = await resolver.resolve(
        profile(secret_ref="OPENROUTER_B_KEY", default_model="model-b", settings={}),
        model_override="route-model",
    )

    assert selected.model == "route-model"
    assert selected.provider.api_key == "key-b"
    assert secrets.resolved == ["OPENROUTER_B_KEY"]
    assert "key-a" not in repr(selected)
    await factory.clients[0].aclose()


async def test_fake_profile_uses_registered_provider_without_secret_or_http():
    factory = RecordingFactory()
    resolver = ProviderProfileResolver(
        secret_resolver=FakeSecrets({}),
        http_client_factory=factory,
        provider_registry=build_default_provider_registry(),
    )
    resolved = await resolver.resolve(
        profile(provider_type="fake", secret_ref=None, default_model=None, settings={}),
        model_override=None,
    )
    assert resolved.model == "fake-v1"
    assert resolved.provider.provider_name == "fake"
    assert factory.last_kwargs is None
    request = GenerationProviderRequest(
        run_id=uuid4(),
        purpose="telegram_rewrite",
        requested_model="route-fake-model",
        messages=(ProviderMessage(role="user", content="Rewrite"),),
        response_schema=TelegramRewriteOutput.model_json_schema(),
        metadata={},
    )
    result = await resolved.provider.generate(request)
    TelegramRewriteOutput.model_validate(result.output)
    assert result.resolved_model == "route-fake-model"


@pytest.mark.parametrize(
    "broken",
    [
        profile(enabled=False),
        profile(secret_ref=None),
        profile(provider_type="unknown"),
        profile(default_model=None),
        profile(settings={"unexpected": True}),
        profile(settings={"base_url": "ftp://invalid.example"}),
        profile(settings={"base_url": "https://user:pass@example.com/api"}),
    ],
)
async def test_profile_resolver_rejects_invalid_configuration_before_http(broken):
    factory = RecordingFactory()
    resolver = ProviderProfileResolver(
        secret_resolver=FakeSecrets({"OPENROUTER_EDITOR_KEY": "secret"}),
        http_client_factory=factory,
        provider_registry=build_default_provider_registry(),
    )
    with pytest.raises(ProviderProfileConfigurationError):
        await resolver.resolve(broken, model_override=None)
    assert factory.last_kwargs is None


async def test_profile_resolver_rejects_unconfigured_selected_secret_before_http():
    factory = RecordingFactory()
    resolver = ProviderProfileResolver(
        secret_resolver=FakeSecrets({}),
        http_client_factory=factory,
        provider_registry=build_default_provider_registry(),
    )
    with pytest.raises(ProviderProfileConfigurationError, match="not configured"):
        await resolver.resolve(profile(), model_override=None)
    assert factory.last_kwargs is None
