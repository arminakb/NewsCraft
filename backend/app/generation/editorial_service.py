from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.commands import ApprovalRequest, EditVariantRequest, GeneratePackRequest, RegenerateVariantRequest
from app.generation.errors import InvalidGenerationRequest, RevisionConflict
from app.generation.models import (
    AIProviderProfile,
    ContentPack,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.multiplatform import (
    PLATFORM_PROMPT_PURPOSE,
    ordered_distinct_citations,
    payload_claims,
)
from app.generation.package_evidence import (
    LockedEvidenceStage,
    LockedStoryEvidenceError,
    load_locked_story_evidence,
)
from app.generation.platform_media import trusted_story_media, validate_payload_media_assignments
from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    ManualPlatformEditRequest,
    Platform,
    PlatformPayload,
    XVariantPayload,
)
from app.generation.platform_validation import validate_platform_payload
from app.generation.provider_identity import (
    ProviderConfigurationIdentity,
)
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.research.citations import CitationIntegrityError, validate_citations
from app.research.schemas import CitationRef, Claim
from app.stories.evidence import EvidenceRecord
from app.stories.models import StoryRevision


def _job_out(result: Any) -> JobAcceptedOut:
    return JobAcceptedOut(job_id=result.job.id, status=result.job.status, deduplicated=not result.created)


_LOCKED_EVIDENCE_MESSAGES: dict[LockedEvidenceStage, str] = {
    "citations_invalid": "story revision citations are invalid",
    "citations_missing": "story revision citations are empty",
    "evidence_missing": "story revision evidence is missing",
    "citation_integrity": "story revision evidence no longer matches",
}


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
        from app.generation.provider_profiles import require_generation_profile

        return await require_generation_profile(self.session, self.profile_resolver, profile_id)

    async def request_content_pack(
        self,
        story_id: UUID,
        request: GeneratePackRequest,
        *,
        evaluation_run_id: UUID | None = None,
    ) -> JobAcceptedOut:
        from app.generation.request_pack import request_content_pack

        return await request_content_pack(
            self,
            story_id,
            request,
            evaluation_run_id=evaluation_run_id,
        )

    async def edit_variant(
        self, variant_id: UUID, request: EditVariantRequest | None = None, **kwargs: Any
    ) -> PlatformVariantRevision:
        from app.generation.manual_edit import edit_variant

        return await edit_variant(self, variant_id, request, **kwargs)

    async def approve_revision(
        self, revision_id: UUID, request: ApprovalRequest | None = None, **kwargs: Any
    ) -> PlatformVariantRevision:
        from app.generation.review_decisions import approve_revision

        return await approve_revision(self, revision_id, request, **kwargs)

    async def reject_revision(self, revision_id: UUID, request: ApprovalRequest) -> PlatformVariantRevision:
        from app.generation.review_decisions import reject_revision

        return await reject_revision(self, revision_id, request)

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

    async def _evidence_records(self, story_revision: StoryRevision) -> dict[UUID, EvidenceRecord]:
        try:
            _citations, records = await load_locked_story_evidence(self.session, story_revision)
        except LockedStoryEvidenceError as error:
            raise InvalidGenerationRequest(
                _LOCKED_EVIDENCE_MESSAGES[error.stage],
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
        platform: Platform
        payload: PlatformPayload
        try:
            if variant.platform == "instagram":
                platform = "instagram"
                payload = InstagramVariantPayload.model_validate(revision.content)
            elif variant.platform == "x":
                platform = "x"
                payload = XVariantPayload.model_validate(revision.content)
            elif variant.platform == "blog":
                platform = "blog"
                payload = BlogVariantPayload.model_validate(revision.content)
            else:
                raise InvalidGenerationRequest("manual platform is unsupported")
        except ValueError:
            raise InvalidGenerationRequest("stored platform content is invalid") from None
        issues = validate_platform_payload(platform, payload)
        if any(issue.severity == "error" for issue in issues):
            raise InvalidGenerationRequest("revision has a failed validation gate")
        expected = [item.model_dump(mode="json") for item in ordered_distinct_citations(payload)]
        if revision.evidence_map != expected:
            raise InvalidGenerationRequest("citation integrity failed", code="citation_integrity")
        records = await self._evidence_records(await self._pack_story_revision(variant))
        try:
            validate_citations(payload_claims(platform, payload), records)
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
        from app.generation.manual_edit import edit_manual_platform_variant

        return await edit_manual_platform_variant(self, variant_id, request)

    def _event(self, event_type: str, revision: PlatformVariantRevision) -> None:
        self.session.add(
            WorkflowEvent(
                workflow_job_id=None,
                event_type=event_type,
                actor="operator",
                event_data=redact_event_data({"revision_id": str(revision.id), "content_hash": revision.content_hash}),
            )
        )
