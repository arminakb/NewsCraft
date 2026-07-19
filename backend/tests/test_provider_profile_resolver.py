from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.generation.models import AIProviderProfile
from app.generation.provider_settings import default_codex_provider_settings
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


async def test_profile_resolver_builds_codex_from_selected_profile_and_runtime_executable():
    executor = object()
    executables = []

    def executor_factory(executable):
        executables.append(executable)
        return executor

    codex = profile(
        provider_type="codex",
        default_model="gpt-5.4",
        secret_ref=None,
        settings=default_codex_provider_settings().model_dump(mode="json"),
    )
    resolver = ProviderProfileResolver(
        secret_resolver=FakeSecrets({}),
        http_client_factory=RecordingFactory(),
        provider_registry=build_default_provider_registry(),
        application_settings=Settings(
            _env_file=None,
            codex_enabled=True,
            codex_executable="codex-private",
        ),
        executable_resolver=lambda name: "/resolved/codex" if name == "codex-private" else None,
        codex_executor_factory=executor_factory,
    )

    resolved = await resolver.resolve(codex, model_override=None)

    assert resolved.provider_type == "codex"
    assert resolved.model == "gpt-5.4"
    assert resolved.provider.profile is codex
    assert resolved.provider.executor is executor
    assert executables == ["/resolved/codex"]


async def test_profile_resolver_rejects_codex_when_disabled_or_executable_missing():
    codex = profile(
        provider_type="codex",
        default_model="gpt-5.4",
        secret_ref=None,
        settings={},
    )
    for application_settings, executable_resolver in (
        (Settings(_env_file=None, codex_enabled=False), lambda name: "/resolved/codex"),
        (Settings(_env_file=None, codex_enabled=True), lambda name: None),
    ):
        resolver = ProviderProfileResolver(
            secret_resolver=FakeSecrets({}),
            http_client_factory=RecordingFactory(),
            provider_registry=build_default_provider_registry(),
            application_settings=application_settings,
            executable_resolver=executable_resolver,
            codex_executor_factory=lambda executable: object(),
        )
        with pytest.raises(ProviderProfileConfigurationError):
            await resolver.resolve(codex, model_override=None)


async def test_profile_configuration_checksum_tracks_model_and_safe_settings_but_not_secret_reference():
    secrets = FakeSecrets({"OPENROUTER_EDITOR_KEY": "one", "OPENROUTER_OTHER_KEY": "two"})
    factory = RecordingFactory()
    resolver = ProviderProfileResolver(
        secret_resolver=secrets,
        http_client_factory=factory,
        provider_registry=build_default_provider_registry(),
    )
    profile_id = uuid4()
    base = profile(id=profile_id)
    changed_secret = profile(id=profile_id, secret_ref="OPENROUTER_OTHER_KEY")
    changed_model = profile(id=profile_id, default_model="openai/gpt-5-mini")
    changed_timeout = profile(
        id=profile_id,
        settings={**base.settings, "timeout_seconds": 46},
    )

    resolved = [
        await resolver.resolve(candidate, None)
        for candidate in (base, changed_secret, changed_model, changed_timeout)
    ]
    try:
        assert resolved[0].configuration_checksum == resolved[1].configuration_checksum
        assert resolved[0].configuration_checksum != resolved[2].configuration_checksum
        assert resolved[0].configuration_checksum != resolved[3].configuration_checksum
        assert all(len(item.configuration_revision) == 16 for item in resolved)
        assert all(len(item.configuration_checksum) == 64 for item in resolved)
    finally:
        for client in factory.clients:
            await client.aclose()
