from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.generation.models import AIProviderProfile
from app.generation.provider_execution import _resolve_profile
from app.generation.providers.profiles import ProviderProfileConfigurationError
from app.jobs.errors import PermanentJobError, RetryableJobError
from app.security.secret_store import SecretStoreUnavailable


class Session:
    def __init__(self, profile: AIProviderProfile) -> None:
        self.profile = profile

    async def get(self, _model, _identifier):
        return self.profile


def context(profile: AIProviderProfile):
    return SimpleNamespace(session=Session(profile))


def profile() -> AIProviderProfile:
    return AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )


@pytest.mark.asyncio
async def test_profile_resolution_retries_secret_store_outage_with_cause():
    selected = profile()

    class Resolver:
        async def resolve_with_session(self, *_args, **_kwargs):
            raise SecretStoreUnavailable

    with pytest.raises(RetryableJobError) as caught:
        await _resolve_profile(context(selected), profile_resolver=Resolver(), profile_id=selected.id)

    assert caught.value.code == "generation_profile_temporarily_unavailable"
    assert isinstance(caught.value.__cause__, SecretStoreUnavailable)


@pytest.mark.asyncio
async def test_profile_resolution_keeps_configuration_failure_permanent_with_cause():
    selected = profile()

    class Resolver:
        async def resolve_with_session(self, *_args, **_kwargs):
            raise ProviderProfileConfigurationError("invalid")

    with pytest.raises(PermanentJobError) as caught:
        await _resolve_profile(context(selected), profile_resolver=Resolver(), profile_id=selected.id)

    assert caught.value.code == "generation_profile_unavailable"
    assert isinstance(caught.value.__cause__, ProviderProfileConfigurationError)
