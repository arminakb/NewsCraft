from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.handlers import (
    enqueue_telegram_publish_intent,
    sha256_canonical,
)
from app.db.models import ItemMedia, MediaAsset, SourceItem
from app.db.session import get_session
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.telegram_schema import (
    TelegramEvidenceCitation,
    TelegramRewriteOutput,
    TelegramVariantContent,
)
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent
from app.publishing.models import Destination, PublishJob
from app.stories.models import StoryRevision

router = APIRouter(prefix="/telegram/drafts", tags=["telegram"])
SessionDependency = Depends(get_session)


class TelegramDraftEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: TelegramRewriteOutput
    media_asset_ids: list[UUID]


class TelegramContentHashIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class TelegramRejectIn(TelegramContentHashIn):
    note: str | None = Field(default=None, max_length=500)


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
        validation_results=[{"gate": "telegram_schema", "ok": True}],
        approval_state="pending_review",
        created_by="operator",
    )


def require_revision_transition(
    revision: Any,
    *,
    action: Literal["approve", "reject", "publish"],
    content_hash: str,
) -> None:
    if revision.content_hash != content_hash:
        raise HTTPException(409, "Draft content changed")
    required = "approved" if action == "publish" else "pending_review"
    if revision.approval_state != required:
        raise HTTPException(409, f"Draft cannot {action} from its current state")
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
    return {
        "id": revision.id,
        "platform_variant_id": revision.platform_variant_id,
        "parent_revision_id": revision.parent_revision_id,
        "generation_attempt_id": revision.generation_attempt_id,
        "revision_number": revision.revision_number,
        "content": revision.content,
        "content_hash": revision.content_hash,
        "evidence_map": revision.evidence_map,
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
    story_revision = (
        await session.get(StoryRevision, pack.story_revision_id) if pack is not None else None
    )
    if variant is None or variant.platform != "telegram" or story_revision is None:
        raise HTTPException(409, "Draft lineage is invalid")
    from app.stories.models import StoryEvidenceSnapshot

    snapshots = list(
        await session.scalars(
            select(StoryEvidenceSnapshot).where(
                StoryEvidenceSnapshot.id.in_(
                    [citation.evidence_snapshot_id for citation in citations]
                )
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


@router.get("")
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


@router.get("/{revision_id}")
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


@router.post("/{revision_id}/revisions", status_code=201)
async def edit_telegram_draft(
    revision_id: UUID,
    body: TelegramDraftEditIn,
    session: AsyncSession = SessionDependency,
):
    async with session.begin():
        parent = await _locked_revision(session, revision_id)
        variant = await session.scalar(
            select(PlatformVariant)
            .where(PlatformVariant.id == parent.platform_variant_id)
            .with_for_update()
        )
        if variant is None:
            raise HTTPException(409, "Telegram draft lineage is invalid")
        snapshots = await _revision_snapshots(session, parent, parent.evidence_map)
        requested_ids = set(body.media_asset_ids)
        requested_assets: list[MediaAsset] = []
        if requested_ids:
            requested_assets = list(
                await session.scalars(
                    select(MediaAsset).where(MediaAsset.id.in_(requested_ids))
                )
            )
            found = {asset.id for asset in requested_assets}
            if found != requested_ids:
                raise HTTPException(422, "One or more media assets do not exist")
            if any(
                asset.fetch_status != "downloaded"
                or not asset.storage_path
                or not asset.checksum_sha256
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
                    select(ItemMedia.media_asset_id).where(
                        ItemMedia.content_item_id == source_item.content_item_id
                    )
                )
            )
            if not requested_ids.issubset(linked_ids):
                raise HTTPException(422, "Preserved media must belong to the draft source")
        next_number = int(
            await session.scalar(
                select(func.coalesce(func.max(PlatformVariantRevision.revision_number), 0)).where(
                    PlatformVariantRevision.platform_variant_id == parent.platform_variant_id
                )
            )
            or 0
        ) + 1
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


@router.post("/{revision_id}/approve")
async def approve_telegram_draft(
    revision_id: UUID,
    body: TelegramContentHashIn,
    session: AsyncSession = SessionDependency,
):
    async with session.begin():
        revision = await _locked_revision(session, revision_id)
        require_revision_transition(
            revision,
            action="approve",
            content_hash=body.content_hash,
        )
        revision.approval_state = "approved"
        revision.approved_at = datetime.now(UTC)
        revision.approval_note = None
        _append_draft_event(
            session,
            event_type="telegram.revision.approved",
            revision=revision,
        )
        await session.flush()
    return await _draft_out(session, revision)


@router.post("/{revision_id}/reject")
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


@router.post("/{revision_id}/publish", status_code=202)
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
            select(Destination)
            .where(Destination.id == route.destination_id)
            .with_for_update()
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
