from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from app.db.models import MediaAsset
from app.sources.base import MediaCandidate, ParsedSourceItem


def dedupe_media_candidates(candidates: list[MediaCandidate]) -> list[MediaCandidate]:
    """Collapse candidates that point at one URL, keeping the strongest claim."""

    strongest: dict[str, MediaCandidate] = {}
    order: list[str] = []
    for candidate in candidates:
        existing = strongest.get(candidate.normalized_url)
        if existing is None:
            strongest[candidate.normalized_url] = candidate
            order.append(candidate.normalized_url)
        elif candidate.confidence > existing.confidence:
            strongest[candidate.normalized_url] = candidate
    return [strongest[url] for url in order]


def plan_item_media_rows(
    content_item_id: UUID,
    media_assets: list[MediaAsset],
    parsed_item: ParsedSourceItem,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates_by_url = {
        candidate.normalized_url: candidate for candidate in dedupe_media_candidates(parsed_item.media_candidates)
    }
    primary_image_assigned = False

    for sort_order, media_asset in enumerate(media_assets):
        candidate = candidates_by_url.get(media_asset.normalized_url)
        role = _media_role(media_asset, candidate, primary_image_assigned)
        if role == "primary_image":
            primary_image_assigned = True
        rows.append(
            {
                "content_item_id": content_item_id,
                "media_asset_id": media_asset.id,
                "role": role,
                "sort_order": sort_order,
                "confidence": _media_confidence(media_asset, candidate),
                "extracted_from": candidate.source_field if candidate else media_asset.source_field,
            }
        )
    return rows


def media_asset_values(candidate: MediaCandidate, url_hash: str) -> dict[str, Any]:
    quality = _classify_media(candidate)
    return {
        "original_url": candidate.original_url,
        "normalized_url": candidate.normalized_url,
        "url_hash": url_hash,
        "kind": candidate.kind,
        "mime_type": candidate.mime_type,
        "width": candidate.width,
        "height": candidate.height,
        "alt_text": candidate.alt_text,
        "title": candidate.title,
        "source_field": candidate.source_field,
        "storage_path": candidate.storage_path,
        "checksum_sha256": candidate.checksum_sha256,
        "byte_length": candidate.byte_length,
        "fetch_status": candidate.fetch_status,
        "media_quality": quality["media_quality"],
        "media_confidence": quality["media_confidence"],
        "media_source_type": quality["media_source_type"],
        "asset_role": quality["asset_role"],
        "is_primary_candidate": quality["is_primary_candidate"],
        "is_primary": False,
        "raw_metadata": {
            "confidence": candidate.confidence,
            "quality_reasons": quality["quality_reasons"],
        },
    }


def apply_media_candidate(asset: MediaAsset, candidate: MediaCandidate, url_hash: str) -> None:
    values = media_asset_values(candidate, url_hash)
    stored_asset = bool(asset.storage_path)
    if stored_asset:
        values["media_source_type"] = "stored"
    for key, value in values.items():
        if stored_asset and key in {
            "source_field",
            "media_quality",
            "media_confidence",
            "media_source_type",
            "asset_role",
            "is_primary_candidate",
        }:
            if key == "media_source_type":
                asset.media_source_type = "stored"
            continue
        if key in {"storage_path", "checksum_sha256", "byte_length", "mime_type", "width", "height"} and value is None:
            continue
        if key == "mime_type" and stored_asset and candidate.storage_path is None:
            continue
        if key in {"fetch_status", "raw_metadata"} and getattr(asset, key) not in (None, {}, "remote_only"):
            continue
        setattr(asset, key, value)


def _media_role(
    media_asset: MediaAsset,
    candidate: MediaCandidate | None,
    primary_image_assigned: bool,
) -> str:
    source_field = candidate.source_field if candidate else media_asset.source_field
    asset_role = getattr(media_asset, "asset_role", None) or _asset_role(media_asset.kind, source_field)
    if asset_role == "tracking_pixel" or getattr(media_asset, "media_quality", None) == "tracking":
        return "tracking_pixel"
    if _can_be_primary(media_asset, candidate) and not primary_image_assigned:
        return "primary_image"
    if asset_role in {"thumbnail", "inline_image", "video", "document", "preview", "unknown"}:
        return asset_role
    return "unknown"


def _classify_media(candidate: MediaCandidate) -> dict[str, Any]:
    role = _asset_role(candidate.kind, candidate.source_field)
    source_type = _media_source_type(candidate.normalized_url)
    confidence = Decimal(str(candidate.confidence))
    reasons: list[str] = []

    if _is_tracking_pixel(candidate):
        return {
            "media_quality": "tracking",
            "media_confidence": Decimal("0.05"),
            "media_source_type": source_type,
            "asset_role": "tracking_pixel",
            "is_primary_candidate": False,
            "quality_reasons": ["tracking_pixel"],
        }
    if candidate.confidence < 0.4:
        reasons.append("low_candidate_confidence")
        quality = "low"
        confidence = min(confidence, Decimal("0.30"))
    elif candidate.kind == "image" and _is_tiny_image(candidate):
        reasons.append("tiny_image")
        quality = "low"
        confidence = min(confidence, Decimal("0.30"))
    elif role == "unknown":
        reasons.append("unknown_role")
        quality = "unknown"
        confidence = min(confidence, Decimal("0.20"))
    else:
        quality = "good"
        reasons.append("usable_media")

    return {
        "media_quality": quality,
        "media_confidence": confidence,
        "media_source_type": source_type,
        "asset_role": role,
        "is_primary_candidate": quality == "good" and candidate.kind == "image",
        "quality_reasons": reasons,
    }


def _asset_role(kind: str, source_field: str | None) -> str:
    if source_field == "media_thumbnail":
        return "thumbnail"
    if source_field == "link_preview_image":
        return "preview"
    if kind == "image":
        return "inline_image"
    if kind == "video":
        return "video"
    if kind == "document":
        return "document"
    return "unknown"


def _media_source_type(url: str) -> str:
    host = urlsplit(url).hostname or ""
    if "cdn-telegram.org" in host:
        return "temporary_external"
    return "external"


def _is_tracking_pixel(candidate: MediaCandidate) -> bool:
    if _is_medium_stat_url(candidate.normalized_url):
        return True
    return (
        candidate.kind == "image"
        and candidate.width is not None
        and candidate.height is not None
        and (candidate.width <= 2 or candidate.height <= 2)
    )


def _is_medium_stat_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    return host.endswith("medium.com") and (parsed.path.startswith("/_/stat") or "event=" in parsed.query)


def _is_tiny_image(candidate: MediaCandidate) -> bool:
    if candidate.width is None or candidate.height is None:
        return False
    return candidate.width < 120 or candidate.height < 90


def _can_be_primary(media_asset: MediaAsset, candidate: MediaCandidate | None) -> bool:
    explicit_candidate = getattr(media_asset, "is_primary_candidate", None)
    if explicit_candidate is False:
        return False
    if media_asset.kind != "image":
        return False
    if getattr(media_asset, "media_quality", None) in {"tracking", "low", "unknown"}:
        return False
    if candidate and candidate.confidence < 0.4:
        return False
    if candidate and _is_tracking_pixel(candidate):
        return False
    return True


def _media_confidence(media_asset: MediaAsset, candidate: MediaCandidate | None) -> Decimal:
    value = getattr(media_asset, "media_confidence", None)
    if value is not None:
        return Decimal(str(value))
    return Decimal(str(candidate.confidence if candidate else 1.0))
