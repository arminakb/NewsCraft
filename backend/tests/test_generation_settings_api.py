from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.api.generation_schemas import (
    BrandProfileCreate,
    BrandProfilePatch,
    PromptActivationCreate,
    PromptTemplateCreate,
    PromptTemplateVersionCreate,
)
from app.api.generation_settings import (
    activate_prompt_version,
    create_brand_profile,
    create_prompt_template,
    create_prompt_version,
    list_prompt_versions,
    patch_brand_profile,
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
from app.security.auth import TEST_ADMIN


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


def test_codex_runtime_settings_have_safe_disabled_defaults():
    runtime = Settings(_env_file=None)
    assert runtime.codex_enabled is False
    assert runtime.codex_executable == "codex"


def test_prompt_versions_enforce_individual_and_combined_size_limits():
    with pytest.raises(ValidationError, match="20000"):
        PromptTemplateVersionCreate(
            system_template="s" * 20_001,
            user_template="user",
        )
    with pytest.raises(ValidationError, match="40000"):
        PromptTemplateVersionCreate(
            system_template="system",
            user_template="u" * 40_001,
        )
    with pytest.raises(ValidationError, match="combined"):
        PromptTemplateVersionCreate(
            system_template="s" * 20_000,
            user_template="u" * 30_001,
        )


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


@pytest.mark.parametrize("purpose", ["instagram_pack", "x_pack", "blog_pack"])
async def test_manual_prompt_purposes_share_required_variable_validation(purpose):
    session = GenerationSession()
    template = PromptTemplate(id=uuid4(), purpose_key=purpose, name=purpose, description=None)
    session.values.append(template)
    variables = (
        "canonical_story_json",
        "brand_profile_json",
        "platform_limits_json",
        "source_media_json",
        "instruction",
    )
    created = await create_prompt_version(
        template.id,
        PromptTemplateVersionCreate(
            system_template="Use evidence only",
            user_template=" ".join(f"{{{name}}}" for name in variables),
        ),
        session,
    )
    assert created.output_schema_version == f"{purpose}.v1"

    with pytest.raises(HTTPException) as error:
        await create_prompt_version(
            template.id,
            PromptTemplateVersionCreate(
                system_template="Use evidence only",
                user_template=" ".join(f"{{{name}}}" for name in variables[:-1]),
            ),
            session,
        )
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "prompt_template_invalid"


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


async def test_setting_default_brand_profile_clears_the_previous_default():
    session = GenerationSession()
    previous = BrandProfile(
        id=uuid4(),
        name="Previous",
        output_language="fa",
        tone="neutral",
        is_default=True,
    )
    selected = BrandProfile(
        id=uuid4(),
        name="Selected",
        output_language="en",
        tone="analytical",
        is_default=False,
    )
    session.values.extend([previous, selected])

    result = await patch_brand_profile(
        selected.id,
        BrandProfilePatch(is_default=True),
        session,
    )

    assert result is selected
    assert selected.is_default is True
    assert previous.is_default is False


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

    await activate_prompt_version(
        first.id,
        PromptActivationCreate(reason="Approved for newsroom use"),
        TEST_ADMIN,
        session,
    )

    assert first.version == 1
    assert first.system_template == "System one"
    assert second.version == 2
    assert first.is_active is True
    assert second.is_active is False
    assert first.activated_by_type == "test_harness"
    assert first.activated_by_id == "pytest"
    assert first.activation_reason == "Approved for newsroom use"
    assert first.activated_at is not None
    assert first.output_schema_version == "telegram_rewrite.v1"
    assert session.prompt_lock_count == 3


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
        "activated_at": None,
        "activated_by_type": None,
        "activated_by_id": None,
        "activation_reason": None,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    }
    assert "secret" not in response.text.lower()


async def test_prompt_version_history_returns_404_for_unknown_template():
    with pytest.raises(HTTPException) as error:
        await list_prompt_versions(uuid4(), GenerationSession())

    assert error.value.status_code == 404


async def test_conflicting_duplicate_brand_and_template_creates_return_409():
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

    assert session.nested_count == 2


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

    sessions = (
        brand_match,
        brand_conflict,
        template_match,
        template_conflict,
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
