from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db.models import ItemMedia, MediaAsset
from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    MediaAssignment,
    PlatformPayload,
    XVariantPayload,
)
from app.research.citations import CitationIntegrityError


def _payload_media_assignments(payload: PlatformPayload) -> list[MediaAssignment]:
    if isinstance(payload, InstagramVariantPayload):
        return [slide.media for slide in payload.carousel]
    if isinstance(payload, XVariantPayload):
        return [media for post in payload.posts for media in post.media]
    if isinstance(payload, BlogVariantPayload) and payload.hero_media is not None:
        return [payload.hero_media]
    return []


def validate_payload_media_assignments(
    payload: PlatformPayload,
    authorized: dict[UUID, MediaAsset | Any],
) -> None:
    for assignment in _payload_media_assignments(payload):
        if assignment.media_asset_id is None:
            if not any(
                isinstance(value, str) and bool(value.strip())
                for value in (assignment.manual_brief, assignment.image_prompt)
            ):
                raise CitationIntegrityError("manual media assignment requires a brief or prompt")
            continue
        asset = authorized.get(assignment.media_asset_id)
        if asset is None:
            raise CitationIntegrityError("media assignment is not grounded in story evidence")
        checksum = getattr(asset, "checksum_sha256", None)
        if (
            getattr(asset, "fetch_status", None) != "downloaded"
            or not getattr(asset, "storage_path", None)
            or not isinstance(checksum, str)
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
        ):
            raise CitationIntegrityError("media assignment is not downloaded and checksum verified")


async def trusted_story_media(
    session: Any,
    evidence: dict[UUID, Any],
    *,
    lock_rows: bool = False,
) -> tuple[dict[UUID, MediaAsset], list[dict[str, Any]]]:
    content_item_ids = {
        record.content_item_id
        for record in evidence.values()
        if record.content_item_id is not None
    }
    if not content_item_ids:
        return {}, []
    link_statement = (
        select(ItemMedia)
        .where(ItemMedia.content_item_id.in_(content_item_ids))
        .order_by(
            ItemMedia.content_item_id,
            ItemMedia.sort_order,
            ItemMedia.media_asset_id,
        )
    )
    if lock_rows:
        # ItemMedia is append/update-only in ingestion. Read a fresh snapshot,
        # then lock assets in the same direction ingestion writes them.
        link_statement = link_statement.execution_options(populate_existing=True)
    links = list(await session.scalars(link_statement))
    asset_ids = {link.media_asset_id for link in links}
    if not asset_ids:
        return {}, []
    asset_statement = (
        select(MediaAsset)
        .where(MediaAsset.id.in_(asset_ids))
        .order_by(MediaAsset.id)
    )
    if lock_rows:
        asset_statement = asset_statement.with_for_update().execution_options(populate_existing=True)
    assets = list(await session.scalars(asset_statement))
    assets_by_id = {asset.id: asset for asset in assets}
    authorized = {
        asset.id: asset
        for asset in assets
        if (
            asset.fetch_status == "downloaded"
            and bool(asset.storage_path)
            and isinstance(asset.checksum_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", asset.checksum_sha256) is not None
        )
    }
    projection: list[dict[str, Any]] = []
    projected_ids: set[UUID] = set()
    for link in links:
        asset = assets_by_id.get(link.media_asset_id)
        if asset is None or asset.id in projected_ids:
            continue
        projected_ids.add(asset.id)
        projection.append(
            {
                "id": str(asset.id),
                "kind": asset.kind,
                "mime_type": asset.mime_type,
                "width": asset.width,
                "height": asset.height,
                "duration_seconds": (
                    str(asset.duration_seconds) if asset.duration_seconds is not None else None
                ),
                "byte_length": asset.byte_length,
                "checksum_sha256": asset.checksum_sha256,
                "fetch_status": asset.fetch_status,
                "available": asset.id in authorized,
                "role": link.role,
                "order": link.sort_order,
            }
        )
    return authorized, projection


__all__ = ["trusted_story_media", "validate_payload_media_assignments"]
