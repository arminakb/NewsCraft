from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.capabilities import CapabilityStatusDependency
from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.handlers import (
    enqueue_telegram_publish_intent,
    sha256_canonical,
)
from app.core.redaction import redact_secrets
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
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.media.reference_fence import fence_platform_revision_media_write
from app.publishing.models import (
    Destination,
    Publication,
    PublishJob,
    PublishOperationReceipt,
)
from app.publishing.telegram.service import (
    PublishValidationError,
    ReconciliationCase,
    ReviewedTelegramScheduleError,
    derive_telegram_permalink,
    get_reconciliation_case,
    list_reconciliation_cases,
    ordered_receipt_remote_ids,
    schedule_reviewed_telegram,
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


class ScheduleTelegramIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination_id: UUID
    scheduled_for: AwareDatetime

    @field_validator("scheduled_for")
    @classmethod
    def normalize_scheduled_for(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class TelegramReconcileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["published", "not_published"]
    remote_message_ids: list[int] = Field(default_factory=list)
    permalink: HttpUrl | None = None
    operator_note: str | None = Field(default=None, min_length=5, max_length=1_000)

    @field_validator("operator_note", mode="before")
    @classmethod
    def normalize_operator_note(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

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


def _reconciliation_decision_fields(body: TelegramReconcileIn) -> dict[str, object]:
    return {
        "operator_note": body.operator_note,
        "outcome": body.outcome,
        "permalink": str(body.permalink) if body.permalink is not None else None,
        "remote_message_ids": list(body.remote_message_ids),
    }


def _reconciliation_decision_hash(body: TelegramReconcileIn) -> str:
    return sha256_canonical(_reconciliation_decision_fields(body))


def _reconciliation_generation(receipt: PublishOperationReceipt) -> dict[str, object]:
    return {
        "operation_key": receipt.operation_key,
        "attempt_count": receipt.attempt_count,
        "ambiguous_at": (receipt.ambiguous_at.isoformat() if receipt.ambiguous_at is not None else None),
    }


async def _reconciliation_events(
    session: AsyncSession,
    publish_job_id: UUID,
) -> list[WorkflowEvent]:
    return list(
        await session.scalars(
            select(WorkflowEvent)
            .where(
                WorkflowEvent.event_type.in_(
                    (
                        "telegram.publish.reconciled_not_published",
                        "telegram.publish.reconciled_published",
                    )
                ),
                WorkflowEvent.event_data["publish_job_id"].as_string() == str(publish_job_id),
            )
            .order_by(WorkflowEvent.created_at.desc(), WorkflowEvent.id.desc())
        )
    )


def _event_matches_reconciliation_generation(
    event: WorkflowEvent,
    receipts: list[PublishOperationReceipt],
) -> bool:
    event_data = event.event_data if isinstance(event.event_data, dict) else {}
    generation = event_data.get("reconciliation_generation")
    if not isinstance(generation, dict):
        return False
    operation_key = generation.get("operation_key")
    attempt_count = generation.get("attempt_count")
    receipt = next(
        (item for item in receipts if item.operation_key == operation_key),
        None,
    )
    if receipt is None or receipt.attempt_count != attempt_count:
        return False
    if receipt.ambiguous_at is not None:
        return generation.get("ambiguous_at") == receipt.ambiguous_at.isoformat()
    return True


async def _replay_reconciliation_decision(
    session: AsyncSession,
    event: WorkflowEvent,
    publish_job: PublishJob,
    receipts: list[PublishOperationReceipt],
    response: Response,
) -> dict[str, Any]:
    event_data = event.event_data if isinstance(event.event_data, dict) else {}
    if event_data.get("outcome") == "published":
        publication_id = _uuid_or_none(event_data.get("publication_id"))
        publication = (
            await session.scalar(
                select(Publication).where(
                    Publication.id == publication_id,
                    Publication.publish_job_id == publish_job.id,
                )
            )
            if publication_id is not None
            else None
        )
        if publication is None:
            raise HTTPException(409, "Prior reconciliation result is unavailable")
        return _publication_out(publication)

    if event_data.get("outcome") == "not_published":
        workflow_job_id = _uuid_or_none(event_data.get("requeued_workflow_job_id"))
        requeued_job_status = event_data.get("requeued_job_status")
        requeued_job_deduplicated = event_data.get("requeued_job_deduplicated")
        workflow_job = await session.get(WorkflowJob, workflow_job_id) if workflow_job_id is not None else None
        if (
            workflow_job is None
            or not isinstance(requeued_job_status, str)
            or not isinstance(requeued_job_deduplicated, bool)
        ):
            raise HTTPException(409, "Prior reconciliation result is unavailable")
        response.status_code = 202
        return {
            "publish_job_id": publish_job.id,
            "reconciliation_status": "requeued",
            "job": {
                "job_id": workflow_job.id,
                "status": requeued_job_status,
                "deduplicated": requeued_job_deduplicated,
            },
            "receipts": [_receipt_out(receipt) for receipt in receipts],
        }

    raise HTTPException(409, "Prior reconciliation result is unavailable")


def _uuid_or_none(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except TypeError, ValueError:
        return None


def _reconciliation_event_data(
    *,
    body: TelegramReconcileIn,
    publish_job: PublishJob,
    receipts: list[PublishOperationReceipt],
    generation: dict[str, object],
    result_ids: dict[str, object],
) -> dict[str, object]:
    return redact_event_data(
        {
            "publish_job_id": str(publish_job.id),
            "decision_hash": _reconciliation_decision_hash(body),
            "operation_keys": [receipt.operation_key for receipt in receipts],
            **_reconciliation_decision_fields(body),
            **result_ids,
            "reconciliation_generation": generation,
        }
    )


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
    redacted_validation_results = redact_secrets(revision.validation_results)
    validation_results = (
        [item for item in redacted_validation_results if isinstance(item, dict)]
        if isinstance(redacted_validation_results, list)
        else []
    )
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
        "validation_results": validation_results,
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
    provisional = await session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.id == revision_id)
        .execution_options(populate_existing=True)
    )
    if provisional is None:
        raise HTTPException(404, "Telegram draft not found")
    variant = await session.scalar(
        select(PlatformVariant)
        .where(PlatformVariant.id == provisional.platform_variant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if variant is None or variant.platform != "telegram":
        raise HTTPException(404, "Telegram draft not found")
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .where(
            PlatformVariantRevision.id == revision_id,
            PlatformVariantRevision.platform_variant_id == variant.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
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
            await fence_platform_revision_media_write(session)
            requested_assets = list(
                await session.scalars(
                    select(MediaAsset)
                    .where(MediaAsset.id.in_(requested_ids))
                    .order_by(MediaAsset.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
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
        await _locked_revision(session, revision_id)
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
    capability_status: CapabilityStatusDependency = None,
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
        await capability_status.require_available(
            "destination",
            destination.id,
            "publishing",
            job_type="telegram.publish",
        )
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


@draft_router.post(
    "/{revision_id}/schedule",
    response_model=JobAcceptedOut,
    status_code=202,
)
async def schedule_telegram_revision(
    revision_id: UUID,
    body: ScheduleTelegramIn,
    session: AsyncSession = SessionDependency,
    capability_status: CapabilityStatusDependency = None,
) -> JobAcceptedOut:
    try:
        async with session.begin():
            await capability_status.require_available(
                "destination",
                body.destination_id,
                "publishing",
                job_type="telegram.publish",
            )
            result = await schedule_reviewed_telegram(
                session,
                revision_id=revision_id,
                request=body,
            )
    except ReviewedTelegramScheduleError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return JobAcceptedOut(
        job_id=result.workflow_job.id,
        status=result.workflow_job.status,
        deduplicated=not result.created,
    )


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


@router.get("/reconciliation", response_model=list[ReconciliationCase])
async def list_telegram_reconciliation_cases(
    session: AsyncSession = SessionDependency,
) -> list[ReconciliationCase]:
    return await list_reconciliation_cases(session)


@router.get("/reconciliation/{publish_job_id}", response_model=ReconciliationCase)
async def get_telegram_reconciliation_case(
    publish_job_id: UUID,
    session: AsyncSession = SessionDependency,
) -> ReconciliationCase:
    case = await get_reconciliation_case(session, publish_job_id)
    if case is None:
        raise HTTPException(404, "Telegram reconciliation case not found")
    return case


@router.post("/publish-jobs/{publish_job_id}/reconcile")
async def reconcile_telegram_publish_job(
    publish_job_id: UUID,
    body: TelegramReconcileIn,
    response: Response,
    session: AsyncSession = SessionDependency,
    capability_status: CapabilityStatusDependency = None,
):
    async with session.begin():
        publish_job = await session.scalar(select(PublishJob).where(PublishJob.id == publish_job_id).with_for_update())
        if publish_job is None:
            raise HTTPException(404, "Telegram publish job not found")
        destination = await session.get(Destination, publish_job.destination_id)
        if destination is None or destination.platform != "telegram":
            raise HTTPException(404, "Telegram publish job not found")
        if body.outcome == "not_published":
            await capability_status.require_available(
                "destination",
                destination.id,
                "publishing",
                job_type="telegram.publish",
            )
        receipts = list(
            await session.scalars(
                select(PublishOperationReceipt)
                .where(PublishOperationReceipt.publish_job_id == publish_job.id)
                .order_by(PublishOperationReceipt.operation_index)
                .with_for_update()
            )
        )
        decision_hash = _reconciliation_decision_hash(body)
        prior_events = await _reconciliation_events(session, publish_job.id)
        prior_event = next(
            (event for event in prior_events if _event_matches_reconciliation_generation(event, receipts)),
            None,
        )
        if prior_event is not None:
            event_data = prior_event.event_data if isinstance(prior_event.event_data, dict) else {}
            if event_data.get("decision_hash") != decision_hash:
                raise HTTPException(409, "Conflicting reconciliation decision")
            return await _replay_reconciliation_decision(
                session,
                prior_event,
                publish_job,
                receipts,
                response,
            )
        if any(
            isinstance(event.event_data, dict) and event.event_data.get("decision_hash") == decision_hash
            for event in prior_events
        ):
            raise HTTPException(409, "Stale reconciliation decision")

        try:
            ambiguous = validate_reconciliation(
                receipts,
                outcome=body.outcome,
                remote_message_ids=body.remote_message_ids,
            )
        except PublishValidationError as exc:
            raise HTTPException(409, str(exc)) from None

        observed_at = datetime.now(UTC)
        generation = _reconciliation_generation(ambiguous)
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
                idempotency_key=(
                    f"telegram-publish-reconcile:{publish_job.id}:{ambiguous.operation_key}:{ambiguous.attempt_count}"
                ),
                origin=JobOrigin.RETRY,
            )
            publish_job.workflow_job_id = result.job.id
            session.add(
                WorkflowEvent(
                    workflow_job_id=result.job.id,
                    event_type="telegram.publish.reconciled_not_published",
                    actor="operator",
                    event_data=_reconciliation_event_data(
                        body=body,
                        publish_job=publish_job,
                        receipts=receipts,
                        generation=generation,
                        result_ids={
                            "requeued_workflow_job_id": str(result.job.id),
                            "requeued_job_status": result.job.status,
                            "requeued_job_deduplicated": not result.created,
                        },
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

        _validate_reconciled_remote_ids(ambiguous, body.remote_message_ids)
        ambiguous.status = "succeeded"
        ambiguous.remote_message_ids = list(body.remote_message_ids)
        ambiguous.response_metadata = {
            "operator_confirmed": True,
            "reconciliation_outcome": "published",
        }
        ambiguous.next_attempt_at = None
        ambiguous.completed_at = observed_at
        ambiguous.updated_at = observed_at
        try:
            remote_ids = ordered_receipt_remote_ids(receipts)
        except PublishValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        permalink = (
            str(body.permalink)
            if body.permalink is not None
            else derive_telegram_permalink(destination.target_ref, remote_ids)
        )
        existing = await session.scalar(
            select(Publication).where(Publication.publish_job_id == publish_job.id).with_for_update()
        )
        if existing is None:
            publication = Publication(
                publish_job_id=publish_job.id,
                destination_id=publish_job.destination_id,
                platform_variant_revision_id=publish_job.platform_variant_revision_id,
                remote_message_ids=remote_ids,
                permalink=permalink,
                payload_hash=publish_job.payload_hash,
                published_at=observed_at,
                reconciliation_status="confirmed",
            )
            session.add(publication)
        else:
            if (
                existing.destination_id != publish_job.destination_id
                or existing.platform_variant_revision_id != publish_job.platform_variant_revision_id
                or existing.payload_hash != publish_job.payload_hash
                or list(existing.remote_message_ids) != remote_ids
                or existing.permalink != permalink
                or existing.reconciliation_status != "confirmed"
            ):
                raise HTTPException(409, "Telegram publication conflicts with reconciliation")
            publication = existing
        publish_job.status = "succeeded"
        publish_job.scheduled_for = None
        publish_job.updated_at = observed_at
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
                event_data=_reconciliation_event_data(
                    body=body,
                    publish_job=publish_job,
                    receipts=receipts,
                    generation=generation,
                    result_ids={
                        "publication_id": str(publication.id),
                    },
                ),
            )
        )
        await session.flush()
        return _publication_out(publication)


router.include_router(draft_router)
