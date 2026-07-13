from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.handlers import (
    enqueue_telegram_publish_intent,
    sha256_canonical,
)
from app.db.models import ItemMedia, MediaAsset, SourceItem
from app.db.session import get_session
from app.generation.editorial_service import (
    EditorialService,
    InvalidGenerationRequest,
    RevisionConflict,
)
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.revision_fence import RegenerationFenceConflict, require_revision_write_allowed
from app.generation.revision_validation import RevisionValidationError, validate_approvable_revision
from app.generation.telegram_schema import (
    TelegramEvidenceCitation,
    TelegramRewriteOutput,
    TelegramVariantContent,
)
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin
from app.publishing.models import (
    Destination,
    Publication,
    PublishAttempt,
    PublishJob,
    PublishOperationReceipt,
)
from app.publishing.telegram.service import (
    PublishValidationError,
    derive_telegram_permalink,
    ordered_receipt_remote_ids,
    validate_reconciliation,
)
from app.stories.models import StoryEvidenceSnapshot, StoryRevision

router = APIRouter(prefix="/telegram", tags=["telegram"])
draft_router = APIRouter(prefix="/drafts")
SessionDependency = Depends(get_session)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class TelegramDraftEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: TelegramRewriteOutput
    media_asset_ids: list[UUID]


class TelegramContentHashIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class TelegramRejectIn(TelegramContentHashIn):
    note: str | None = Field(default=None, max_length=500)


class TelegramReconcileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["published", "not_published"]
    remote_message_ids: list[int] = Field(default_factory=list)
    permalink: HttpUrl | None = None

    @model_validator(mode="after")
    def validate_outcome_fields(self):
        if self.outcome == "not_published" and self.permalink is not None:
            raise ValueError("Not-published outcome cannot include a permalink")
        return self


def _publication_out(publication: Publication) -> dict[str, Any]:
    return {
        "id": publication.id,
        "publish_job_id": publication.publish_job_id,
        "destination_id": publication.destination_id,
        "platform_variant_revision_id": publication.platform_variant_revision_id,
        "remote_message_ids": list(publication.remote_message_ids),
        "permalink": publication.permalink,
        "payload_hash": publication.payload_hash,
        "published_at": publication.published_at,
        "reconciliation_status": publication.reconciliation_status,
    }


def _receipt_out(receipt: PublishOperationReceipt) -> dict[str, Any]:
    return {
        "id": receipt.id,
        "operation_index": receipt.operation_index,
        "operation_key": receipt.operation_key,
        "method": receipt.method,
        "request_hash": receipt.request_hash,
        "status": receipt.status,
        "attempt_count": receipt.attempt_count,
        "remote_message_ids": list(receipt.remote_message_ids),
        "response_metadata": redact_event_data(dict(receipt.response_metadata or {})),
        "next_attempt_at": receipt.next_attempt_at,
        "ambiguous_at": receipt.ambiguous_at,
        "completed_at": receipt.completed_at,
        "created_at": receipt.created_at,
        "updated_at": receipt.updated_at,
    }


def _validate_reconciled_remote_ids(
    receipt: Any,
    remote_message_ids: list[int],
    *,
    expected_count: int | None = None,
) -> None:
    if len(set(remote_message_ids)) != len(remote_message_ids):
        raise HTTPException(422, "Remote message IDs must be unique")
    if expected_count is not None:
        if expected_count <= 0 or len(remote_message_ids) != expected_count:
            raise HTTPException(422, "Remote message IDs do not match the publish operation")
        return
    if receipt.method == "sendMediaGroup":
        if len(remote_message_ids) < 2:
            raise HTTPException(422, "A media group requires at least two remote message IDs")
    elif len(remote_message_ids) != 1:
        raise HTTPException(422, "This Telegram operation requires exactly one remote message ID")


def _publish_job_out(
    publish_job: PublishJob,
    receipts: Iterable[PublishOperationReceipt],
    publication: Publication | None,
) -> dict[str, Any]:
    return {
        "publish_job_id": publish_job.id,
        "workflow_job_id": publish_job.workflow_job_id,
        "destination_id": publish_job.destination_id,
        "platform_variant_revision_id": publish_job.platform_variant_revision_id,
        "status": publish_job.status,
        "payload_hash": publish_job.payload_hash,
        "scheduled_for": publish_job.scheduled_for,
        "created_at": publish_job.created_at,
        "updated_at": publish_job.updated_at,
        "receipts": [_receipt_out(receipt) for receipt in receipts],
        "publication": _publication_out(publication) if publication is not None else None,
    }


def validate_revision_evidence(
    evidence_map: list[dict[str, Any]],
    snapshots: Iterable[Any],
) -> list[dict[str, Any]]:
    if not evidence_map:
        raise HTTPException(409, "Draft evidence is missing")
    indexed = {snapshot.id: snapshot for snapshot in snapshots}
    validated: list[dict[str, Any]] = []
    for raw in evidence_map:
        try:
            citation = TelegramEvidenceCitation.model_validate(raw)
        except Exception:
            raise HTTPException(409, "Draft evidence is invalid") from None
        snapshot = indexed.get(citation.evidence_snapshot_id)
        if snapshot is None:
            raise HTTPException(409, "Draft evidence snapshot is missing")
        text = snapshot.content_text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            expected = TelegramEvidenceCitation(
                evidence_snapshot_id=snapshot.id,
                evidence_key=snapshot.evidence_key,
                source_url=snapshot.source_url,
                locator=f"chars:0-{len(text)}",
                excerpt_sha256=snapshot.content_sha256,
            ).model_dump(mode="json")
        except Exception:
            raise HTTPException(409, "Draft evidence snapshot is invalid") from None
        if digest != snapshot.content_sha256 or citation.model_dump(mode="json") != expected:
            raise HTTPException(409, "Draft evidence no longer matches its snapshot")
        validated.append(citation.model_dump(mode="json"))
    return validated


def build_manual_revision(
    parent: Any,
    body: TelegramDraftEditIn,
    snapshots: Iterable[Any],
    *,
    next_revision_number: int,
) -> PlatformVariantRevision:
    evidence_map = validate_revision_evidence(parent.evidence_map, snapshots)
    try:
        parent_content = TelegramVariantContent.model_validate(parent.content)
        content = TelegramVariantContent(
            body=body.content.body,
            parse_mode=body.content.parse_mode,
            buttons=body.content.buttons,
            source_item_id=parent_content.source_item_id,
            source_url=parent_content.source_url,
            media_policy=parent_content.media_policy,
            media_asset_ids=body.media_asset_ids,
            direction=parent_content.direction,
            dry_run=parent_content.dry_run,
        ).model_dump(mode="json")
    except Exception:
        raise HTTPException(409, "Draft content is invalid") from None
    return PlatformVariantRevision(
        platform_variant_id=parent.platform_variant_id,
        parent_revision_id=parent.id,
        generation_attempt_id=None,
        revision_number=next_revision_number,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=[{"gate": "telegram_schema", "ok": True, "reason": None}],
        approval_state="pending_review",
        created_by="operator",
    )


def require_revision_transition(
    revision: Any,
    *,
    action: Literal["reject", "publish"],
    content_hash: str,
) -> None:
    if revision.content_hash != content_hash:
        raise HTTPException(409, "Draft content changed")
    if action == "reject":
        required = "pending_review"
    elif action == "publish":
        required = "approved"
    else:
        raise HTTPException(409, "Draft transition is unsupported")
    if revision.approval_state != required:
        raise HTTPException(409, f"Draft cannot {action} from its current state")
    if action == "publish":
        try:
            validate_approvable_revision(revision)
        except RevisionValidationError as exc:
            raise HTTPException(409, str(exc)) from None
    if action == "publish" and bool((revision.content or {}).get("dry_run")):
        raise HTTPException(409, "Dry-run drafts cannot be published")


async def _revision_dispatch(
    session: AsyncSession,
    revision: PlatformVariantRevision,
) -> AutomationDispatch | None:
    variant = await session.get(PlatformVariant, revision.platform_variant_id)
    if variant is None or variant.platform != "telegram":
        return None
    expected_variant_id = revision.platform_variant_id
    current: PlatformVariantRevision | None = revision
    seen: set[UUID] = set()
    while current is not None and current.id not in seen:
        if current.platform_variant_id != expected_variant_id:
            return None
        seen.add(current.id)
        dispatch = await session.scalar(
            select(AutomationDispatch)
            .where(AutomationDispatch.variant_revision_id == current.id)
            .order_by(AutomationDispatch.created_at.desc())
            .limit(1)
        )
        if dispatch is not None:
            return dispatch
        current = (
            await session.get(PlatformVariantRevision, current.parent_revision_id)
            if current.parent_revision_id is not None
            else None
        )
    return None


async def _draft_out(
    session: AsyncSession,
    revision: PlatformVariantRevision,
) -> dict[str, Any]:
    dispatch = await _revision_dispatch(session, revision)
    publish_job = await session.scalar(
        select(PublishJob)
        .where(PublishJob.platform_variant_revision_id == revision.id)
        .order_by(PublishJob.created_at.desc())
        .limit(1)
    )
    publication = (
        await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job.id))
        if publish_job is not None
        else None
    )
    evidence_ids: list[UUID] = []
    for raw in revision.evidence_map or []:
        try:
            evidence_ids.append(TelegramEvidenceCitation.model_validate(raw).evidence_snapshot_id)
        except Exception:
            continue
    snapshots = (
        list(await session.scalars(select(StoryEvidenceSnapshot).where(StoryEvidenceSnapshot.id.in_(evidence_ids))))
        if evidence_ids
        else []
    )
    snapshots_by_id = {snapshot.id: snapshot for snapshot in snapshots}
    evidence = [
        {
            "evidence_snapshot_id": snapshot.id,
            "evidence_key": snapshot.evidence_key,
            "source_url": snapshot.source_url,
            "content_text": snapshot.content_text,
            "content_sha256": snapshot.content_sha256,
        }
        for evidence_id in evidence_ids
        if (snapshot := snapshots_by_id.get(evidence_id)) is not None
    ]
    try:
        content = TelegramVariantContent.model_validate(revision.content)
        requested_media_ids = list(content.media_asset_ids)
    except Exception:
        requested_media_ids = []
    media_assets = (
        list(await session.scalars(select(MediaAsset).where(MediaAsset.id.in_(requested_media_ids))))
        if requested_media_ids
        else []
    )
    media_by_id = {asset.id: asset for asset in media_assets}
    media = [
        {
            "id": asset.id,
            "kind": asset.kind,
            "mime_type": asset.mime_type,
            "fetch_status": asset.fetch_status,
            "checksum_sha256": asset.checksum_sha256,
            "preview_url": f"/telegram/drafts/{revision.id}/media/{asset.id}",
        }
        for media_id in requested_media_ids
        if (asset := media_by_id.get(media_id)) is not None
    ]
    return {
        "id": revision.id,
        "platform_variant_id": revision.platform_variant_id,
        "parent_revision_id": revision.parent_revision_id,
        "generation_attempt_id": revision.generation_attempt_id,
        "revision_number": revision.revision_number,
        "content": revision.content,
        "content_hash": revision.content_hash,
        "evidence_map": revision.evidence_map,
        "evidence": evidence,
        "media": media,
        "validation_results": revision.validation_results,
        "approval_state": revision.approval_state,
        "approval_note": revision.approval_note,
        "approved_at": revision.approved_at,
        "created_by": revision.created_by,
        "created_at": revision.created_at,
        "route_id": dispatch.route_id if dispatch is not None else None,
        "dispatch_id": dispatch.id if dispatch is not None else None,
        "publish_job_id": publish_job.id if publish_job is not None else None,
        "publish_status": publish_job.status if publish_job is not None else None,
        "publication": _publication_out(publication) if publication is not None else None,
    }


async def _locked_revision(
    session: AsyncSession,
    revision_id: UUID,
) -> PlatformVariantRevision:
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .join(PlatformVariant, PlatformVariant.id == PlatformVariantRevision.platform_variant_id)
        .where(PlatformVariantRevision.id == revision_id)
        .where(PlatformVariant.platform == "telegram")
        .with_for_update()
    )
    if revision is None:
        raise HTTPException(404, "Telegram draft not found")
    latest_id = await session.scalar(
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
        raise HTTPException(409, "Telegram draft revision is not current")
    return revision


async def _revision_snapshots(
    session: AsyncSession,
    revision: PlatformVariantRevision,
    evidence_map: list[dict[str, Any]],
) -> list[Any]:
    citations: list[TelegramEvidenceCitation] = []
    for raw in evidence_map:
        try:
            citations.append(TelegramEvidenceCitation.model_validate(raw))
        except Exception:
            raise HTTPException(409, "Draft evidence is invalid") from None
    if not citations:
        raise HTTPException(409, "Draft evidence is missing")
    variant = await session.get(PlatformVariant, revision.platform_variant_id)
    pack = await session.get(ContentPack, variant.content_pack_id) if variant is not None else None
    story_revision = await session.get(StoryRevision, pack.story_revision_id) if pack is not None else None
    if variant is None or variant.platform != "telegram" or story_revision is None:
        raise HTTPException(409, "Draft lineage is invalid")
    from app.stories.models import StoryEvidenceSnapshot

    snapshots = list(
        await session.scalars(
            select(StoryEvidenceSnapshot).where(
                StoryEvidenceSnapshot.id.in_([citation.evidence_snapshot_id for citation in citations])
            )
        )
    )
    if any(snapshot.story_id != story_revision.story_id for snapshot in snapshots):
        raise HTTPException(409, "Draft evidence does not belong to its story")
    return snapshots


def _append_draft_event(
    session: AsyncSession,
    *,
    event_type: str,
    revision: PlatformVariantRevision,
    data: dict[str, Any] | None = None,
) -> None:
    session.add(
        WorkflowEvent(
            workflow_job_id=None,
            event_type=event_type,
            actor="operator",
            event_data=redact_event_data(
                {
                    "revision_id": str(revision.id),
                    "content_hash": revision.content_hash,
                    **(data or {}),
                }
            ),
        )
    )


@draft_router.get("")
async def list_telegram_drafts(
    route_id: UUID | None = None,
    approval_state: Literal["draft", "pending_review", "approved", "rejected"] | None = None,
    session: AsyncSession = SessionDependency,
):
    statement = (
        select(PlatformVariantRevision)
        .join(PlatformVariant, PlatformVariant.id == PlatformVariantRevision.platform_variant_id)
        .where(PlatformVariant.platform == "telegram")
        .order_by(
            PlatformVariantRevision.created_at.desc(),
            PlatformVariantRevision.revision_number.desc(),
        )
    )
    if approval_state is not None:
        statement = statement.where(PlatformVariantRevision.approval_state == approval_state)
    revisions = list(await session.scalars(statement))
    results = []
    for revision in revisions:
        item = await _draft_out(session, revision)
        if route_id is None or item["route_id"] == route_id:
            results.append(item)
    return results


@draft_router.get("/{revision_id}")
async def get_telegram_draft(
    revision_id: UUID,
    session: AsyncSession = SessionDependency,
):
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .join(PlatformVariant, PlatformVariant.id == PlatformVariantRevision.platform_variant_id)
        .where(
            PlatformVariantRevision.id == revision_id,
            PlatformVariant.platform == "telegram",
        )
    )
    if revision is None:
        raise HTTPException(404, "Telegram draft not found")
    return await _draft_out(session, revision)


@draft_router.get("/{revision_id}/media/{media_asset_id}")
async def get_telegram_draft_media(
    revision_id: UUID,
    media_asset_id: UUID,
    session: AsyncSession = SessionDependency,
):
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .join(PlatformVariant, PlatformVariant.id == PlatformVariantRevision.platform_variant_id)
        .where(
            PlatformVariantRevision.id == revision_id,
            PlatformVariant.platform == "telegram",
        )
    )
    if revision is None:
        raise HTTPException(404, "Telegram draft not found")
    try:
        content = TelegramVariantContent.model_validate(revision.content)
    except Exception:
        raise HTTPException(409, "Telegram draft content is invalid") from None
    if media_asset_id not in content.media_asset_ids:
        raise HTTPException(404, "Telegram draft media not found")
    asset = await session.get(MediaAsset, media_asset_id)
    if asset is None or asset.fetch_status != "downloaded" or not asset.storage_path or not asset.checksum_sha256:
        raise HTTPException(409, "Telegram draft media is unavailable")
    path = Path(asset.storage_path)
    if not path.is_file():
        raise HTTPException(409, "Telegram draft media is unavailable")
    try:
        digest = await run_in_threadpool(_file_sha256, path)
    except OSError:
        raise HTTPException(409, "Telegram draft media is unavailable") from None
    if digest != asset.checksum_sha256:
        raise HTTPException(409, "Telegram draft media checksum changed")
    preview_formats = {
        ("image", "image/jpeg"): {".jpg", ".jpeg"},
        ("photo", "image/jpeg"): {".jpg", ".jpeg"},
        ("image", "image/png"): {".png"},
        ("photo", "image/png"): {".png"},
        ("image", "image/gif"): {".gif"},
        ("photo", "image/gif"): {".gif"},
        ("image", "image/webp"): {".webp"},
        ("photo", "image/webp"): {".webp"},
        ("video", "video/mp4"): {".mp4"},
        ("video", "video/quicktime"): {".mov"},
    }
    media_key = (str(asset.kind).casefold(), str(asset.mime_type or "").casefold())
    inline_extensions = preview_formats.get(media_key)
    if inline_extensions is not None and path.suffix.casefold() not in inline_extensions:
        raise HTTPException(409, "Telegram draft media format changed")
    inline = inline_extensions is not None
    return FileResponse(
        path,
        media_type=asset.mime_type if inline else "application/octet-stream",
        filename=f"telegram-media-{asset.id}{path.suffix.casefold()}",
        content_disposition_type="inline" if inline else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@draft_router.post("/{revision_id}/revisions", status_code=201)
async def edit_telegram_draft(
    revision_id: UUID,
    body: TelegramDraftEditIn,
    session: AsyncSession = SessionDependency,
):
    async with session.begin():
        lineage = await session.get(PlatformVariantRevision, revision_id)
        if lineage is None:
            raise HTTPException(404, "Telegram draft not found")
        variant = await session.scalar(
            select(PlatformVariant)
            .where(
                PlatformVariant.id == lineage.platform_variant_id,
                PlatformVariant.platform == "telegram",
            )
            .with_for_update()
        )
        if variant is None:
            raise HTTPException(409, "Telegram draft lineage is invalid")
        try:
            await require_revision_write_allowed(session, variant_id=variant.id)
        except RegenerationFenceConflict:
            raise HTTPException(409, "Telegram draft regeneration is in progress") from None
        parent = await _locked_revision(session, revision_id)
        if parent.platform_variant_id != variant.id:
            raise HTTPException(409, "Telegram draft lineage changed")
        snapshots = await _revision_snapshots(session, parent, parent.evidence_map)
        requested_ids = set(body.media_asset_ids)
        requested_assets: list[MediaAsset] = []
        if requested_ids:
            requested_assets = list(await session.scalars(select(MediaAsset).where(MediaAsset.id.in_(requested_ids))))
            found = {asset.id for asset in requested_assets}
            if found != requested_ids:
                raise HTTPException(422, "One or more media assets do not exist")
            if any(
                asset.fetch_status != "downloaded" or not asset.storage_path or not asset.checksum_sha256
                for asset in requested_assets
            ):
                raise HTTPException(422, "Draft media must be downloaded and checksum-verified")
        try:
            parent_content = TelegramVariantContent.model_validate(parent.content)
        except Exception:
            raise HTTPException(409, "Draft content is invalid") from None
        if parent_content.media_policy == "omit" and requested_ids:
            raise HTTPException(422, "Omit-media drafts cannot attach media")
        if parent_content.media_policy == "preserve":
            if parent_content.source_item_id is None:
                raise HTTPException(409, "Draft source provenance is missing")
            source_item = await session.get(SourceItem, parent_content.source_item_id)
            if source_item is None or source_item.content_item_id is None:
                raise HTTPException(409, "Draft source provenance is invalid")
            linked_ids = set(
                await session.scalars(
                    select(ItemMedia.media_asset_id).where(ItemMedia.content_item_id == source_item.content_item_id)
                )
            )
            if not requested_ids.issubset(linked_ids):
                raise HTTPException(422, "Preserved media must belong to the draft source")
        next_number = (
            int(
                await session.scalar(
                    select(func.coalesce(func.max(PlatformVariantRevision.revision_number), 0)).where(
                        PlatformVariantRevision.platform_variant_id == parent.platform_variant_id
                    )
                )
                or 0
            )
            + 1
        )
        child = build_manual_revision(
            parent,
            body,
            snapshots,
            next_revision_number=next_number,
        )
        session.add(child)
        await session.flush()
        _append_draft_event(
            session,
            event_type="telegram.revision.edited",
            revision=child,
            data={"parent_revision_id": str(parent.id)},
        )
        await session.flush()
    return await _draft_out(session, child)


@draft_router.post("/{revision_id}/approve")
async def approve_telegram_draft(
    revision_id: UUID,
    body: TelegramContentHashIn,
    session: AsyncSession = SessionDependency,
):
    async with session.begin():
        try:
            revision = await EditorialService(session).approve_revision(
                revision_id,
                expected_content_hash=body.content_hash,
                note=None,
            )
        except (InvalidGenerationRequest, RevisionConflict) as exc:
            raise HTTPException(409, str(exc)) from None
        _append_draft_event(
            session,
            event_type="telegram.revision.approved",
            revision=revision,
        )
        await session.flush()
    return await _draft_out(session, revision)


@draft_router.post("/{revision_id}/reject")
async def reject_telegram_draft(
    revision_id: UUID,
    body: TelegramRejectIn,
    session: AsyncSession = SessionDependency,
):
    async with session.begin():
        revision = await _locked_revision(session, revision_id)
        require_revision_transition(
            revision,
            action="reject",
            content_hash=body.content_hash,
        )
        revision.approval_state = "rejected"
        revision.approval_note = body.note
        revision.approved_at = None
        _append_draft_event(
            session,
            event_type="telegram.revision.rejected",
            revision=revision,
            data={"note": body.note},
        )
        await session.flush()
    return await _draft_out(session, revision)


@draft_router.post("/{revision_id}/publish", status_code=202)
async def publish_telegram_draft(
    revision_id: UUID,
    body: TelegramContentHashIn,
    session: AsyncSession = SessionDependency,
):
    async with session.begin():
        revision = await _locked_revision(session, revision_id)
        require_revision_transition(
            revision,
            action="publish",
            content_hash=body.content_hash,
        )
        dispatch = await _revision_dispatch(session, revision)
        if dispatch is None:
            raise HTTPException(409, "Telegram draft has no route provenance")
        route = await session.get(AutomationRoute, dispatch.route_id)
        if route is None:
            raise HTTPException(409, "Telegram draft route is missing")
        destination = await session.scalar(
            select(Destination).where(Destination.id == route.destination_id).with_for_update()
        )
        if destination is None:
            raise HTTPException(409, "Telegram draft destination is missing")
        publish_job = await enqueue_telegram_publish_intent(
            session,
            revision=revision,
            destination=destination,
            dispatch=dispatch if dispatch.variant_revision_id == revision.id else None,
        )
        _append_draft_event(
            session,
            event_type="telegram.revision.publish_requested",
            revision=revision,
            data={"publish_job_id": str(publish_job.id)},
        )
        await session.flush()
    return {
        "revision": await _draft_out(session, revision),
        "job": {
            "publish_job_id": publish_job.id,
            "workflow_job_id": publish_job.workflow_job_id,
            "status": publish_job.status,
        },
    }


@router.get("/publish-jobs/{publish_job_id}")
async def get_telegram_publish_job(
    publish_job_id: UUID,
    session: AsyncSession = SessionDependency,
):
    publish_job = await session.get(PublishJob, publish_job_id)
    if publish_job is None:
        raise HTTPException(404, "Telegram publish job not found")
    destination = await session.get(Destination, publish_job.destination_id)
    if destination is None or destination.platform != "telegram":
        raise HTTPException(404, "Telegram publish job not found")
    receipts = list(
        await session.scalars(
            select(PublishOperationReceipt)
            .where(PublishOperationReceipt.publish_job_id == publish_job.id)
            .order_by(PublishOperationReceipt.operation_index)
        )
    )
    publication = await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job.id))
    return _publish_job_out(publish_job, receipts, publication)


@router.post("/publish-jobs/{publish_job_id}/reconcile")
async def reconcile_telegram_publish_job(
    publish_job_id: UUID,
    body: TelegramReconcileIn,
    response: Response,
    session: AsyncSession = SessionDependency,
):
    async with session.begin():
        publish_job = await session.scalar(select(PublishJob).where(PublishJob.id == publish_job_id).with_for_update())
        if publish_job is None:
            raise HTTPException(404, "Telegram publish job not found")
        destination = await session.get(Destination, publish_job.destination_id)
        if destination is None or destination.platform != "telegram":
            raise HTTPException(404, "Telegram publish job not found")
        receipts = list(
            await session.scalars(
                select(PublishOperationReceipt)
                .where(PublishOperationReceipt.publish_job_id == publish_job.id)
                .order_by(PublishOperationReceipt.operation_index)
                .with_for_update()
            )
        )
        try:
            ambiguous = validate_reconciliation(
                receipts,
                outcome=body.outcome,
                remote_message_ids=body.remote_message_ids,
            )
        except PublishValidationError as exc:
            raise HTTPException(409, str(exc)) from None

        observed_at = datetime.now(UTC)
        if body.outcome == "not_published":
            ambiguous.status = "pending"
            ambiguous.remote_message_ids = []
            ambiguous.response_metadata = {}
            ambiguous.next_attempt_at = None
            ambiguous.ambiguous_at = None
            ambiguous.completed_at = None
            ambiguous.updated_at = observed_at
            publish_job.status = "queued"
            publish_job.scheduled_for = observed_at
            publish_job.updated_at = observed_at
            result = await JobRepository(session).enqueue_job(
                job_type="telegram.publish",
                payload={"publish_job_id": str(publish_job.id)},
                idempotency_key=(f"telegram-publish-reconcile:{publish_job.id}:{publish_job.updated_at.isoformat()}"),
                origin=JobOrigin.RETRY,
            )
            publish_job.workflow_job_id = result.job.id
            session.add(
                WorkflowEvent(
                    workflow_job_id=result.job.id,
                    event_type="telegram.publish.reconciled_not_published",
                    actor="operator",
                    event_data=redact_event_data(
                        {
                            "publish_job_id": str(publish_job.id),
                            "operation_key": ambiguous.operation_key,
                            "requeued_workflow_job_id": str(result.job.id),
                        }
                    ),
                )
            )
            await session.flush()
            response.status_code = 202
            return {
                "publish_job_id": publish_job.id,
                "reconciliation_status": "requeued",
                "job": {
                    "job_id": result.job.id,
                    "status": result.job.status,
                    "deduplicated": not result.created,
                },
                "receipts": [_receipt_out(receipt) for receipt in receipts],
            }

        latest_attempt = await session.scalar(
            select(PublishAttempt)
            .where(PublishAttempt.publish_job_id == publish_job.id)
            .order_by(PublishAttempt.attempt_number.desc())
            .limit(1)
            .with_for_update()
        )
        expected_count: int | None = None
        if latest_attempt is not None:
            operations = latest_attempt.sanitized_payload.get("operations", [])
            if isinstance(operations, list):
                operation_summary = next(
                    (
                        item
                        for item in operations
                        if isinstance(item, dict) and item.get("index") == ambiguous.operation_index
                    ),
                    None,
                )
                if operation_summary is not None:
                    upload_count = operation_summary.get("upload_count")
                    if isinstance(upload_count, int) and not isinstance(upload_count, bool):
                        expected_count = upload_count if upload_count > 0 else 1
        if ambiguous.method == "sendMediaGroup" and expected_count is None:
            raise HTTPException(409, "Telegram publish operation plan is unavailable")
        _validate_reconciled_remote_ids(
            ambiguous,
            body.remote_message_ids,
            expected_count=expected_count,
        )
        ambiguous.status = "succeeded"
        ambiguous.remote_message_ids = list(body.remote_message_ids)
        ambiguous.response_metadata = {
            "operator_confirmed": True,
            "reconciliation_outcome": "published",
        }
        ambiguous.next_attempt_at = None
        ambiguous.completed_at = observed_at
        try:
            remote_ids = ordered_receipt_remote_ids(receipts)
        except PublishValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        existing = await session.scalar(
            select(Publication).where(Publication.publish_job_id == publish_job.id).with_for_update()
        )
        if existing is not None:
            raise HTTPException(409, "Telegram publish job already has a publication")
        publication = Publication(
            publish_job_id=publish_job.id,
            destination_id=publish_job.destination_id,
            platform_variant_revision_id=publish_job.platform_variant_revision_id,
            remote_message_ids=remote_ids,
            permalink=(
                str(body.permalink)
                if body.permalink is not None
                else derive_telegram_permalink(destination.target_ref, remote_ids)
            ),
            payload_hash=publish_job.payload_hash,
            published_at=observed_at,
            reconciliation_status="confirmed",
        )
        session.add(publication)
        publish_job.status = "succeeded"
        publish_job.scheduled_for = None
        if latest_attempt is not None:
            latest_attempt.status = "succeeded"
            latest_attempt.error_class = None
            latest_attempt.error_code = None
            latest_attempt.error_message = None
            latest_attempt.remote_response = {
                "operator_confirmed": True,
                "remote_message_ids": remote_ids,
            }
            latest_attempt.finished_at = observed_at
        revision = await session.get(
            PlatformVariantRevision,
            publish_job.platform_variant_revision_id,
        )
        dispatch = await _revision_dispatch(session, revision) if revision is not None else None
        if dispatch is not None:
            dispatch.status = "published"
            dispatch.publish_job_id = publish_job.id
        await session.flush()
        session.add(
            WorkflowEvent(
                workflow_job_id=publish_job.workflow_job_id,
                event_type="telegram.publish.reconciled_published",
                actor="operator",
                event_data=redact_event_data(
                    {
                        "publish_job_id": str(publish_job.id),
                        "publication_id": str(publication.id),
                        "operation_key": ambiguous.operation_key,
                        "remote_message_ids": remote_ids,
                    }
                ),
            )
        )
        await session.flush()
        return _publication_out(publication)


router.include_router(draft_router)
