from __future__ import annotations

import shutil
from collections.abc import Callable
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.generation_schemas import (
    AIProviderProfileCreate,
    AIProviderProfileOut,
    AIProviderProfilePatch,
    BrandProfileCreate,
    BrandProfileOut,
    BrandProfilePatch,
    PromptTemplateCreate,
    PromptTemplateVersionCreate,
    PromptTemplateVersionOut,
)
from app.api.telegram_destinations import get_secret_resolver
from app.core.config import settings as application_settings
from app.core.secrets import SecretResolver
from app.db.session import get_session
from app.generation.canonical import CanonicalStoryOutput
from app.generation.default_prompts import prompt_checksum, validate_prompt_template_fields
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplate, PromptTemplateVersion
from app.generation.provider_settings import (
    CodexProviderSettings,
    OpenRouterProviderSettings,
    default_codex_provider_settings,
    merge_provider_settings,
)
from app.generation.telegram_schema import TelegramRewriteOutput

router = APIRouter(tags=["generation-settings"])
SessionDependency = Depends(get_session)
SecretResolverDependency = Annotated[SecretResolver, Depends(get_secret_resolver)]
type ExecutableResolver = Callable[[str], str | None]


def get_executable_resolver() -> ExecutableResolver:
    return shutil.which


ExecutableResolverDependency = Annotated[ExecutableResolver, Depends(get_executable_resolver)]

_TELEGRAM_REWRITE_VARIABLES = (
    "source_text",
    "source_url",
    "source_channel",
    "language",
    "direction",
    "attribution_policy",
    "custom_footer",
)
_TELEGRAM_REWRITE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["body", "parse_mode", "buttons"],
    "properties": {
        "body": {"type": "string", "minLength": 1, "maxLength": 4096},
        "parse_mode": {"const": "HTML"},
        "buttons": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "url"],
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 64},
                    "url": {"type": "string", "format": "uri"},
                },
            },
        },
    },
}
_EDITORIAL_PROMPT_CONTRACTS = {
    "canonical_story": (
        ("story_title", "evidence_json"),
        "canonical_story.v1",
        CanonicalStoryOutput.model_json_schema(),
    ),
    "telegram_pack": (
        ("canonical_story_json", "brand_profile_json", "direction", "instruction"),
        "telegram_pack.v1",
        TelegramRewriteOutput.model_json_schema(),
    ),
}


def _profile_out(
    profile: AIProviderProfile,
    secrets: SecretResolver,
    executable_resolver: ExecutableResolver = shutil.which,
) -> AIProviderProfileOut:
    capabilities, codes = provider_capabilities(profile, secrets, executable_resolver)
    generation = capabilities["generation"]
    research = capabilities["research"]
    configured = generation or research
    return AIProviderProfileOut(
        id=profile.id,
        name=profile.name,
        provider_type=profile.provider_type,
        default_model=profile.default_model,
        settings=dict(profile.settings or {}),
        enabled=profile.enabled,
        configured=configured,
        capabilities=capabilities,
        unavailability_codes=codes,
    )


def provider_capabilities(
    profile: AIProviderProfile,
    secrets: SecretResolver,
    executable_resolver: ExecutableResolver = shutil.which,
) -> tuple[dict[str, bool], list[str]]:
    codes: list[str] = []
    generation = False
    research = False
    if not profile.enabled:
        codes.append("disabled")
    elif profile.provider_type == "fake":
        generation = research = profile.secret_ref is None and not dict(profile.settings or {})
        if not generation:
            codes.append("invalid_settings")
    elif profile.provider_type == "codex":
        try:
            CodexProviderSettings.model_validate(dict(profile.settings or {}))
            valid_settings = True
        except ValidationError:
            valid_settings = False
        executable_available = (
            application_settings.codex_enabled
            and executable_resolver(application_settings.codex_executable) is not None
        )
        generation = research = bool(
            profile.default_model and profile.secret_ref is None and valid_settings and executable_available
        )
        if not profile.default_model:
            codes.append("model_missing")
        if profile.secret_ref is not None or not valid_settings:
            codes.append("invalid_settings")
        if not executable_available:
            codes.append("executable_unavailable")
    elif profile.provider_type == "openrouter":
        try:
            validated = OpenRouterProviderSettings.model_validate(dict(profile.settings or {}))
            valid_settings = True
        except ValidationError:
            validated = None
            valid_settings = False
        secret_available = bool(profile.secret_ref and secrets.configured(profile.secret_ref))
        generation = bool(profile.default_model and secret_available and valid_settings)
        research = bool(
            generation
            and validated is not None
            and validated.pricing is not None
            and validated.research_budgets is not None
        )
        if not profile.default_model:
            codes.append("model_missing")
        if not secret_available:
            codes.append("secret_unavailable")
        if not valid_settings:
            codes.append("invalid_settings")
        elif not research:
            codes.append("research_settings_missing")
    else:
        codes.append("unsupported_provider")
    return {"generation": generation, "research": research}, codes


def _brand_values(body: BrandProfileCreate) -> dict:
    return body.model_dump(mode="json")


def _brand_matches(profile: BrandProfile, body: BrandProfileCreate) -> bool:
    return all(getattr(profile, key) == value for key, value in _brand_values(body).items())


def _template_matches(template: PromptTemplate, body: PromptTemplateCreate) -> bool:
    return template.name == body.name and template.description == body.description


def _provider_values(body: AIProviderProfileCreate) -> dict:
    return {
        "name": body.name,
        "provider_type": body.provider_type,
        "default_model": body.default_model,
        "secret_ref": body.secret_ref,
        "settings": _validated_settings(body.provider_type, body.settings),
        "enabled": body.enabled,
    }


def _provider_matches(profile: AIProviderProfile, body: AIProviderProfileCreate) -> bool:
    return all(getattr(profile, key) == value for key, value in _provider_values(body).items())


def _validated_settings(provider_type: str, value: dict | None) -> dict:
    if provider_type == "fake" or value is None:
        return {}
    if provider_type == "codex":
        CodexProviderSettings.model_validate(value)
        return dict(value)
    return OpenRouterProviderSettings.model_validate(value).model_dump(mode="json")


async def seed_codex_provider_profile(
    session: AsyncSession,
    *,
    enabled: bool,
    model: str,
) -> AIProviderProfile:
    rows = list(await session.scalars(select(AIProviderProfile).with_for_update()))
    profile = next((row for row in rows if row.name == "Codex CLI"), None)
    if profile is None:
        profile = AIProviderProfile(
            id=uuid4(),
            name="Codex CLI",
            provider_type="codex",
            default_model=model,
            secret_ref=None,
            settings=default_codex_provider_settings().model_dump(mode="json"),
            enabled=enabled,
        )
        session.add(profile)
        await session.flush()
    else:
        profile.provider_type = "codex"
        profile.default_model = model
        profile.secret_ref = None
        profile.settings = default_codex_provider_settings().model_dump(mode="json")
        profile.enabled = enabled
    return profile


@router.get("/brand-profiles", response_model=list[BrandProfileOut])
async def list_brand_profiles(session: AsyncSession = SessionDependency):
    return list(await session.scalars(select(BrandProfile).order_by(BrandProfile.name)))


@router.post("/brand-profiles", response_model=BrandProfileOut, status_code=201)
async def create_brand_profile(body: BrandProfileCreate, session: AsyncSession = SessionDependency):
    existing = await session.scalar(select(BrandProfile).where(BrandProfile.name == body.name))
    if existing is not None:
        if _brand_matches(existing, body):
            return existing
        raise HTTPException(409, "Brand profile already exists with different configuration")
    profile = BrandProfile(**_brand_values(body))
    try:
        async with session.begin_nested():
            session.add(profile)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(BrandProfile).where(BrandProfile.name == body.name))
        if existing is None or not _brand_matches(existing, body):
            raise HTTPException(409, "Brand profile already exists with different configuration") from None
        return existing
    await session.commit()
    return profile


@router.patch("/brand-profiles/{brand_profile_id}", response_model=BrandProfileOut)
async def patch_brand_profile(
    brand_profile_id: UUID,
    body: BrandProfilePatch,
    session: AsyncSession = SessionDependency,
):
    profile = await session.get(BrandProfile, brand_profile_id)
    if profile is None:
        raise HTTPException(404, "Brand profile not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    await session.commit()
    return profile


@router.get("/prompt-templates")
async def list_prompt_templates(session: AsyncSession = SessionDependency):
    return list(await session.scalars(select(PromptTemplate).order_by(PromptTemplate.name)))


@router.post("/prompt-templates", status_code=201)
async def create_prompt_template(
    body: PromptTemplateCreate,
    session: AsyncSession = SessionDependency,
):
    existing = await session.scalar(select(PromptTemplate).where(PromptTemplate.purpose_key == body.purpose_key))
    if existing is not None:
        if _template_matches(existing, body):
            return existing
        raise HTTPException(409, "Prompt template purpose already exists with different configuration")
    template = PromptTemplate(**body.model_dump())
    try:
        async with session.begin_nested():
            session.add(template)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(PromptTemplate).where(PromptTemplate.purpose_key == body.purpose_key))
        if existing is None or not _template_matches(existing, body):
            raise HTTPException(409, "Prompt template purpose already exists with different configuration") from None
        return existing
    await session.commit()
    return template


@router.post("/prompt-templates/{prompt_template_id}/versions", status_code=201)
async def create_prompt_version(
    prompt_template_id: UUID,
    body: PromptTemplateVersionCreate,
    session: AsyncSession = SessionDependency,
):
    template = await session.scalar(
        select(PromptTemplate).where(PromptTemplate.id == prompt_template_id).with_for_update()
    )
    if template is None:
        raise HTTPException(404, "Prompt template not found")
    if template.purpose_key == "telegram_rewrite":
        try:
            validate_prompt_template_fields(
                body.user_template,
                required=_TELEGRAM_REWRITE_VARIABLES,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        output_schema = _TELEGRAM_REWRITE_SCHEMA
        output_schema_version = "telegram_rewrite.v1"
    elif template.purpose_key in _EDITORIAL_PROMPT_CONTRACTS:
        variables, output_schema_version, output_schema = _EDITORIAL_PROMPT_CONTRACTS[template.purpose_key]
        try:
            validate_prompt_template_fields(body.user_template, required=variables)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    else:
        output_schema = {}
        output_schema_version = f"{template.purpose_key}.v1"
    versions = list(
        await session.scalars(
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.prompt_template_id == prompt_template_id)
            .order_by(PromptTemplateVersion.version)
            .with_for_update()
        )
    )
    version_number = max((item.version for item in versions), default=0) + 1
    checksum = prompt_checksum(body.system_template, body.user_template, output_schema)
    version = PromptTemplateVersion(
        prompt_template_id=prompt_template_id,
        version=version_number,
        system_template=body.system_template,
        user_template=body.user_template,
        output_schema_version=output_schema_version,
        output_schema=output_schema,
        checksum_sha256=checksum,
        is_active=False,
    )
    session.add(version)
    await session.flush()
    await session.commit()
    return version


@router.get(
    "/prompt-templates/{prompt_template_id}/versions",
    response_model=list[PromptTemplateVersionOut],
)
async def list_prompt_versions(
    prompt_template_id: UUID,
    session: AsyncSession = SessionDependency,
):
    if await session.get(PromptTemplate, prompt_template_id) is None:
        raise HTTPException(404, "Prompt template not found")
    return list(
        await session.scalars(
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.prompt_template_id == prompt_template_id)
            .order_by(PromptTemplateVersion.version.desc())
        )
    )


@router.post("/prompt-template-versions/{version_id}/activate")
async def activate_prompt_version(version_id: UUID, session: AsyncSession = SessionDependency):
    version = await session.get(PromptTemplateVersion, version_id)
    if version is None:
        raise HTTPException(404, "Prompt template version not found")
    siblings = list(
        await session.scalars(
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.prompt_template_id == version.prompt_template_id)
            .with_for_update()
        )
    )
    for sibling in siblings:
        sibling.is_active = sibling.id == version.id
    await session.commit()
    return version


@router.get("/ai-provider-profiles", response_model=list[AIProviderProfileOut])
async def list_provider_profiles(
    session: AsyncSession = SessionDependency,
    secrets: SecretResolverDependency = None,
    executable_resolver: ExecutableResolverDependency = shutil.which,
):
    rows = list(await session.scalars(select(AIProviderProfile).order_by(AIProviderProfile.name)))
    return [_profile_out(row, secrets, executable_resolver) for row in rows]


@router.post("/ai-provider-profiles", response_model=AIProviderProfileOut, status_code=201)
async def create_provider_profile(
    body: AIProviderProfileCreate,
    session: AsyncSession = SessionDependency,
    secrets: SecretResolverDependency = None,
    executable_resolver: ExecutableResolverDependency = shutil.which,
):
    existing = await session.scalar(select(AIProviderProfile).where(AIProviderProfile.name == body.name))
    if existing is not None:
        if _provider_matches(existing, body):
            return _profile_out(existing, secrets, executable_resolver)
        raise HTTPException(409, "AI provider profile already exists with different configuration")
    profile = AIProviderProfile(**_provider_values(body))
    try:
        async with session.begin_nested():
            session.add(profile)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(AIProviderProfile).where(AIProviderProfile.name == body.name))
        if existing is None or not _provider_matches(existing, body):
            raise HTTPException(409, "AI provider profile already exists with different configuration") from None
        return _profile_out(existing, secrets, executable_resolver)
    await session.commit()
    return _profile_out(profile, secrets, executable_resolver)


@router.patch("/ai-provider-profiles/{provider_profile_id}", response_model=AIProviderProfileOut)
async def patch_provider_profile(
    provider_profile_id: UUID,
    body: AIProviderProfilePatch,
    session: AsyncSession = SessionDependency,
    secrets: SecretResolverDependency = None,
    executable_resolver: ExecutableResolverDependency = shutil.which,
):
    profile = await session.get(AIProviderProfile, provider_profile_id)
    if profile is None:
        raise HTTPException(404, "AI provider profile not found")
    patch = body.model_dump(exclude_unset=True)
    settings_supplied = "settings" in patch
    settings_patch = patch.pop("settings", None)
    complete = {
        "name": patch.get("name", profile.name),
        "provider_type": profile.provider_type,
        "default_model": patch.get("default_model", profile.default_model),
        "secret_ref": patch.get("secret_ref", profile.secret_ref),
        "settings": (
            None
            if settings_supplied and settings_patch is None
            else merge_provider_settings(dict(profile.settings or {}), settings_patch)
            if settings_supplied
            else (dict(profile.settings or {}) or None)
        ),
        "enabled": patch.get("enabled", profile.enabled),
    }
    try:
        validated = AIProviderProfileCreate.model_validate(complete)
    except ValidationError as exc:
        detail = [
            {key: value for key, value in error.items() if key in {"type", "loc", "msg"}}
            for error in exc.errors(include_url=False)
        ]
        raise HTTPException(422, detail=detail) from None
    profile.name = validated.name
    profile.default_model = validated.default_model
    profile.secret_ref = validated.secret_ref
    profile.settings = _validated_settings(validated.provider_type, validated.settings)
    profile.enabled = validated.enabled
    await session.commit()
    return _profile_out(profile, secrets, executable_resolver)
