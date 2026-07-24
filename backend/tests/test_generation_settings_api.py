from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.api.capabilities import get_capability_status_service
from app.api.generation_schemas import (
    AIProviderProfileCreate,
    AIProviderProfilePatch,
    BrandProfileCreate,
    BrandProfilePatch,
    PromptTemplateCreate,
    PromptTemplateVersionCreate,
)
from app.api.generation_settings import (
    activate_prompt_version,
    create_brand_profile,
    create_prompt_template,
    create_prompt_version,
    create_provider_profile,
    list_prompt_versions,
    patch_provider_profile,
    seed_codex_provider_profile,
)
from app.core.config import Settings
from app.db.session import get_session
from app.generation.canonical import CanonicalStoryOutput
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.provider_settings import (
    CodexProviderSettings,
    OpenRouterProviderSettings,
    default_codex_provider_settings,
    effective_codex_provider_settings,
)
from app.main import app
from tests.capability_fakes import AVAILABLE_CAPABILITIES, StaticCapabilityStatusService


def _research_budget(max_model_calls: int) -> dict:
    return {
        "max_model_calls": max_model_calls,
        "max_input_tokens": 60_000,
        "max_output_tokens": 12_000,
        "max_cost_usd": "2.00",
        "max_queries": 4,
        "max_results_per_query": 5,
        "max_pages": 8,
        "max_elapsed_seconds": 120,
        "max_total_chars": 120_000,
    }


def test_openrouter_settings_round_trip_pricing_and_distinct_research_budgets():
    settings = OpenRouterProviderSettings.model_validate(
        {
            "base_url": "https://openrouter.example/api/v1",
            "pricing": {
                "input_usd_per_million": "1.25",
                "output_usd_per_million": "5.00",
            },
            "research_budgets": {
                "standard": _research_budget(3),
                "deep": _research_budget(6),
            },
        }
    )

    assert settings.pricing.input_usd_per_million == Decimal("1.25")
    assert settings.pricing.output_usd_per_million == Decimal("5.00")
    assert settings.research_budgets.standard.max_model_calls == 3
    assert settings.research_budgets.deep.max_model_calls == 6


def test_provider_contract_rejects_fake_settings_and_requires_openrouter_model_and_reference():
    with pytest.raises(ValidationError, match="fake provider"):
        AIProviderProfileCreate.model_validate({"name": "Fake", "provider_type": "fake", "settings": {}})
    with pytest.raises(ValidationError, match="openrouter requires"):
        AIProviderProfileCreate.model_validate(
            {"name": "Live", "provider_type": "openrouter", "secret_ref": "OPENROUTER_KEY"}
        )


def test_provider_contract_forbids_unknown_settings_keys():
    with pytest.raises(ValidationError):
        OpenRouterProviderSettings.model_validate({"api_key": "must-never-be-stored"})


def test_codex_provider_settings_are_strict_and_apply_effective_nested_defaults():
    defaults = default_codex_provider_settings()
    assert defaults.research_budgets.standard.max_pages == 8
    assert defaults.research_budgets.deep.max_pages == 16
    assert defaults.generation_limits.max_model_calls == 1
    omitted = CodexProviderSettings.model_validate({})
    effective = effective_codex_provider_settings(omitted)
    assert omitted.research_budgets is None
    assert effective.research_budgets == defaults.research_budgets
    with pytest.raises(ValidationError):
        CodexProviderSettings.model_validate({"executable": "/usr/bin/codex"})


def test_codex_profile_forbids_secret_and_requires_model():
    with pytest.raises(ValidationError, match="codex"):
        AIProviderProfileCreate.model_validate(
            {
                "name": "Codex CLI",
                "provider_type": "codex",
                "default_model": "gpt-5.4",
                "secret_ref": "OPENAI_API_KEY",
            }
        )


def test_codex_runtime_settings_have_safe_disabled_defaults():
    runtime = Settings(_env_file=None)
    assert runtime.codex_enabled is False
    assert runtime.codex_executable == "codex"
    with pytest.raises(ValidationError, match="codex"):
        AIProviderProfileCreate.model_validate({"name": "Codex CLI", "provider_type": "codex"})


async def test_editorial_prompt_versions_keep_the_stage_schema():
    session = GenerationSession()
    template = PromptTemplate(id=uuid4(), purpose_key="canonical_story", name="Canonical", description=None)
    session.values.append(template)
    created = await create_prompt_version(
        template.id,
        PromptTemplateVersionCreate(
            system_template="Use persisted evidence only",
            user_template="Story {story_title}; evidence {evidence_json}",
        ),
        session,
    )
    assert created.output_schema_version == "canonical_story.v1"
    assert created.output_schema == CanonicalStoryOutput.model_json_schema()


@pytest.mark.parametrize(
    "user_template",
    [
        "Story {{story_title}}; evidence {evidence_json}",
        "Story {story_title}; evidence {evidence_json}; extra {unknown}",
        "Story {story_title.upper}; evidence {evidence_json}",
        "Story {story_title[0]}; evidence {evidence_json}",
    ],
)
async def test_editorial_prompt_rejects_escaped_missing_unknown_or_complex_fields(user_template):
    session = GenerationSession()
    template = PromptTemplate(id=uuid4(), purpose_key="canonical_story", name="Canonical", description=None)
    session.values.append(template)
    with pytest.raises(HTTPException) as error:
        await create_prompt_version(
            template.id,
            PromptTemplateVersionCreate(system_template="Use evidence", user_template=user_template),
            session,
        )
    assert error.value.status_code == 422


async def test_prompt_checksum_is_identical_for_non_ascii_content_across_api_and_seed_runtime():
    from app.generation.default_prompts import prompt_checksum

    session = GenerationSession()
    template = PromptTemplate(id=uuid4(), purpose_key="canonical_story", name="Canonical", description=None)
    session.values.append(template)
    user = "داستان {story_title}؛ شواهد {evidence_json}"
    created = await create_prompt_version(
        template.id,
        PromptTemplateVersionCreate(system_template="سامانه", user_template=user),
        session,
    )
    assert created.checksum_sha256 == prompt_checksum("سامانه", user, CanonicalStoryOutput.model_json_schema())


async def test_codex_profile_create_applies_defaults_and_exposes_only_safe_capabilities():
    session = GenerationSession()

    created = await create_provider_profile(
        AIProviderProfileCreate.model_validate(
            {
                "name": "Codex CLI",
                "provider_type": "codex",
                "default_model": "gpt-5.4",
                "settings": {},
            }
        ),
        session,
        AVAILABLE_CAPABILITIES,
    )
    stored = session.one(AIProviderProfile)
    assert stored.settings == {}
    assert created.configured is True
    assert created.capabilities == {"generation": True, "research": True}
    assert created.unavailability_codes == []
    assert "/private/operator" not in created.model_dump_json()
    assert "environment" not in created.model_dump_json().lower()


async def test_provider_configuration_api_works_without_external_credentials_and_reports_unknown(
    monkeypatch,
):
    for name in (
        "OPENROUTER_API_KEY",
        "TELEGRAM_SOURCE_EDITOR_API_ID",
        "TELEGRAM_SOURCE_EDITOR_API_HASH",
        "TELEGRAM_SOURCE_EDITOR_SESSION",
        "TELEGRAM_DESTINATION_NEWS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    session = GenerationSession()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_capability_status_service] = lambda: (
        StaticCapabilityStatusService("unknown")
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ai-provider-profiles",
                json={
                    "name": "Credential-free API configuration",
                    "provider_type": "openrouter",
                    "default_model": "openai/gpt-5-mini",
                    "secret_ref": "OPENROUTER_API_KEY",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["configured"] is False
    assert payload["capability_states"]["generation"]["status"] == "unknown"
    assert payload["capability_states"]["research"]["status"] == "unknown"
    assert "secret_ref" not in payload
    assert "OPENROUTER_API_KEY" not in response.text


async def test_codex_profile_seed_is_idempotent_and_has_no_secret():
    session = GenerationSession()
    first = await seed_codex_provider_profile(session, enabled=True, model="gpt-5.4")
    second = await seed_codex_provider_profile(session, enabled=True, model="gpt-5.4")
    assert first.id == second.id
    assert first.secret_ref is None
    assert first.provider_type == "codex"
    settings = CodexProviderSettings.model_validate(first.settings)
    assert settings.research_budgets.deep.max_model_calls == 1


async def test_codex_profile_seed_never_overwrites_operator_configuration():
    session = GenerationSession()
    drifted = AIProviderProfile(
        id=uuid4(),
        name="Codex CLI",
        provider_type="openrouter",
        default_model="wrong-model",
        secret_ref="OPENROUTER_API_KEY",
        settings={"base_url": "https://example.com"},
        enabled=False,
    )
    session.values.append(drifted)

    preserved = await seed_codex_provider_profile(session, enabled=True, model="gpt-5.4")

    assert preserved is drifted
    assert preserved.provider_type == "openrouter"
    assert preserved.default_model == "wrong-model"
    assert preserved.secret_ref == "OPENROUTER_API_KEY"
    assert preserved.settings == {"base_url": "https://example.com"}
    assert preserved.enabled is False


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "output_language",
        "tone",
        "editorial_rules",
        "attribution_rules",
        "default_hashtags",
        "platform_preferences",
        "is_default",
    ],
)
async def test_brand_patch_rejects_explicit_null_with_422_and_no_mutation(field):
    session = GenerationSession()
    brand = BrandProfile(
        id=uuid4(),
        name="Newsroom",
        output_language="fa",
        tone="neutral",
        editorial_rules=["verify"],
        attribution_rules={"mode": "preserve"},
        default_hashtags=["news"],
        platform_preferences={"telegram": True},
        is_default=False,
    )
    session.values.append(brand)
    before = {name: getattr(brand, name) for name in BrandProfilePatch.model_fields}

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(f"/brand-profiles/{brand.id}", json={field: None})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert {name: getattr(brand, name) for name in BrandProfilePatch.model_fields} == before


async def test_provider_patch_recursively_preserves_pricing_and_both_research_budgets():
    session = GenerationSession()
    created = await create_provider_profile(
        AIProviderProfileCreate.model_validate(
            {
                "name": "Editor",
                "provider_type": "openrouter",
                "default_model": "openai/gpt-5-mini",
                "secret_ref": "OPENROUTER_EDITOR_KEY",
                "settings": {
                    "pricing": {
                        "input_usd_per_million": "1.25",
                        "output_usd_per_million": "5.00",
                    },
                    "research_budgets": {
                        "standard": _research_budget(3),
                        "deep": _research_budget(6),
                    },
                },
            }
        ),
        session,
        AVAILABLE_CAPABILITIES,
    )

    patched = await patch_provider_profile(
        created.id,
        AIProviderProfilePatch.model_validate({"settings": {"pricing": {"input_usd_per_million": "2.50"}}}),
        session,
        AVAILABLE_CAPABILITIES,
    )

    assert patched.settings["pricing"] == {
        "input_usd_per_million": "2.50",
        "output_usd_per_million": "5.00",
    }
    assert patched.settings["research_budgets"]["standard"]["max_model_calls"] == 3
    assert patched.settings["research_budgets"]["deep"]["max_model_calls"] == 6
    assert patched.configured is True
    assert not hasattr(patched, "secret_ref")


async def test_provider_patch_distinguishes_omitted_settings_from_null_and_maps_validation_to_422():
    session = GenerationSession()
    created = await create_provider_profile(
        AIProviderProfileCreate.model_validate(
            {
                "name": "Editor",
                "provider_type": "openrouter",
                "default_model": "model-one",
                "secret_ref": "OPENROUTER_EDITOR_KEY",
                "settings": {"timeout_seconds": 45},
            }
        ),
        session,
        AVAILABLE_CAPABILITIES,
    )

    renamed = await patch_provider_profile(
        created.id,
        AIProviderProfilePatch.model_validate({"name": "Renamed editor"}),
        session,
        AVAILABLE_CAPABILITIES,
    )
    assert renamed.settings["timeout_seconds"] == 45

    cleared = await patch_provider_profile(
        created.id,
        AIProviderProfilePatch.model_validate({"settings": None}),
        session,
        AVAILABLE_CAPABILITIES,
    )
    assert cleared.settings == {}

    with pytest.raises(HTTPException) as error:
        await patch_provider_profile(
            created.id,
            AIProviderProfilePatch.model_validate({"default_model": None}),
            session,
            AVAILABLE_CAPABILITIES,
        )
    assert error.value.status_code == 422
    assert "OPENROUTER_EDITOR_KEY" not in str(error.value.detail)
    assert session.one(AIProviderProfile).default_model == "model-one"


async def test_prompt_edits_create_immutable_versions_and_activation_selects_exactly_one():
    session = GenerationSession()
    template = await create_prompt_template(
        PromptTemplateCreate(
            purpose_key="telegram_rewrite",
            name="Telegram rewrite",
            description=None,
        ),
        session,
    )
    user_template = " ".join(
        f"{{{name}}}"
        for name in (
            "source_text",
            "source_url",
            "source_channel",
            "language",
            "direction",
            "attribution_policy",
            "custom_footer",
        )
    )
    first = await create_prompt_version(
        template.id,
        PromptTemplateVersionCreate(system_template="System one", user_template=user_template),
        session,
    )
    second = await create_prompt_version(
        template.id,
        PromptTemplateVersionCreate(system_template="System two", user_template=user_template),
        session,
    )

    await activate_prompt_version(first.id, session)

    assert first.version == 1
    assert first.system_template == "System one"
    assert second.version == 2
    assert first.is_active is True
    assert second.is_active is False
    assert first.output_schema_version == "telegram_rewrite.v1"
    assert session.prompt_lock_count == 2


async def test_prompt_version_history_returns_newest_first_with_immutable_safe_fields():
    session = GenerationSession()
    now = datetime.now(UTC)
    template = PromptTemplate(id=uuid4(), purpose_key="telegram_rewrite", name="Telegram rewrite")
    older = PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=template.id,
        version=1,
        system_template="System one",
        user_template="User one",
        output_schema_version="telegram_rewrite.v1",
        output_schema={"type": "object"},
        checksum_sha256="a" * 64,
        is_active=False,
        created_at=now - timedelta(hours=1),
    )
    active = PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=template.id,
        version=2,
        system_template="System two",
        user_template="User two",
        output_schema_version="telegram_rewrite.v1",
        output_schema={"type": "object", "required": ["body"]},
        checksum_sha256="b" * 64,
        is_active=True,
        created_at=now,
    )
    session.values.extend([template, older, active])

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/prompt-templates/{template.id}/versions")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    history = response.json()
    assert [item["version"] for item in history] == [2, 1]
    assert history[0] == {
        "id": str(active.id),
        "prompt_template_id": str(template.id),
        "version": 2,
        "system_template": "System two",
        "user_template": "User two",
        "output_schema_version": "telegram_rewrite.v1",
        "output_schema": {"type": "object", "required": ["body"]},
        "checksum_sha256": "b" * 64,
        "is_active": True,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    }
    assert "secret" not in response.text.lower()


async def test_prompt_version_history_returns_404_for_unknown_template():
    with pytest.raises(HTTPException) as error:
        await list_prompt_versions(uuid4(), GenerationSession())

    assert error.value.status_code == 404


async def test_conflicting_duplicate_brand_template_and_provider_creates_return_409():
    session = GenerationSession()
    await create_brand_profile(
        BrandProfileCreate(
            name="Newsroom",
            output_language="fa",
            tone="neutral",
        ),
        session,
    )
    with pytest.raises(HTTPException) as brand_conflict:
        await create_brand_profile(
            BrandProfileCreate(
                name="Newsroom",
                output_language="fa",
                tone="urgent",
            ),
            session,
        )
    assert brand_conflict.value.status_code == 409

    await create_prompt_template(
        PromptTemplateCreate(purpose_key="telegram_rewrite", name="Rewrite", description=None),
        session,
    )
    with pytest.raises(HTTPException) as prompt_conflict:
        await create_prompt_template(
            PromptTemplateCreate(purpose_key="telegram_rewrite", name="Different name", description=None),
            session,
        )
    assert prompt_conflict.value.status_code == 409

    await create_provider_profile(
        AIProviderProfileCreate(
            name="Fake",
            provider_type="fake",
            default_model="fake-v1",
        ),
        session,
        AVAILABLE_CAPABILITIES,
    )
    with pytest.raises(HTTPException) as provider_conflict:
        await create_provider_profile(
            AIProviderProfileCreate(
                name="Fake",
                provider_type="fake",
                default_model="fake-v2",
            ),
            session,
            AVAILABLE_CAPABILITIES,
        )
    assert provider_conflict.value.status_code == 409
    assert session.nested_count == 3


async def test_generation_create_savepoints_recover_matching_winners_and_reject_conflicts():
    brand = BrandProfile(
        id=uuid4(),
        name="Newsroom",
        output_language="fa",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=False,
    )
    brand_body = BrandProfileCreate(name="Newsroom", output_language="fa", tone="neutral")
    brand_match = GenerationSavepointRaceSession(brand)
    assert await create_brand_profile(brand_body, brand_match) is brand
    brand_conflict = GenerationSavepointRaceSession(brand)
    with pytest.raises(HTTPException) as error:
        await create_brand_profile(
            BrandProfileCreate(name="Newsroom", output_language="fa", tone="urgent"),
            brand_conflict,
        )
    assert error.value.status_code == 409

    template = PromptTemplate(id=uuid4(), purpose_key="telegram_rewrite", name="Rewrite", description=None)
    template_body = PromptTemplateCreate(purpose_key="telegram_rewrite", name="Rewrite", description=None)
    template_match = GenerationSavepointRaceSession(template)
    assert await create_prompt_template(template_body, template_match) is template
    template_conflict = GenerationSavepointRaceSession(template)
    with pytest.raises(HTTPException) as error:
        await create_prompt_template(
            PromptTemplateCreate(purpose_key="telegram_rewrite", name="Different", description=None),
            template_conflict,
        )
    assert error.value.status_code == 409

    provider = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    provider_body = AIProviderProfileCreate(name="Fake", provider_type="fake", default_model="fake-v1")
    provider_match = GenerationSavepointRaceSession(provider)
    assert (
        await create_provider_profile(provider_body, provider_match, AVAILABLE_CAPABILITIES)
    ).id == provider.id
    provider_conflict = GenerationSavepointRaceSession(provider)
    with pytest.raises(HTTPException) as error:
        await create_provider_profile(
            AIProviderProfileCreate(name="Fake", provider_type="fake", default_model="fake-v2"),
            provider_conflict,
            AVAILABLE_CAPABILITIES,
        )
    assert error.value.status_code == 409

    sessions = (
        brand_match,
        brand_conflict,
        template_match,
        template_conflict,
        provider_match,
        provider_conflict,
    )
    assert all(session.integrity_errors == 1 for session in sessions)


class GenerationSession:
    def __init__(self):
        self.values = []
        self.prompt_lock_count = 0
        self.nested_count = 0

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        self.values.append(value)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def get(self, model, identifier):
        return next(
            (value for value in self.values if isinstance(value, model) and value.id == identifier),
            None,
        )

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is PromptTemplate and statement._for_update_arg is not None:
            self.prompt_lock_count += 1
        return next((value for value in self.values if isinstance(value, entity)), None)

    async def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        values = [value for value in self.values if isinstance(value, entity)]
        if entity is PromptTemplateVersion:
            values.sort(key=lambda item: item.version, reverse=True)
        return values

    def begin_nested(self):
        self.nested_count += 1
        return AsyncNullContext()

    def one(self, model):
        return next(value for value in self.values if isinstance(value, model))


class AsyncNullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class GenerationSavepointRaceSession:
    def __init__(self, winner):
        self.winner = winner
        self.race_exposed = False
        self.integrity_errors = 0

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if not self.race_exposed:
            return None
        return self.winner if isinstance(self.winner, entity) else None

    def begin_nested(self):
        return AsyncNullContext()

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = uuid4()

    async def flush(self):
        if not self.race_exposed:
            self.race_exposed = True
            self.integrity_errors += 1
            raise IntegrityError("forced nested race", {}, RuntimeError("winner committed"))

    async def commit(self):
        return None
