from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from app.db.models import Source
from app.normalization.fingerprints import content_hash, title_date_fingerprint
from app.normalization.urls import hash_value
from app.sources.base import ParsedSourceItem


def build_item_identities(source: Source, parsed_item: ParsedSourceItem) -> list[dict[str, Any]]:
    identities: list[dict[str, Any]] = []

    if parsed_item.canonical_url_candidate:
        _append_identity(identities, "canonical_url", parsed_item.canonical_url_candidate, "global", True)

    if parsed_item.source_url_norm:
        _append_identity(identities, "normalized_url", parsed_item.source_url_norm, "global", True)

    if source.platform == "telegram_public":
        _append_identity(identities, "telegram_post", parsed_item.external_id_norm, "global", True)
    elif source.platform == "rss" and parsed_item.external_id_norm:
        _append_identity(identities, "rss_guid", parsed_item.external_id_norm, "source", True, source.id)
    elif source.platform == "atom" and parsed_item.external_id_norm:
        _append_identity(identities, "atom_id", parsed_item.external_id_norm, "source", True, source.id)

    if len(parsed_item.content_text.strip()) >= 80:
        _append_identity(
            identities,
            "content_hash",
            content_hash(parsed_item.content_text),
            "global",
            True,
            confidence=Decimal("0.92"),
        )

    date_key = (
        parsed_item.published_at.date().isoformat() if parsed_item.published_at else parsed_item.published_raw or ""
    )
    _append_identity(
        identities,
        "title_date_fingerprint",
        title_date_fingerprint(parsed_item.title, date_key),
        "source",
        False,
        source.id,
        confidence=Decimal("0.55"),
    )

    deduped: dict[tuple[str, str, str, UUID | None], dict[str, Any]] = {}
    for identity in identities:
        key = (
            identity["identity_type"],
            identity["identity_hash"],
            identity["scope"],
            identity["source_id"],
        )
        deduped[key] = identity
    return list(deduped.values())


def _append_identity(
    identities: list[dict[str, Any]],
    identity_type: str,
    identity_value: str,
    scope: str,
    is_strong: bool,
    source_id: UUID | None = None,
    confidence: Decimal = Decimal("1.0"),
) -> None:
    identities.append(
        {
            "identity_type": identity_type,
            "identity_value": identity_value,
            "identity_hash": hash_value(identity_value),
            "scope": scope,
            "source_id": source_id,
            "confidence": confidence,
            "is_strong": is_strong,
        }
    )
