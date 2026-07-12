from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID

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
)
from app.api.telegram_destinations import get_secret_resolver
from app.core.secrets import SecretResolver
from app.db.session import get_session
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplate, PromptTemplateVersion
from app.generation.provider_settings import merge_provider_settings

router = APIRouter(tags=["generation-settings"])
SessionDependency = Depends(get_session)
SecretResolverDependency = Annotated[SecretResolver, Depends(get_secret_resolver)]

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


def _profile_out(profile: AIProviderProfile, secrets: SecretResolver) -> AIProviderProfileOut:
    configured = profile.provider_type == "fake" or bool(
        profile.secret_ref and secrets.configured(profile.secret_ref)
    )
    return AIProviderProfileOut(
        id=profile.id,
        name=profile.name,
        provider_type=profile.provider_type,
        default_model=profile.default_model,
        settings=dict(profile.settings or {}),
        enabled=profile.enabled,
        configured=configured,
    )


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
        "settings": body.settings.model_dump(mode="json") if body.settings is not None else {},
        "enabled": body.enabled,
    }


def _provider_matches(profile: AIProviderProfile, body: AIProviderProfileCreate) -> bool:
    return all(getattr(profile, key) == value for key, value in _provider_values(body).items())
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
    existing = await session.scalar(
        select(PromptTemplate).where(PromptTemplate.purpose_key == body.purpose_key)
    )
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
        existing = await session.scalar(
            select(PromptTemplate).where(PromptTemplate.purpose_key == body.purpose_key)
        )
        if existing is None or not _template_matches(existing, body):
            raise HTTPException(
                409, "Prompt template purpose already exists with different configuration"
            ) from None
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
        select(PromptTemplate)
        .where(PromptTemplate.id == prompt_template_id)
        .with_for_update()
    )
    if template is None:
        raise HTTPException(404, "Prompt template not found")
    if template.purpose_key == "telegram_rewrite":
        missing = [name for name in _TELEGRAM_REWRITE_VARIABLES if f"{{{name}}}" not in body.user_template]
        if missing:
            raise HTTPException(422, f"Telegram prompt is missing variables: {', '.join(missing)}")
        output_schema = _TELEGRAM_REWRITE_SCHEMA
        output_schema_version = "telegram_rewrite.v1"
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
    checksum_payload = {
        "system_template": body.system_template,
        "user_template": body.user_template,
        "output_schema": output_schema,
    }
    checksum = hashlib.sha256(
        json.dumps(checksum_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
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
):
    rows = list(await session.scalars(select(AIProviderProfile).order_by(AIProviderProfile.name)))
    return [_profile_out(row, secrets) for row in rows]


@router.post("/ai-provider-profiles", response_model=AIProviderProfileOut, status_code=201)
async def create_provider_profile(
    body: AIProviderProfileCreate,
    session: AsyncSession = SessionDependency,
    secrets: SecretResolverDependency = None,
):
    existing = await session.scalar(select(AIProviderProfile).where(AIProviderProfile.name == body.name))
    if existing is not None:
        if _provider_matches(existing, body):
            return _profile_out(existing, secrets)
        raise HTTPException(409, "AI provider profile already exists with different configuration")
    profile = AIProviderProfile(**_provider_values(body))
    try:
        async with session.begin_nested():
            session.add(profile)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(AIProviderProfile).where(AIProviderProfile.name == body.name)
        )
        if existing is None or not _provider_matches(existing, body):
            raise HTTPException(
                409, "AI provider profile already exists with different configuration"
            ) from None
        return _profile_out(existing, secrets)
    await session.commit()
    return _profile_out(profile, secrets)


@router.patch("/ai-provider-profiles/{provider_profile_id}", response_model=AIProviderProfileOut)
async def patch_provider_profile(
    provider_profile_id: UUID,
    body: AIProviderProfilePatch,
    session: AsyncSession = SessionDependency,
    secrets: SecretResolverDependency = None,
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
    profile.settings = validated.settings.model_dump(mode="json") if validated.settings else {}
    profile.enabled = validated.enabled
    await session.commit()
    return _profile_out(profile, secrets)
