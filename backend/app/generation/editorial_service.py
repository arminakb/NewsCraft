from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.telegram.handlers import sha256_canonical
from app.db.models import ItemMedia, MediaAsset, SourceItem
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    ContentPack,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.multiplatform import (
    PLATFORM_PROMPT_PURPOSE,
    deduplicate_preserving_order,
    ordered_distinct_citations,
    payload_claims,
)
from app.generation.platform_media import trusted_story_media, validate_payload_media_assignments
from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    ManualPlatformEditRequest,
    Platform,
    TelegramVariantPayload,
    XVariantPayload,
)
from app.generation.platform_validation import revision_gates_from_issues, validate_platform_payload
from app.generation.provider_identity import (
    ProviderConfigurationIdentity,
    is_qualified_generation_profile,
    provider_identity_for_profile,
)
from app.generation.revision_fence import RegenerationFenceConflict, require_revision_write_allowed
from app.generation.revision_validation import RevisionValidationError, validate_approvable_revision
from app.generation.telegram_schema import (
    TelegramEvidenceCitation,
    TelegramRewriteOutput,
    TelegramVariantContent,
)
from app.jobs.credential_capabilities import provider_shape_capabilities
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.media.reference_fence import fence_platform_revision_media_write
from app.research.citations import CitationIntegrityError, validate_citations
from app.research.models import ResearchRun
from app.research.schemas import CitationRef, Claim
from app.research.service import ResearchRequestError, ResearchService
from app.stories.evidence import EvidenceRecord
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision
from app.workflows.errors import EditorialValidationError, StaleRevisionError
from app.workflows.states import require_content_pack_transition, require_variant_approval_transition


class InvalidGenerationRequest(EditorialValidationError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message, code=code)


class RevisionConflict(StaleRevisionError):
    pass


class GeneratePackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_profile_id: UUID | None = None
    platforms: list[Platform] = Field(min_length=1)
    generation_provider_profile_id: UUID
    research_mode: Literal["off", "manual", "auto_if_incomplete"] = "off"
    research_provider_profile_id: UUID | None = None
    research_run_id: UUID | None = None


class EditVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision_id: UUID
    base_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: TelegramRewriteOutput
    media_asset_ids: list[UUID]
    edit_note: str = Field(min_length=1, max_length=500)


class RegenerateVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_provider_profile_id: UUID
    instruction: str | None = Field(default=None, max_length=1_000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=500)


def _job_out(result: Any) -> JobAcceptedOut:
    return JobAcceptedOut(job_id=result.job.id, status=result.job.status, deduplicated=not result.created)


class EditorialService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        jobs: JobRepository | None = None,
        profile_resolver: Any | None = None,
    ) -> None:
        self.session = session
        self.jobs = jobs or JobRepository(session)
        self.profile_resolver = profile_resolver

    async def require_active_prompt_versions(
        self,
        *,
        canonical_id: UUID,
        canonical_purpose: str = "canonical_story",
        platform_id: UUID,
        platform_purpose: str = "telegram_pack",
    ) -> tuple[PromptTemplateVersion, PromptTemplateVersion]:
        async def require(version_id: UUID, purpose: str) -> PromptTemplateVersion:
            row = await self.session.scalar(
                select(PromptTemplateVersion)
                .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.prompt_template_id)
                .where(
                    PromptTemplateVersion.id == version_id,
                    PromptTemplateVersion.is_active.is_(True),
                    PromptTemplate.purpose_key == purpose,
                )
                .with_for_update()
            )
            if row is None:
                raise InvalidGenerationRequest(f"requires active {purpose} prompt version")
            return row

        return await require(canonical_id, canonical_purpose), await require(platform_id, platform_purpose)

    async def require_active_prompt_version(self, purpose: str) -> PromptTemplateVersion:
        # Enqueue-time prompt selection is a snapshot only. Workers lock and
        # exact-revalidate the selected ID/checksum immediately before use, so
        # holding this row behind Story/Variant locks only creates inversions.
        rows = list(
            await self.session.scalars(
                select(PromptTemplateVersion)
                .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.prompt_template_id)
                .where(
                    PromptTemplateVersion.is_active.is_(True),
                    PromptTemplate.purpose_key == purpose,
                )
            )
        )
        if len(rows) != 1:
            raise InvalidGenerationRequest(f"requires exactly one active {purpose} prompt version")
        return rows[0]

    async def _require_profile(self, profile_id: UUID) -> tuple[AIProviderProfile, ProviderConfigurationIdentity]:
        profile = await self.session.scalar(
            select(AIProviderProfile).where(AIProviderProfile.id == profile_id).with_for_update()
        )
        if profile is None or not profile.enabled or not profile.default_model:
            raise InvalidGenerationRequest("generation provider profile is unavailable")
        from app.llm_providers.models import LLMProvider

        generic = await self.session.get(LLMProvider, profile_id) if isinstance(self.session, AsyncSession) else None
        if generic is None:
            shaped, _codes = provider_shape_capabilities(profile)
            if not shaped["generation"]:
                raise InvalidGenerationRequest("generation provider profile is unavailable")
        elif not generic.enabled or generic.generation_capability != "ready":
            raise InvalidGenerationRequest("generation provider profile is unavailable")
        resolved = None
        if self.profile_resolver is not None:
            try:
                validate_with_session = getattr(
                    self.profile_resolver,
                    "validate_availability_with_session",
                    None,
                )
                if validate_with_session is not None:
                    resolved = await validate_with_session(profile, None, session=self.session)
                else:
                    validate = getattr(self.profile_resolver, "validate_availability", None)
                    if validate is None:
                        validate = self.profile_resolver.resolve
                    resolved = await validate(profile, None)
            except Exception:
                raise InvalidGenerationRequest("generation provider profile is unavailable") from None
        try:
            if not is_qualified_generation_profile(profile):
                raise InvalidGenerationRequest("generation provider profile is not qualified")
        except ValueError:
            raise InvalidGenerationRequest("generation provider profile is unavailable") from None
        if getattr(resolved, "configuration_checksum", None):
            return profile, ProviderConfigurationIdentity(
                revision=resolved.configuration_revision,
                checksum=resolved.configuration_checksum,
            )
        try:
            return profile, provider_identity_for_profile(profile)
        except ValueError:
            raise InvalidGenerationRequest("generation provider profile is unavailable") from None

    async def request_content_pack(
        self,
        story_id: UUID,
        request: GeneratePackRequest,
        *,
        evaluation_run_id: UUID | None = None,
    ) -> JobAcceptedOut:
        platforms = deduplicate_preserving_order(request.platforms)
        canonical = await self.require_active_prompt_version("canonical_story")
        platform_prompts = {
            platform: await self.require_active_prompt_version(PLATFORM_PROMPT_PURPOSE[platform])
            for platform in platforms
        }
        _profile, provider_identity = await self._require_profile(request.generation_provider_profile_id)
        story = await self.session.scalar(
            select(Story).where(Story.id == story_id, Story.superseded_by_id.is_(None)).with_for_update()
        )
        if story is None:
            raise InvalidGenerationRequest("active story not found")
        brand = (
            await self.session.get(BrandProfile, request.brand_profile_id)
            if request.brand_profile_id is not None
            else await self.session.scalar(
                select(BrandProfile).where(BrandProfile.is_default.is_(True)).with_for_update()
            )
        )
        if brand is None:
            message = (
                "brand profile not found"
                if request.brand_profile_id is not None
                else "default editorial profile is not configured"
            )
            raise InvalidGenerationRequest(message, code="editorial_profile_unavailable")
        if request.research_mode == "auto_if_incomplete" and request.research_provider_profile_id is None:
            raise InvalidGenerationRequest("auto research requires research_provider_profile_id")
        if request.research_run_id is not None and (
            request.research_mode != "off" or request.research_provider_profile_id is not None
        ):
            raise InvalidGenerationRequest("bound research run cannot request another research mode")
        bound_payload: dict[str, str] = {}
        if request.research_run_id is not None:
            run = await self.session.get(ResearchRun, request.research_run_id)
            result_revision = (
                await self.session.get(StoryRevision, run.result_story_revision_id)
                if run is not None and run.result_story_revision_id is not None
                else None
            )
            if (
                run is None
                or run.status != "succeeded"
                or run.story_id != story_id
                or result_revision is None
                or result_revision.story_id != story_id
            ):
                raise InvalidGenerationRequest("research run is not a succeeded result for this story")
            bound_payload = {
                "completed_research_run_id": str(run.id),
                "research_result_story_revision_id": str(result_revision.id),
            }
        payload = (
            request.model_dump(
                mode="json",
                exclude={"research_run_id", "brand_profile_id"},
            )
            | bound_payload
            | {
                "story_id": str(story_id),
                "brand_profile_id": str(brand.id),
                "platforms": platforms,
                "canonical_prompt_template_version_id": str(canonical.id),
                "platform_prompt_template_version_ids": {
                    platform: str(prompt.id) for platform, prompt in platform_prompts.items()
                },
                "canonical_prompt_checksum": canonical.checksum_sha256,
                "platform_prompt_checksums": {
                    platform: prompt.checksum_sha256 for platform, prompt in platform_prompts.items()
                },
                "generation_provider_configuration_revision": provider_identity.revision,
                "generation_provider_configuration_checksum": provider_identity.checksum,
            }
        )
        if evaluation_run_id is not None:
            # This is intentionally an internal-only argument. Public request
            # schemas cannot bypass production idempotency.
            payload["evaluation_run_id"] = str(evaluation_run_id)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if request.research_mode == "auto_if_incomplete":
            continuation = {
                "job_type": "content_pack.generate",
                "payload": payload,
                "idempotency_prefix": f"content-pack:{story_id}:{digest}",
                "subscriber_id": digest,
                "expected_story_id": str(story_id),
                "expected_provider_profile_id": str(request.research_provider_profile_id),
            }
            try:
                research = await ResearchService(self.session).request(
                    story_id=story_id,
                    mode="auto_if_incomplete",
                    depth="standard",
                    provider_profile_id=request.research_provider_profile_id,
                    query_hint=None,
                    continuation=continuation,
                )
            except ResearchRequestError as exc:
                raise InvalidGenerationRequest(str(exc)) from None
            if research.disposition == "enqueued":
                assert research.job_id is not None
                research_job = await self.session.get(WorkflowJob, research.job_id)
                if research_job is None:
                    raise InvalidGenerationRequest("research job is unavailable")
                result_out = JobAcceptedOut(
                    job_id=research_job.id,
                    status=research_job.status,
                    deduplicated=False,
                )
            else:
                result_out = _job_out(
                    await self.jobs.enqueue_job(
                        job_type="content_pack.generate",
                        payload=payload,
                        idempotency_key=f"content-pack:{story_id}:{digest}",
                        origin=JobOrigin.MANUAL,
                    )
                )
        else:
            result_out = _job_out(
                await self.jobs.enqueue_job(
                    job_type="content_pack.generate",
                    payload=payload,
                    idempotency_key=f"content-pack:{story_id}:{digest}",
                    origin=JobOrigin.MANUAL,
                )
            )
        await self.session.flush()
        return result_out

    async def edit_variant(
        self, variant_id: UUID, request: EditVariantRequest | None = None, **kwargs: Any
    ) -> PlatformVariantRevision:
        if request is None:
            request = EditVariantRequest(
                base_revision_id=kwargs["base_revision_id"],
                base_content_hash=kwargs["base_content_hash"],
                content=kwargs["content"],
                media_asset_ids=kwargs["media_asset_ids"],
                edit_note=kwargs["edit_note"],
            )
        variant = await self.session.scalar(
            select(PlatformVariant).where(PlatformVariant.id == variant_id).with_for_update()
        )
        if variant is None:
            raise RevisionConflict("base revision not found")
        if variant.platform != "telegram":
            raise RevisionConflict("platform conflicts with Telegram edit")
        try:
            await require_revision_write_allowed(self.session, variant_id=variant.id)
        except RegenerationFenceConflict:
            raise RevisionConflict("variant regeneration is in progress") from None
        parent = await self.session.scalar(
            select(PlatformVariantRevision)
            .where(
                PlatformVariantRevision.id == request.base_revision_id,
                PlatformVariantRevision.platform_variant_id == variant_id,
            )
            .with_for_update()
        )
        if parent is None:
            raise RevisionConflict("base revision not found")
        if parent.content_hash != request.base_content_hash:
            raise RevisionConflict("content hash changed")
        story_revision = await self._pack_story_revision(variant)
        citations = [TelegramEvidenceCitation.model_validate(item) for item in parent.evidence_map or []]
        if not citations:
            raise InvalidGenerationRequest("revision evidence map is empty")
        snapshots = list(
            await self.session.scalars(
                select(StoryEvidenceSnapshot).where(
                    StoryEvidenceSnapshot.id.in_([item.evidence_snapshot_id for item in citations]),
                    StoryEvidenceSnapshot.story_id == story_revision.story_id,
                )
            )
        )
        by_id = {item.id: item for item in snapshots}
        if len(by_id) != len({item.evidence_snapshot_id for item in citations}):
            raise InvalidGenerationRequest("revision evidence snapshot is missing")
        records = {
            item.id: EvidenceRecord(
                evidence_key=item.evidence_key,
                evidence_snapshot_id=item.id,
                content_item_id=item.content_item_id,
                title=item.title,
                content_text=item.content_text,
                content_sha256=item.content_sha256,
                source_url=item.source_url,
                authors=tuple(item.authors or []),
                published_at=item.published_at,
                captured_at=item.captured_at,
            )
            for item in snapshots
        }
        try:
            validate_citations(
                [
                    Claim(
                        text="Preserved Telegram evidence",
                        citations=[CitationRef.model_validate(item.model_dump())],
                    )
                    for item in citations
                ],
                records,
            )
        except ValueError:
            raise InvalidGenerationRequest("revision evidence no longer matches") from None
        parent_content = TelegramVariantContent.model_validate(parent.content)
        requested_media_ids = set(request.media_asset_ids)
        if len(requested_media_ids) != len(request.media_asset_ids):
            raise InvalidGenerationRequest("media asset IDs must be unique")
        if parent_content.media_policy == "omit" and requested_media_ids:
            raise InvalidGenerationRequest("omit-media revisions cannot attach media")
        if requested_media_ids:
            await fence_platform_revision_media_write(self.session)
            media_assets = list(
                await self.session.scalars(
                    select(MediaAsset)
                    .where(MediaAsset.id.in_(requested_media_ids))
                    .order_by(MediaAsset.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if {item.id for item in media_assets} != requested_media_ids:
                raise InvalidGenerationRequest("one or more media assets do not exist")
            if any(
                item.fetch_status != "downloaded" or not item.storage_path or not item.checksum_sha256
                for item in media_assets
            ):
                raise InvalidGenerationRequest("media assets must be checksum-verified")
        if parent_content.media_policy == "preserve":
            if parent_content.source_item_id is None:
                raise InvalidGenerationRequest("preserved media provenance is missing")
            source_item = await self.session.get(SourceItem, parent_content.source_item_id)
            if source_item is None or source_item.content_item_id is None:
                raise InvalidGenerationRequest("preserved media provenance is invalid")
            linked_ids = set(
                await self.session.scalars(
                    select(ItemMedia.media_asset_id).where(ItemMedia.content_item_id == source_item.content_item_id)
                )
            )
            if not requested_media_ids.issubset(linked_ids):
                raise InvalidGenerationRequest("preserved media must belong to the source")
        content = TelegramVariantContent(
            body=request.content.body,
            parse_mode=request.content.parse_mode,
            buttons=request.content.buttons,
            source_item_id=parent_content.source_item_id,
            source_url=parent_content.source_url,
            media_policy=parent_content.media_policy,
            media_asset_ids=request.media_asset_ids,
            direction=parent_content.direction,
            dry_run=parent_content.dry_run,
        ).model_dump(mode="json")
        evidence_map = [item.model_dump(mode="json") for item in citations]
        next_number = (
            int(
                await self.session.scalar(
                    select(func.coalesce(func.max(PlatformVariantRevision.revision_number), 0)).where(
                        PlatformVariantRevision.platform_variant_id == variant_id
                    )
                )
                or 0
            )
            + 1
        )
        child = PlatformVariantRevision(
            platform_variant_id=variant_id,
            parent_revision_id=parent.id,
            generation_attempt_id=None,
            revision_number=next_number,
            content=content,
            content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
            evidence_map=evidence_map,
            validation_results=[{"gate": "telegram_schema", "ok": True, "reason": None}],
            approval_state="pending_review",
            approval_note=request.edit_note,
            created_by="operator",
        )
        self.session.add(child)
        await self.session.flush()
        return child

    async def approve_revision(
        self, revision_id: UUID, request: ApprovalRequest | None = None, **kwargs: Any
    ) -> PlatformVariantRevision:
        if request is None:
            request = ApprovalRequest(expected_content_hash=kwargs["expected_content_hash"], note=kwargs.get("note"))
        revision = await self.session.scalar(
            select(PlatformVariantRevision).where(PlatformVariantRevision.id == revision_id).with_for_update()
        )
        if revision is None:
            raise RevisionConflict("revision not found")
        if revision.content_hash != request.expected_content_hash:
            raise RevisionConflict("content hash changed")
        if revision.content_hash != sha256_canonical(
            {"content": revision.content, "evidence_map": revision.evidence_map}
        ):
            raise InvalidGenerationRequest(
                "stored revision content hash is invalid",
                code="content_integrity",
            )
        if revision.approval_state != "pending_review":
            raise RevisionConflict("revision is not pending review")
        if not revision.evidence_map:
            raise InvalidGenerationRequest("Revision evidence map is empty")
        variant = await self.session.get(PlatformVariant, revision.platform_variant_id)
        if variant is None:
            raise RevisionConflict("variant not found")
        if variant.platform == "telegram":
            try:
                validate_approvable_revision(revision)
                telegram_payload = TelegramVariantPayload.model_validate(revision.content)
                issues = validate_platform_payload("telegram", telegram_payload)
                failed = next((item for item in issues if item.severity == "error"), None)
                if failed is not None:
                    raise InvalidGenerationRequest(failed.message, code=failed.code)
                await self._validate_telegram_revision_evidence(revision)
            except (RevisionValidationError, InvalidGenerationRequest) as exc:
                raise InvalidGenerationRequest(str(exc), code=getattr(exc, "code", None)) from None
        else:
            await self._revalidate_manual_revision(variant, revision)
        latest_id = await self.session.scalar(
            select(PlatformVariantRevision.id)
            .where(PlatformVariantRevision.platform_variant_id == revision.platform_variant_id)
            .order_by(
                PlatformVariantRevision.revision_number.desc(),
                PlatformVariantRevision.created_at.desc(),
                PlatformVariantRevision.id.desc(),
            )
            .limit(1)
        )
        if latest_id != revision.id:
            raise RevisionConflict("revision is not current")
        revision.approval_state = require_variant_approval_transition(revision.approval_state, "approved")
        revision.approval_note = request.note
        revision.approved_at = datetime.now(UTC)
        self._event("content_pack.revision.approved", revision)
        await self.session.flush()
        await self._refresh_pack_status(variant.content_pack_id)
        return revision

    async def reject_revision(self, revision_id: UUID, request: ApprovalRequest) -> PlatformVariantRevision:
        revision = await self.session.scalar(
            select(PlatformVariantRevision).where(PlatformVariantRevision.id == revision_id).with_for_update()
        )
        if revision is None or revision.content_hash != request.expected_content_hash:
            raise RevisionConflict("content hash changed")
        if revision.approval_state != "pending_review":
            raise RevisionConflict("revision is not pending review")
        revision.approval_state = require_variant_approval_transition(revision.approval_state, "rejected")
        revision.approval_note = request.note
        revision.approved_at = None
        self._event("content_pack.revision.rejected", revision)
        await self.session.flush()
        variant = await self.session.get(PlatformVariant, revision.platform_variant_id)
        if variant is not None:
            await self._refresh_pack_status(variant.content_pack_id)
        return revision

    async def regenerate_variant(self, variant_id: UUID, request: RegenerateVariantRequest) -> JobAcceptedOut:
        _profile, provider_identity = await self._require_profile(request.generation_provider_profile_id)
        variant = await self.session.scalar(
            select(PlatformVariant).where(PlatformVariant.id == variant_id).with_for_update()
        )
        if variant is None or variant.platform not in PLATFORM_PROMPT_PURPOSE:
            raise RevisionConflict("variant not found")
        prompt = await self.require_active_prompt_version(PLATFORM_PROMPT_PURPOSE[variant.platform])
        current = await self.session.scalar(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant.id)
            .order_by(
                PlatformVariantRevision.revision_number.desc(),
                PlatformVariantRevision.created_at.desc(),
                PlatformVariantRevision.id.desc(),
            )
            .limit(1)
            .with_for_update()
        )
        if current is None:
            raise RevisionConflict("variant has no current revision")
        payload = request.model_dump(mode="json") | {
            "variant_id": str(variant_id),
            "base_revision_id": str(current.id),
            "base_content_hash": current.content_hash,
            "platforms": [variant.platform],
            "platform_prompt_template_version_ids": {variant.platform: str(prompt.id)},
            "platform_prompt_checksums": {variant.platform: prompt.checksum_sha256},
            "generation_provider_configuration_revision": provider_identity.revision,
            "generation_provider_configuration_checksum": provider_identity.checksum,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result = await self.jobs.enqueue_job(
            job_type="content_pack.regenerate",
            payload=payload,
            idempotency_key=f"content-pack-regenerate:{variant_id}:{digest}",
            origin=JobOrigin.MANUAL,
        )
        return _job_out(result)

    async def _pack_story_revision(self, variant: PlatformVariant) -> StoryRevision:
        pack = await self.session.get(ContentPack, variant.content_pack_id)
        revision = await self.session.get(StoryRevision, pack.story_revision_id) if pack is not None else None
        if revision is None:
            raise InvalidGenerationRequest("content pack story revision is missing")
        return revision

    async def _refresh_pack_status(self, pack_id: UUID) -> None:
        pack = await self.session.scalar(select(ContentPack).where(ContentPack.id == pack_id).with_for_update())
        if pack is None:
            raise RevisionConflict("content pack not found")
        variants = list(
            await self.session.scalars(
                select(PlatformVariant).where(PlatformVariant.content_pack_id == pack_id).order_by(PlatformVariant.id)
            )
        )
        current_states: list[str] = []
        for variant in variants:
            state = await self.session.scalar(
                select(PlatformVariantRevision.approval_state)
                .where(PlatformVariantRevision.platform_variant_id == variant.id)
                .order_by(
                    PlatformVariantRevision.revision_number.desc(),
                    PlatformVariantRevision.created_at.desc(),
                    PlatformVariantRevision.id.desc(),
                )
                .limit(1)
            )
            if state is not None:
                current_states.append(state)
        target = (
            "ready"
            if variants
            and len(current_states) == len(variants)
            and all(state == "approved" for state in current_states)
            else "draft"
        )
        if pack.status != target:
            pack.status = require_content_pack_transition(pack.status, target)
            await self.session.flush()

    async def _evidence_records(self, story_revision: StoryRevision) -> dict[UUID, EvidenceRecord]:
        try:
            citations = [CitationRef.model_validate(item) for item in story_revision.citations]
        except TypeError, ValueError:
            raise InvalidGenerationRequest("story revision citations are invalid", code="citation_integrity") from None
        snapshot_ids = {item.evidence_snapshot_id for item in citations}
        if not snapshot_ids:
            raise InvalidGenerationRequest("story revision citations are empty", code="citation_integrity")
        rows = list(
            await self.session.scalars(
                select(StoryEvidenceSnapshot).where(
                    StoryEvidenceSnapshot.id.in_(snapshot_ids),
                    StoryEvidenceSnapshot.story_id == story_revision.story_id,
                )
            )
        )
        records = {
            row.id: EvidenceRecord(
                evidence_key=row.evidence_key,
                evidence_snapshot_id=row.id,
                content_item_id=row.content_item_id,
                title=row.title,
                content_text=row.content_text,
                content_sha256=row.content_sha256,
                source_url=row.source_url,
                authors=tuple(row.authors or []),
                published_at=row.published_at,
                captured_at=row.captured_at,
            )
            for row in rows
        }
        if set(records) != snapshot_ids:
            raise InvalidGenerationRequest("story revision evidence is missing", code="citation_integrity")
        try:
            validate_citations([Claim(text="Locked story evidence", citations=citations)], records)
        except ValueError:
            raise InvalidGenerationRequest(
                "story revision evidence no longer matches",
                code="citation_integrity",
            ) from None
        return records

    async def _validate_telegram_revision_evidence(self, revision: PlatformVariantRevision) -> None:
        variant = await self.session.get(PlatformVariant, revision.platform_variant_id)
        if variant is None:
            raise InvalidGenerationRequest("variant is missing")
        story_revision = await self._pack_story_revision(variant)
        records = await self._evidence_records(story_revision)
        try:
            expected = [CitationRef.model_validate(item).model_dump(mode="json") for item in story_revision.citations]
            citations = [CitationRef.model_validate(item) for item in revision.evidence_map]
            actual = [item.model_dump(mode="json") for item in citations]
            if actual != expected:
                raise InvalidGenerationRequest(
                    "citation integrity failed",
                    code="citation_integrity",
                )
            validate_citations([Claim(text="Telegram package", citations=citations)], records)
        except InvalidGenerationRequest:
            raise
        except TypeError, ValueError:
            raise InvalidGenerationRequest("citation integrity failed", code="citation_integrity") from None

    async def _revalidate_manual_revision(
        self,
        variant: PlatformVariant,
        revision: PlatformVariantRevision,
    ) -> None:
        payload_types = {
            "instagram": InstagramVariantPayload,
            "x": XVariantPayload,
            "blog": BlogVariantPayload,
        }
        payload_type = payload_types.get(variant.platform)
        if payload_type is None:
            raise InvalidGenerationRequest("manual platform is unsupported")
        try:
            payload = payload_type.model_validate(revision.content)
        except ValueError:
            raise InvalidGenerationRequest("stored platform content is invalid") from None
        issues = validate_platform_payload(variant.platform, payload)
        if any(issue.severity == "error" for issue in issues):
            raise InvalidGenerationRequest("revision has a failed validation gate")
        expected = [item.model_dump(mode="json") for item in ordered_distinct_citations(payload)]
        if revision.evidence_map != expected:
            raise InvalidGenerationRequest("citation integrity failed", code="citation_integrity")
        records = await self._evidence_records(await self._pack_story_revision(variant))
        try:
            validate_citations(payload_claims(variant.platform, payload), records)
        except ValueError:
            raise InvalidGenerationRequest("citation integrity failed", code="citation_integrity") from None
        authorized_media, _projection = await trusted_story_media(
            self.session,
            records,
            lock_rows=True,
        )
        try:
            validate_payload_media_assignments(payload, authorized_media)
        except CitationIntegrityError:
            raise InvalidGenerationRequest("media integrity failed", code="media_integrity") from None

    async def edit_manual_platform_variant(
        self,
        variant_id: UUID,
        request: ManualPlatformEditRequest,
    ) -> PlatformVariantRevision:
        variant = await self.session.scalar(
            select(PlatformVariant).where(PlatformVariant.id == variant_id).with_for_update()
        )
        if variant is None:
            raise RevisionConflict("variant not found")
        if request.payload.platform != variant.platform:
            raise RevisionConflict("platform conflicts with target variant")
        try:
            await require_revision_write_allowed(self.session, variant_id=variant.id)
        except RegenerationFenceConflict:
            raise RevisionConflict("variant regeneration is in progress") from None
        current = await self.session.scalar(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant_id)
            .order_by(
                PlatformVariantRevision.revision_number.desc(),
                PlatformVariantRevision.created_at.desc(),
                PlatformVariantRevision.id.desc(),
            )
            .limit(1)
            .with_for_update()
        )
        if (
            current is None
            or current.id != request.base_revision_id
            or current.content_hash != request.base_content_hash
        ):
            raise RevisionConflict("base revision is stale")
        payload = request.payload.content
        issues = validate_platform_payload(variant.platform, payload)
        failed = next((item for item in issues if item.severity == "error"), None)
        if failed is not None:
            raise InvalidGenerationRequest(failed.message, code=failed.code)
        expected_evidence = [item.model_dump(mode="json") for item in ordered_distinct_citations(payload)]
        supplied_evidence = [item.model_dump(mode="json") for item in request.evidence_map]
        if supplied_evidence != expected_evidence:
            raise InvalidGenerationRequest("citation integrity failed", code="citation_integrity")
        records = await self._evidence_records(await self._pack_story_revision(variant))
        try:
            validate_citations(payload_claims(variant.platform, payload), records)
        except ValueError:
            raise InvalidGenerationRequest("citation integrity failed", code="citation_integrity") from None
        authorized_media, _projection = await trusted_story_media(
            self.session,
            records,
            lock_rows=True,
        )
        try:
            validate_payload_media_assignments(payload, authorized_media)
        except CitationIntegrityError:
            raise InvalidGenerationRequest("media integrity failed", code="media_integrity") from None
        content = payload.model_dump(mode="json")
        child = PlatformVariantRevision(
            platform_variant_id=variant.id,
            parent_revision_id=current.id,
            generation_attempt_id=None,
            revision_number=current.revision_number + 1,
            content=content,
            content_hash=sha256_canonical({"content": content, "evidence_map": supplied_evidence}),
            evidence_map=supplied_evidence,
            validation_results=revision_gates_from_issues(issues),
            approval_state="pending_review",
            approval_note=request.edit_note,
            created_by="operator",
        )
        self.session.add(child)
        await self.session.flush()
        return child

    def _event(self, event_type: str, revision: PlatformVariantRevision) -> None:
        self.session.add(
            WorkflowEvent(
                workflow_job_id=None,
                event_type=event_type,
                actor="operator",
                event_data=redact_event_data({"revision_id": str(revision.id), "content_hash": revision.content_hash}),
            )
        )
