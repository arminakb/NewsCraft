from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.buckets import assign_rewrite_bucket
from app.content.classification import classify_content_item
from app.content.scoring import classify_and_score
from app.db.models import (
    ContentItem,
    IngestRun,
    ItemIdentity,
    ItemMedia,
    MediaAsset,
    RawPayload,
    RewriteCandidate,
    Source,
    SourceItem,
)
from app.normalization.fingerprints import content_hash, title_date_fingerprint
from app.normalization.text import fingerprint_text, infer_direction
from app.normalization.titles import normalize_telegram_title
from app.normalization.urls import hash_value
from app.sources.base import MediaCandidate, ParsedSourceItem

GLOBAL_STRONG_IDENTITY_INDEX_WHERE = text("scope = 'global' AND is_strong")
SOURCE_STRONG_IDENTITY_INDEX_WHERE = text("scope = 'source' AND is_strong")


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


def plan_item_media_rows(
    content_item_id: UUID,
    media_assets: list[MediaAsset],
    parsed_item: ParsedSourceItem,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates_by_url = {candidate.normalized_url: candidate for candidate in parsed_item.media_candidates}
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
                "confidence": Decimal(str(candidate.confidence if candidate else 1.0)),
                "extracted_from": candidate.source_field if candidate else media_asset.source_field,
            }
        )
    return rows


class IngestionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_run(self, trigger: str, parser_version: str) -> IngestRun:
        run = IngestRun(trigger=trigger, parser_version=parser_version, status="running")
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish_run(self, run_id: UUID, status: str, stats: dict, error: str | None = None) -> None:
        await self.session.execute(
            update(IngestRun)
            .where(IngestRun.id == run_id)
            .values(finished_at=func.now(), status=status, stats=stats, error=error)
        )

    async def get_active_sources(self, platforms: list[str] | None = None) -> list[Source]:
        stmt: Select[tuple[Source]] = select(Source).where(Source.active.is_(True))
        if platforms:
            stmt = stmt.where(Source.platform.in_(platforms))
        rows = await self.session.scalars(stmt.order_by(Source.name))
        return list(rows)

    async def save_raw_payload(
        self,
        run_id: UUID,
        source_id: UUID,
        payload_kind: str,
        request_url: str,
        final_url: str | None,
        http_status: int | None,
        headers: dict,
        content_type: str | None,
        raw_text: str,
        parser_warnings: list[str],
    ) -> RawPayload:
        payload = RawPayload(
            run_id=run_id,
            source_id=source_id,
            payload_kind=payload_kind,
            request_url=request_url,
            final_url=final_url,
            http_status=http_status,
            headers=headers,
            content_type=content_type,
            body_sha256=sha256(raw_text.encode("utf-8")).hexdigest(),
            raw_text=raw_text,
            parser_warnings=parser_warnings,
        )
        self.session.add(payload)
        await self.session.flush()
        return payload

    async def upsert_source_item(
        self,
        run_id: UUID,
        source_id: UUID,
        raw_payload_id: UUID,
        parsed_item: ParsedSourceItem,
    ) -> SourceItem:
        values = _source_item_values(run_id, source_id, raw_payload_id, parsed_item)
        if not parsed_item.external_id_norm:
            item = SourceItem(**values)
            self.session.add(item)
            await self.session.flush()
            return item

        stmt = (
            insert(SourceItem)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[SourceItem.source_id, SourceItem.external_id_norm],
                index_where=SourceItem.external_id_norm.is_not(None),
                set_={
                    "run_id": run_id,
                    "raw_payload_id": raw_payload_id,
                    "source_url": parsed_item.source_url,
                    "source_url_norm": parsed_item.source_url_norm,
                    "canonical_url_candidate": parsed_item.canonical_url_candidate,
                    "title_raw": parsed_item.title,
                    "summary_raw": parsed_item.summary,
                    "content_html_raw": parsed_item.content_html,
                    "content_text_raw": parsed_item.content_text,
                    "author_raw": parsed_item.author,
                    "categories": parsed_item.categories,
                    "published_raw": parsed_item.published_raw,
                    "parser_meta": parsed_item.parser_meta,
                    "last_seen_at": func.now(),
                },
            )
            .returning(SourceItem)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def find_content_item_by_identities(self, identities: list[dict[str, Any]]) -> ContentItem | None:
        clauses = []
        for identity in identities:
            if not identity["is_strong"]:
                continue
            clause = and_(
                ItemIdentity.identity_type == identity["identity_type"],
                ItemIdentity.identity_hash == identity["identity_hash"],
                ItemIdentity.scope == identity["scope"],
            )
            if identity["scope"] == "source":
                clause = and_(clause, ItemIdentity.source_id == identity["source_id"])
            clauses.append(clause)

        if not clauses:
            return None

        stmt = select(ContentItem).join(ItemIdentity).where(or_(*clauses)).limit(1)
        return await self.session.scalar(stmt)

    async def upsert_content_item(
        self,
        source: Source,
        source_item: SourceItem,
        parsed_item: ParsedSourceItem,
        identities: list[dict[str, Any]],
    ) -> ContentItem:
        existing = await self.find_content_item_by_identities(identities)
        values = _content_item_values(source, parsed_item)
        if existing:
            for key, value in values.items():
                if key in {"first_seen_at", "created_at"}:
                    continue
                setattr(existing, key, value)
            existing.last_seen_at = datetime.now(UTC)
            source_item.content_item_id = existing.id
            await self.session.flush()
            await self.upsert_rewrite_candidate(existing)
            return existing

        content_item = ContentItem(**values)
        self.session.add(content_item)
        await self.session.flush()
        source_item.content_item_id = content_item.id
        await self.upsert_rewrite_candidate(content_item)
        await self.session.flush()
        return content_item

    async def upsert_rewrite_candidate(self, content_item: ContentItem) -> None:
        values = plan_rewrite_candidate(content_item)
        if values:
            await self.session.execute(_rewrite_candidate_insert_statement(values))
            await self.session.flush()

    async def attach_identities(
        self,
        content_item_id: UUID,
        source_item_id: UUID,
        source_id: UUID,
        identities: list[dict[str, Any]],
    ) -> None:
        for identity in identities:
            values = {
                **identity,
                "content_item_id": content_item_id,
                "source_item_id": source_item_id,
                "source_id": identity["source_id"] or source_id,
            }
            stmt = _identity_insert_statement(values)
            if stmt is not None:
                await self.session.execute(stmt)
            else:
                self.session.add(ItemIdentity(**values))
        await self.session.flush()

    async def upsert_media_assets(self, parsed_item: ParsedSourceItem) -> list[MediaAsset]:
        assets: list[MediaAsset] = []
        for candidate in parsed_item.media_candidates:
            url_hash = hash_value(candidate.normalized_url)
            existing = await self.session.scalar(select(MediaAsset).where(MediaAsset.url_hash == url_hash))
            if existing:
                _apply_media_candidate(existing, candidate, url_hash)
                assets.append(existing)
                continue
            asset = MediaAsset(**_media_asset_values(candidate, url_hash))
            self.session.add(asset)
            assets.append(asset)
        await self.session.flush()
        return assets

    async def attach_item_media(
        self,
        content_item_id: UUID,
        media_assets: list[MediaAsset],
        parsed_item: ParsedSourceItem,
    ) -> None:
        rows = plan_item_media_rows(content_item_id, media_assets, parsed_item)
        primary_image_id = next((row["media_asset_id"] for row in rows if row["role"] == "primary_image"), None)
        for row in rows:
            stmt = (
                insert(ItemMedia)
                .values(**row)
                .on_conflict_do_update(
                    index_elements=[ItemMedia.content_item_id, ItemMedia.media_asset_id, ItemMedia.role],
                    set_={
                        "sort_order": row["sort_order"],
                        "confidence": row["confidence"],
                        "extracted_from": row["extracted_from"],
                    },
                )
            )
            await self.session.execute(stmt)
        if primary_image_id:
            await self.session.execute(
                update(ContentItem).where(ContentItem.id == content_item_id).values(primary_image_id=primary_image_id)
            )
        await self.session.flush()


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


def _source_item_values(
    run_id: UUID,
    source_id: UUID,
    raw_payload_id: UUID,
    parsed_item: ParsedSourceItem,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "run_id": run_id,
        "raw_payload_id": raw_payload_id,
        "external_id_raw": parsed_item.external_id_raw,
        "external_id_norm": parsed_item.external_id_norm,
        "source_url": parsed_item.source_url,
        "source_url_norm": parsed_item.source_url_norm,
        "canonical_url_candidate": parsed_item.canonical_url_candidate,
        "title_raw": parsed_item.title,
        "summary_raw": parsed_item.summary,
        "content_html_raw": parsed_item.content_html,
        "content_text_raw": parsed_item.content_text,
        "author_raw": parsed_item.author,
        "categories": parsed_item.categories,
        "published_raw": parsed_item.published_raw,
        "parser_meta": parsed_item.parser_meta,
    }


def _identity_insert_statement(values: dict[str, Any]):
    if not values["is_strong"]:
        return None

    stmt = insert(ItemIdentity).values(**values)
    update_values = {
        "content_item_id": values["content_item_id"],
        "source_item_id": values["source_item_id"],
    }
    if values["scope"] == "global":
        return stmt.on_conflict_do_update(
            index_elements=[ItemIdentity.identity_type, ItemIdentity.identity_hash],
            index_where=GLOBAL_STRONG_IDENTITY_INDEX_WHERE,
            set_=update_values,
        )
    if values["scope"] == "source":
        return stmt.on_conflict_do_update(
            index_elements=[ItemIdentity.source_id, ItemIdentity.identity_type, ItemIdentity.identity_hash],
            index_where=SOURCE_STRONG_IDENTITY_INDEX_WHERE,
            set_=update_values,
        )
    return None


def plan_rewrite_candidate(content_item: ContentItem) -> dict[str, Any]:
    if not content_item.rewrite_bucket:
        return {}
    metadata = content_item.classification_metadata or {}
    assignment = assign_rewrite_bucket(
        content_item.content_type,
        source_domain=metadata.get("source_domain", ""),
        source_name=metadata.get("source_name", ""),
    )
    return {
        "content_item_id": content_item.id,
        "bucket_type": content_item.rewrite_bucket,
        "priority_score": int(content_item.score or 0),
        "status": assignment.status,
        "reason": assignment.reason,
    }


def _rewrite_candidate_insert_statement(values: dict[str, Any]):
    return (
        insert(RewriteCandidate)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[RewriteCandidate.content_item_id, RewriteCandidate.bucket_type],
            set_={
                "priority_score": values["priority_score"],
                "status": values["status"],
                "reason": values["reason"],
                "updated_at": func.now(),
            },
        )
    )


def _content_item_values(source: Source, parsed_item: ParsedSourceItem) -> dict[str, Any]:
    now = datetime.now(UTC)
    sort_at = parsed_item.published_at or now
    canonical_url = parsed_item.canonical_url_candidate or parsed_item.source_url_norm
    title_normalization = _title_normalization(source, parsed_item)
    normalized_item = _parsed_item_with_title(parsed_item, title_normalization.title)
    direction = infer_direction(normalized_item.content_text)
    classification = classify_and_score(source, normalized_item)
    content_classification = classify_content_item(source, normalized_item)
    bucket_assignment = assign_rewrite_bucket(
        content_classification.content_type,
        source_domain=content_classification.metadata.get("source_domain", ""),
        source_name=source.name,
    )
    metrics = dict(normalized_item.parser_meta)
    metrics["classification"] = classification.signals
    return {
        "item_type": "telegram_post" if source.platform == "telegram_public" else "article",
        "canonical_url": canonical_url,
        "canonical_url_hash": hash_value(canonical_url) if canonical_url else None,
        "title": normalized_item.title,
        "title_fingerprint": fingerprint_text(normalized_item.title),
        "summary": normalized_item.summary,
        "content_text": normalized_item.content_text,
        "content_html_sanitized": normalized_item.content_html,
        "language_code": source.language_hint,
        "script_code": "Arab" if direction == "rtl" else "Latn",
        "direction": direction,
        "authors": [normalized_item.author] if normalized_item.author else [],
        "tags": classification.tags,
        "published_at": normalized_item.published_at,
        "sort_at": sort_at,
        "date_raw": normalized_item.published_raw,
        "date_source": "source",
        "date_parse_status": normalized_item.date_parse_status,
        "primary_source_id": source.id,
        "score": classification.score,
        "metrics": metrics,
        "content_type": content_classification.content_type,
        "content_type_confidence": Decimal(str(content_classification.confidence)),
        "classification_reasons": content_classification.reasons,
        "classification_metadata": {
            **content_classification.metadata,
            "quality_flags": content_classification.quality_flags,
        },
        "rewrite_bucket": bucket_assignment.bucket_type,
        "title_quality": title_normalization.quality,
        "title_was_generated": title_normalization.was_generated,
        "quality_status": (
            "low_signal"
            if content_classification.content_type == "low_signal" or title_normalization.low_signal
            else "needs_review"
        ),
        "first_seen_at": now,
        "last_seen_at": now,
        "created_at": now,
        "updated_at": now,
    }


def _title_normalization(source: Source, parsed_item: ParsedSourceItem):
    if source.platform == "telegram_public":
        return normalize_telegram_title(parsed_item.title, parsed_item.content_text)
    return normalize_telegram_title(parsed_item.title, parsed_item.title)


def _parsed_item_with_title(parsed_item: ParsedSourceItem, title: str) -> ParsedSourceItem:
    if parsed_item.title == title:
        return parsed_item
    return ParsedSourceItem(
        external_id_raw=parsed_item.external_id_raw,
        external_id_norm=parsed_item.external_id_norm,
        source_url=parsed_item.source_url,
        source_url_norm=parsed_item.source_url_norm,
        canonical_url_candidate=parsed_item.canonical_url_candidate,
        title=title,
        summary=parsed_item.summary,
        content_html=parsed_item.content_html,
        content_text=parsed_item.content_text,
        author=parsed_item.author,
        categories=parsed_item.categories,
        published_raw=parsed_item.published_raw,
        published_at=parsed_item.published_at,
        date_parse_status=parsed_item.date_parse_status,
        media_candidates=parsed_item.media_candidates,
        parser_meta=parsed_item.parser_meta,
    )


def _media_asset_values(candidate: MediaCandidate, url_hash: str) -> dict[str, Any]:
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
        "fetch_status": "remote_only",
        "raw_metadata": {"confidence": candidate.confidence},
    }


def _apply_media_candidate(asset: MediaAsset, candidate: MediaCandidate, url_hash: str) -> None:
    values = _media_asset_values(candidate, url_hash)
    for key, value in values.items():
        if key in {"fetch_status", "raw_metadata"} and getattr(asset, key) not in (None, {}, "remote_only"):
            continue
        setattr(asset, key, value)


def _media_role(
    media_asset: MediaAsset,
    candidate: MediaCandidate | None,
    primary_image_assigned: bool,
) -> str:
    source_field = candidate.source_field if candidate else media_asset.source_field
    if media_asset.kind == "image" and not primary_image_assigned:
        return "primary_image"
    if source_field in {"media_thumbnail", "link_preview_image"}:
        return "thumbnail"
    if media_asset.kind == "image":
        return "inline_image"
    if source_field == "enclosure":
        return "enclosure"
    if media_asset.kind == "document":
        return "attachment"
    return "attachment"
