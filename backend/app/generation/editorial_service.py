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
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.telegram_schema import (
    TelegramEvidenceCitation,
    TelegramRewriteOutput,
    TelegramVariantContent,
)
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.research.citations import validate_citations
from app.research.schemas import CitationRef, Claim
from app.research.service import ResearchRequestError, ResearchService
from app.stories.evidence import EvidenceRecord
from app.stories.models import Story, StoryEvidenceSnapshot


class InvalidGenerationRequest(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


class GeneratePackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_profile_id: UUID
    platform: Literal["telegram"]
    generation_provider_profile_id: UUID
    canonical_prompt_template_version_id: UUID
    platform_prompt_template_version_id: UUID
    research_mode: Literal["off", "manual", "auto_if_incomplete"] = "off"
    research_provider_profile_id: UUID | None = None


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
    platform_prompt_template_version_id: UUID
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

    async def _require_profile(self, profile_id: UUID) -> AIProviderProfile:
        profile = await self.session.scalar(
            select(AIProviderProfile).where(AIProviderProfile.id == profile_id).with_for_update()
        )
        if profile is None or not profile.enabled or not profile.default_model:
            raise InvalidGenerationRequest("generation provider profile is unavailable")
        if self.profile_resolver is not None:
            try:
                validate = getattr(self.profile_resolver, "validate_availability", None)
                if validate is None:
                    validate = self.profile_resolver.resolve
                await validate(profile, None)
            except Exception:
                raise InvalidGenerationRequest("generation provider profile is unavailable") from None
        return profile

    async def request_content_pack(self, story_id: UUID, request: GeneratePackRequest) -> JobAcceptedOut:
        canonical, platform = await self.require_active_prompt_versions(
            canonical_id=request.canonical_prompt_template_version_id,
            platform_id=request.platform_prompt_template_version_id,
        )
        await self._require_profile(request.generation_provider_profile_id)
        story = await self.session.scalar(
            select(Story).where(Story.id == story_id, Story.superseded_by_id.is_(None)).with_for_update()
        )
        if story is None:
            raise InvalidGenerationRequest("active story not found")
        if await self.session.get(BrandProfile, request.brand_profile_id) is None:
            raise InvalidGenerationRequest("brand profile not found")
        if request.research_mode == "auto_if_incomplete" and request.research_provider_profile_id is None:
            raise InvalidGenerationRequest("auto research requires research_provider_profile_id")
        payload = request.model_dump(mode="json") | {
            "story_id": str(story_id),
            "canonical_prompt_checksum": canonical.checksum_sha256,
            "platform_prompt_checksum": platform.checksum_sha256,
        }
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
        parent = await self.session.scalar(
            select(PlatformVariantRevision)
            .where(
                PlatformVariantRevision.id == request.base_revision_id,
                PlatformVariantRevision.platform_variant_id == variant_id,
            )
            .with_for_update()
        )
        if variant is None or parent is None:
            raise RevisionConflict("base revision not found")
        if parent.content_hash != request.base_content_hash:
            raise RevisionConflict("content hash changed")
        citations = [TelegramEvidenceCitation.model_validate(item) for item in parent.evidence_map or []]
        if not citations:
            raise InvalidGenerationRequest("revision evidence map is empty")
        snapshots = list(
            await self.session.scalars(
                select(StoryEvidenceSnapshot).where(
                    StoryEvidenceSnapshot.id.in_([item.evidence_snapshot_id for item in citations])
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
            media_assets = list(
                await self.session.scalars(select(MediaAsset).where(MediaAsset.id.in_(requested_media_ids)))
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
            validation_results=[{"gate": "telegram_schema", "ok": True}],
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
        if revision.approval_state != "pending_review":
            raise RevisionConflict("revision is not pending review")
        revision.approval_state = "approved"
        revision.approval_note = request.note
        revision.approved_at = datetime.now(UTC)
        self._event("content_pack.revision.approved", revision)
        await self.session.flush()
        return revision

    async def reject_revision(self, revision_id: UUID, request: ApprovalRequest) -> PlatformVariantRevision:
        revision = await self.session.scalar(
            select(PlatformVariantRevision).where(PlatformVariantRevision.id == revision_id).with_for_update()
        )
        if revision is None or revision.content_hash != request.expected_content_hash:
            raise RevisionConflict("content hash changed")
        if revision.approval_state != "pending_review":
            raise RevisionConflict("revision is not pending review")
        revision.approval_state = "rejected"
        revision.approval_note = request.note
        revision.approved_at = None
        self._event("content_pack.revision.rejected", revision)
        await self.session.flush()
        return revision

    async def regenerate_variant(self, variant_id: UUID, request: RegenerateVariantRequest) -> JobAcceptedOut:
        await self._require_profile(request.generation_provider_profile_id)
        prompt = await self.session.scalar(
            select(PromptTemplateVersion)
            .join(PromptTemplate)
            .where(
                PromptTemplateVersion.id == request.platform_prompt_template_version_id,
                PromptTemplateVersion.is_active.is_(True),
                PromptTemplate.purpose_key == "telegram_pack",
            )
            .with_for_update()
        )
        if prompt is None:
            raise InvalidGenerationRequest("requires active telegram_pack prompt version")
        payload = request.model_dump(mode="json") | {"variant_id": str(variant_id)}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result = await self.jobs.enqueue_job(
            job_type="content_pack.regenerate",
            payload=payload,
            idempotency_key=f"content-pack-regenerate:{variant_id}:{digest}",
            origin=JobOrigin.MANUAL,
        )
        return _job_out(result)

    def _event(self, event_type: str, revision: PlatformVariantRevision) -> None:
        self.session.add(
            WorkflowEvent(
                workflow_job_id=None,
                event_type=event_type,
                actor="operator",
                event_data=redact_event_data({"revision_id": str(revision.id), "content_hash": revision.content_hash}),
            )
        )
