from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.capabilities import CapabilityStatusDependency
from app.api.generation_schemas import (
    AIProviderProfileOut,
    BrandProfileCreate,
    BrandProfileOut,
    BrandProfilePatch,
    PromptActivationCreate,
    PromptTemplateCreate,
    PromptTemplateVersionCreate,
    PromptTemplateVersionOut,
)
from app.db.session import get_session
from app.generation.canonical import CanonicalStoryOutput
from app.generation.default_prompts import (
    manual_generation_provider_schema,
    prompt_checksum,
    validate_prompt_template_fields,
)
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplate, PromptTemplateVersion
from app.generation.platform_schemas import BlogVariantPayload, InstagramVariantPayload, XVariantPayload
from app.generation.provider_settings import default_codex_provider_settings
from app.generation.telegram_schema import TelegramRewriteOutput
from app.jobs.credential_capabilities import CapabilityStatus, CapabilityStatusService, provider_shape_capabilities
from app.security.auth import SecurityPrincipal

router = APIRouter(tags=["generation-settings"])
SessionDependency = Depends(get_session)


def _security_principal(request: Request) -> SecurityPrincipal:
    principal = getattr(request.state, "security_principal", None)
    if not isinstance(principal, SecurityPrincipal):
        raise HTTPException(401, {"code": "authentication_required"})
    return principal


PrincipalDependency = Annotated[SecurityPrincipal, Depends(_security_principal)]

_TELEGRAM_REWRITE_VARIABLES = (
    "source_text",
    "source_url",
    "source_channel",
    "language",
    "direction",
    "attribution_policy",
    "custom_footer",
)
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
    "instagram_pack": (
        (
            "canonical_story_json",
            "brand_profile_json",
            "platform_limits_json",
            "source_media_json",
            "instruction",
        ),
        "instagram_pack.v1",
        manual_generation_provider_schema(InstagramVariantPayload),
    ),
    "x_pack": (
        (
            "canonical_story_json",
            "brand_profile_json",
            "platform_limits_json",
            "source_media_json",
            "instruction",
        ),
        "x_pack.v1",
        manual_generation_provider_schema(XVariantPayload),
    ),
    "blog_pack": (
        (
            "canonical_story_json",
            "brand_profile_json",
            "platform_limits_json",
            "source_media_json",
            "instruction",
        ),
        "blog_pack.v1",
        manual_generation_provider_schema(BlogVariantPayload),
    ),
}


def _validate_prompt_variables(
    system_template: str,
    user_template: str,
    *,
    required: tuple[str, ...],
) -> None:
    validate_prompt_template_fields(system_template, required=(), allowed=required)
    validate_prompt_template_fields(user_template, required=required)


def _prompt_validation_error(exc: ValueError) -> HTTPException:
    return HTTPException(
        422,
        {
            "code": "prompt_template_invalid",
            "message": str(exc),
        },
    )


async def _profile_out(
    profile: AIProviderProfile,
    capability_status: CapabilityStatusService,
) -> AIProviderProfileOut:
    shaped, codes = provider_shape_capabilities(profile)
    capability_states: dict[Literal["generation", "research"], CapabilityStatus] = {
        "generation": await capability_status.get("provider", profile.id, "generation"),
        "research": await capability_status.get("provider", profile.id, "research"),
    }
    capabilities: dict[Literal["generation", "research"], bool] = {
        name: shaped[name] and state.available for name, state in capability_states.items()
    }
    for state in capability_states.values():
        if not state.available and state.failure_code not in codes:
            codes.append(state.failure_code)
    generation = capabilities["generation"]
    research = capabilities["research"]
    return AIProviderProfileOut(
        id=profile.id,
        name=profile.name,
        provider_type=profile.provider_type,
        default_model=profile.default_model,
        settings=dict(profile.settings or {}),
        enabled=profile.enabled,
        configured=generation or research,
        capabilities=capabilities,
        capability_states=capability_states,
        unavailability_codes=codes,
    )


def _brand_values(body: BrandProfileCreate) -> dict:
    return body.model_dump(mode="json")


def _brand_matches(profile: BrandProfile, body: BrandProfileCreate) -> bool:
    return all(getattr(profile, key) == value for key, value in _brand_values(body).items())


def _brand_conflict() -> HTTPException:
    return HTTPException(
        409,
        {
            "code": "editorial_profile_conflict",
            "message": "Editorial profile name or default selection conflicts with another profile.",
        },
    )


async def _clear_other_default_profiles(
    session: AsyncSession,
    *,
    keep_id: UUID | None = None,
) -> None:
    profiles = list(
        await session.scalars(select(BrandProfile).where(BrandProfile.is_default.is_(True)).with_for_update())
    )
    for profile in profiles:
        if profile.id != keep_id:
            profile.is_default = False


def _template_matches(template: PromptTemplate, body: PromptTemplateCreate) -> bool:
    return template.name == body.name and template.description == body.description


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
    return profile


@router.get("/brand-profiles", response_model=list[BrandProfileOut])
async def list_brand_profiles(session: AsyncSession = SessionDependency):
    return list(await session.scalars(select(BrandProfile).order_by(BrandProfile.is_default.desc(), BrandProfile.name)))


@router.post("/brand-profiles", response_model=BrandProfileOut, status_code=201)
async def create_brand_profile(body: BrandProfileCreate, session: AsyncSession = SessionDependency):
    existing = await session.scalar(select(BrandProfile).where(BrandProfile.name == body.name))
    if existing is not None:
        if _brand_matches(existing, body):
            return existing
        raise _brand_conflict()
    profile = BrandProfile(**_brand_values(body))
    try:
        async with session.begin_nested():
            if body.is_default:
                await _clear_other_default_profiles(session)
            session.add(profile)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(BrandProfile).where(BrandProfile.name == body.name))
        if existing is None or not _brand_matches(existing, body):
            raise _brand_conflict() from None
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
        raise HTTPException(
            404,
            {
                "code": "editorial_profile_not_found",
                "message": "Editorial profile was not found.",
            },
        )
    changes = body.model_dump(exclude_unset=True)
    if changes.get("is_default") is True:
        await _clear_other_default_profiles(session, keep_id=profile.id)
    for key, value in changes.items():
        setattr(profile, key, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _brand_conflict() from None
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
            _validate_prompt_variables(
                body.system_template,
                body.user_template,
                required=_TELEGRAM_REWRITE_VARIABLES,
            )
        except ValueError as exc:
            raise _prompt_validation_error(exc) from None
        output_schema = TelegramRewriteOutput.model_json_schema()
        output_schema_version = "telegram_rewrite.v1"
    elif template.purpose_key in _EDITORIAL_PROMPT_CONTRACTS:
        variables, output_schema_version, output_schema = _EDITORIAL_PROMPT_CONTRACTS[template.purpose_key]
        try:
            _validate_prompt_variables(
                body.system_template,
                body.user_template,
                required=variables,
            )
        except ValueError as exc:
            raise _prompt_validation_error(exc) from None
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


@router.post(
    "/prompt-template-versions/{version_id}/activate",
    response_model=PromptTemplateVersionOut,
)
async def activate_prompt_version(
    version_id: UUID,
    body: PromptActivationCreate,
    principal: PrincipalDependency,
    session: AsyncSession = SessionDependency,
):
    candidate = await session.get(PromptTemplateVersion, version_id)
    if candidate is None:
        raise HTTPException(404, "Prompt template version not found")
    template = await session.scalar(
        select(PromptTemplate).where(PromptTemplate.id == candidate.prompt_template_id).with_for_update()
    )
    if template is None:
        raise HTTPException(404, "Prompt template not found")
    siblings = list(
        await session.scalars(
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.prompt_template_id == template.id)
            .order_by(PromptTemplateVersion.id)
            .with_for_update()
        )
    )
    version = next((item for item in siblings if item.id == version_id), None)
    if version is None:
        raise HTTPException(404, "Prompt template version not found")
    for sibling in siblings:
        sibling.is_active = False
    await session.flush()
    version.is_active = True
    version.activated_at = datetime.now(UTC)
    version.activated_by_type = principal.principal_type
    version.activated_by_id = principal.principal_id
    version.activation_reason = body.reason
    await session.flush()
    await session.commit()
    return version


@router.get("/ai-provider-profiles", response_model=list[AIProviderProfileOut])
async def list_provider_profiles(
    capability_status: CapabilityStatusDependency,
    session: AsyncSession = SessionDependency,
):
    rows = list(await session.scalars(select(AIProviderProfile).order_by(AIProviderProfile.name)))
    return [await _profile_out(row, capability_status) for row in rows]
