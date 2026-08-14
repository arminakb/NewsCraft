from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.buckets import assign_rewrite_bucket
from app.content.classification import classify_content_item, classify_content_taxonomy
from app.content.readiness import evaluate_rewrite_readiness
from app.content.scoring import score_content_item
from app.core.redaction import redact_secrets, redact_string
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
from app.ingestion.identity import build_item_identities
from app.ingestion.media_policy import (
    apply_media_candidate,
    dedupe_media_candidates,
    media_asset_values,
    plan_item_media_rows,
)
from app.ingestion.runs import ingest_run_counters, new_ingest_run
from app.normalization.text import fingerprint_text, infer_direction, infer_script, normalized_language_hint
from app.normalization.titles import normalize_title
from app.normalization.urls import hash_value
from app.sources.base import MediaCandidate, ParsedSourceItem

GLOBAL_STRONG_IDENTITY_INDEX_WHERE = text("scope = 'global' AND is_strong")
SOURCE_STRONG_IDENTITY_INDEX_WHERE = text("scope = 'source' AND is_strong")
SOURCE_WEAK_IDENTITY_INDEX_WHERE = text("scope = 'source' AND NOT is_strong")
LIVE_MEDIA_ASSET_INDEX_WHERE = text("fetch_status <> 'expired'")

__all__ = ["IngestionRepository", "build_item_identities"]


class IngestionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_run(self, trigger: str, parser_version: str) -> IngestRun:
        run = new_ingest_run(trigger=trigger, parser_version=parser_version, status="running")
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish_run(self, run_id: UUID, status: str, stats: dict, error: str | None = None) -> None:
        durable_stats = redact_secrets(stats)
        counters = ingest_run_counters(stats)
        await self.session.execute(
            update(IngestRun)
            .where(IngestRun.id == run_id)
            .values(
                finished_at=func.now(),
                status=status,
                stats=durable_stats if isinstance(durable_stats, dict) else {},
                error=redact_string(error) if error is not None else None,
                processed_count=counters.processed,
                success_count=counters.success,
                failure_count=counters.failure,
            )
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
        durable_headers = redact_secrets(headers)
        durable_warnings = redact_secrets(parser_warnings)
        durable_raw_text = redact_string(raw_text) if http_status is not None and http_status >= 400 else raw_text
        payload = RawPayload(
            run_id=run_id,
            source_id=source_id,
            payload_kind=payload_kind,
            request_url=redact_string(request_url),
            final_url=redact_string(final_url) if final_url is not None else None,
            http_status=http_status,
            headers=durable_headers if isinstance(durable_headers, dict) else {},
            content_type=(redact_string(content_type) if content_type is not None else None),
            body_sha256=sha256(durable_raw_text.encode("utf-8")).hexdigest(),
            raw_text=durable_raw_text,
            parser_warnings=(durable_warnings if isinstance(durable_warnings, list) else []),
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
        item, _created = await self.upsert_source_item_with_created(
            run_id=run_id,
            source_id=source_id,
            raw_payload_id=raw_payload_id,
            parsed_item=parsed_item,
        )
        return item

    async def upsert_source_item_with_created(
        self,
        run_id: UUID,
        source_id: UUID,
        raw_payload_id: UUID,
        parsed_item: ParsedSourceItem,
    ) -> tuple[SourceItem, bool]:
        values = _source_item_values(run_id, source_id, raw_payload_id, parsed_item)
        if not parsed_item.external_id_norm:
            item = SourceItem(**values)
            self.session.add(item)
            await self.session.flush()
            return item, True

        insert_statement = (
            insert(SourceItem)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[SourceItem.source_id, SourceItem.external_id_norm],
                index_where=SourceItem.external_id_norm.is_not(None),
            )
            .returning(SourceItem)
        )
        inserted = (await self.session.execute(insert_statement)).scalar_one_or_none()
        if inserted is not None:
            return inserted, True

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
        return result.scalar_one(), False

    async def find_content_items_by_identities(self, identities: list[dict[str, Any]]) -> list[ContentItem]:
        """Return every content item a strong identity points at, best match first.

        The order is total (best identity confidence, then oldest sighting, then
        id), so the same input always binds to the same content item no matter
        which plan PostgreSQL picks. Any further entries are duplicates that the
        caller merges into the winner.
        """
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
            return []

        ranked = (
            select(
                ItemIdentity.content_item_id.label("content_item_id"),
                func.max(ItemIdentity.confidence).label("best_confidence"),
            )
            .where(ItemIdentity.content_item_id.is_not(None), or_(*clauses))
            .group_by(ItemIdentity.content_item_id)
            .subquery()
        )
        stmt = (
            select(ContentItem)
            .join(ranked, ranked.c.content_item_id == ContentItem.id)
            .order_by(
                ranked.c.best_confidence.desc(),
                ContentItem.first_seen_at.asc(),
                ContentItem.id.asc(),
            )
        )
        return list(await self.session.scalars(stmt))

    async def find_content_item_by_identities(self, identities: list[dict[str, Any]]) -> ContentItem | None:
        matches = await self.find_content_items_by_identities(identities)
        return matches[0] if matches else None

    async def upsert_content_item(
        self,
        source: Source,
        source_item: SourceItem,
        parsed_item: ParsedSourceItem,
        identities: list[dict[str, Any]],
    ) -> ContentItem:
        await self._lock_strong_identities(identities)
        matches = await self.find_content_items_by_identities(identities)
        existing = matches[0] if matches else None
        values = _content_item_values(source, parsed_item)
        if existing:
            await self._merge_duplicate_content_items(existing, matches[1:])
            values = _preserve_more_complete_content(source, existing, parsed_item, values)
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

    async def _merge_duplicate_content_items(self, winner: ContentItem, losers: list[ContentItem]) -> None:
        """Record the merge before `attach_identities` reparents identity rows.

        When one parsed item matches several existing content items, the losing
        rows keep their own history but must point at the surviving row —
        otherwise their identities silently move to the winner and the leftover
        content item stays in the feed as an untracked duplicate.
        """
        loser_ids = [loser.id for loser in losers if loser.id != winner.id]
        if not loser_ids:
            return
        if winner.duplicate_of_id in set(loser_ids):
            winner.duplicate_of_id = None
        await self.session.execute(
            update(ContentItem)
            .where(
                ContentItem.id != winner.id,
                or_(ContentItem.id.in_(loser_ids), ContentItem.duplicate_of_id.in_(loser_ids)),
            )
            .values(duplicate_of_id=winner.id)
        )
        await self.session.flush()

    async def _lock_strong_identities(self, identities: list[dict[str, Any]]) -> None:
        """Serialize creation for any shared durable identity until transaction end."""
        lock_keys = sorted(
            {
                ":".join(
                    (
                        identity["scope"],
                        str(identity["source_id"] or ""),
                        identity["identity_type"],
                        identity["identity_hash"],
                    )
                )
                for identity in identities
                if identity["is_strong"]
            }
        )
        for lock_key in lock_keys:
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity_key, 0))"),
                {"identity_key": lock_key},
            )

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
            await self.session.execute(_identity_insert_statement(values))
        await self.session.flush()

    async def upsert_media_assets(self, parsed_item: ParsedSourceItem) -> list[MediaAsset]:
        # Retention takes SHARE locks in this order before row revalidation.
        # Take the writer fence before any MediaAsset row lock so neither side
        # can hold a row while waiting for the other's table lock.
        await self.session.execute(text("LOCK TABLE content_items, item_media, media_assets IN ROW EXCLUSIVE MODE"))
        assets: list[MediaAsset] = []
        for candidate in dedupe_media_candidates(parsed_item.media_candidates):
            assets.append(await self._upsert_media_asset(candidate))
        await self.session.flush()
        return assets

    async def _upsert_media_asset(self, candidate: MediaCandidate) -> MediaAsset:
        """Bind one candidate to exactly one live media asset row.

        A bare select-then-insert let two concurrent ingest sessions create the
        same asset twice (the table lock is self-compatible and the row lock
        matches nothing when the select misses). The insert now carries the
        live-url_hash conflict target, so at most one writer wins and the loser
        re-reads the winner's row.
        """
        url_hash = hash_value(candidate.normalized_url)
        for _attempt in range(3):
            existing = await self.session.scalar(
                select(MediaAsset)
                .where(
                    MediaAsset.url_hash == url_hash,
                    MediaAsset.fetch_status != "expired",
                )
                .order_by(MediaAsset.updated_at.desc(), MediaAsset.id.desc())
                .limit(1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing is not None:
                apply_media_candidate(existing, candidate, url_hash)
                return existing

            inserted = (
                await self.session.execute(
                    insert(MediaAsset)
                    .values(**media_asset_values(candidate, url_hash))
                    .on_conflict_do_nothing(
                        index_elements=[MediaAsset.url_hash],
                        index_where=LIVE_MEDIA_ASSET_INDEX_WHERE,
                    )
                    .returning(MediaAsset)
                )
            ).scalar_one_or_none()
            if inserted is not None:
                return inserted
        raise RuntimeError(f"Unable to resolve a media asset for url hash {url_hash}")

    async def attach_item_media(
        self,
        content_item_id: UUID,
        media_assets: list[MediaAsset],
        parsed_item: ParsedSourceItem,
    ) -> None:
        # Retention takes SHARE locks in this order before it marks or removes
        # media. Acquire the matching writer locks before refreshing asset rows
        # so a stale ORM instance can never create a reference to a tombstone.
        await self.session.execute(text("LOCK TABLE content_items, item_media, media_assets IN ROW EXCLUSIVE MODE"))
        asset_ids = [asset.id for asset in media_assets]
        live_assets_by_id = {
            asset.id: asset
            for asset in await self.session.scalars(
                select(MediaAsset)
                .where(
                    MediaAsset.id.in_(asset_ids),
                    MediaAsset.fetch_status != "expired",
                )
                .order_by(MediaAsset.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        }
        live_assets = [live_assets_by_id[asset.id] for asset in media_assets if asset.id in live_assets_by_id]
        rows = plan_item_media_rows(content_item_id, live_assets, parsed_item)
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
        # Re-ingestion sees only what the current parse produced. Writing the
        # planned value unconditionally cleared a previously-resolved primary
        # image whenever a later parse shipped no media (or only media that
        # `_can_be_primary` rejects). Publish a new primary when we have one,
        # and otherwise clear the stored one only when this parse actually
        # re-planned that same asset into a non-primary role.
        if primary_image_id is not None:
            await self.session.execute(
                update(ContentItem).where(ContentItem.id == content_item_id).values(primary_image_id=primary_image_id)
            )
        else:
            demoted_asset_ids = {row["media_asset_id"] for row in rows}
            if demoted_asset_ids:
                await self.session.execute(
                    update(ContentItem)
                    .where(
                        ContentItem.id == content_item_id,
                        ContentItem.primary_image_id.in_(demoted_asset_ids),
                    )
                    .values(primary_image_id=None)
                )
        await self.session.flush()


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
    """Build the conflict-aware INSERT for one identity row.

    Every identity NewsCraft writes must land on a partial unique index, so a
    repeated ingest cycle updates the existing row instead of appending a new
    one. Any scope/strength combination without a matching index is rejected
    loudly rather than degrading to an unbounded plain INSERT.
    """
    stmt = insert(ItemIdentity).values(**values)
    update_values = {
        "content_item_id": values["content_item_id"],
        "source_item_id": values["source_item_id"],
    }
    scope = values["scope"]
    if values["is_strong"]:
        if scope == "global":
            return stmt.on_conflict_do_update(
                index_elements=[ItemIdentity.identity_type, ItemIdentity.identity_hash],
                index_where=GLOBAL_STRONG_IDENTITY_INDEX_WHERE,
                set_=update_values,
            )
        if scope == "source":
            return stmt.on_conflict_do_update(
                index_elements=[ItemIdentity.source_id, ItemIdentity.identity_type, ItemIdentity.identity_hash],
                index_where=SOURCE_STRONG_IDENTITY_INDEX_WHERE,
                set_=update_values,
            )
    elif scope == "source":
        return stmt.on_conflict_do_update(
            index_elements=[ItemIdentity.source_id, ItemIdentity.identity_type, ItemIdentity.identity_hash],
            index_where=SOURCE_WEAK_IDENTITY_INDEX_WHERE,
            set_={
                **update_values,
                "identity_value": values["identity_value"],
                "confidence": values["confidence"],
            },
        )
    raise ValueError(f"Unsupported identity scope/strength combination: {scope}/{values['is_strong']}")


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
        "status": assignment.status
        if assignment.status == "excluded"
        else "blocked"
        if content_item.is_rewrite_ready is False
        else "pending",
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
    title_normalization = normalize_title(parsed_item.title, parsed_item.content_text)
    normalized_item = _parsed_item_with_title(parsed_item, title_normalization.title)
    direction = infer_direction(normalized_item.content_text)
    script_code = infer_script(normalized_item.content_text)
    taxonomy = classify_content_taxonomy(source, normalized_item)
    content_classification = classify_content_item(source, normalized_item)
    bucket_assignment = assign_rewrite_bucket(
        content_classification.content_type,
        source_domain=content_classification.metadata.get("source_domain", ""),
        source_name=source.name,
    )
    score_result = score_content_item(
        source,
        normalized_item,
        content_type=content_classification.content_type,
        title_quality=title_normalization.quality,
    )
    metrics = dict(normalized_item.parser_meta)
    metrics["classification"] = taxonomy.signals
    values = {
        "item_type": "telegram_post" if source.platform == "telegram_public" else "article",
        "canonical_url": canonical_url,
        "canonical_url_hash": hash_value(canonical_url) if canonical_url else None,
        "title": normalized_item.title,
        "title_fingerprint": fingerprint_text(normalized_item.title),
        "summary": normalized_item.summary,
        "content_text": normalized_item.content_text,
        "content_html_sanitized": normalized_item.content_html,
        "language_code": normalized_language_hint(source.language_hint, script_code=script_code),
        "script_code": script_code,
        "direction": direction,
        "authors": [normalized_item.author] if normalized_item.author else [],
        "tags": taxonomy.tags,
        "published_at": normalized_item.published_at,
        "sort_at": sort_at,
        "date_raw": normalized_item.published_raw,
        "date_source": "source",
        "date_parse_status": normalized_item.date_parse_status,
        "primary_source_id": source.id,
        "score": score_result.score,
        "metrics": metrics,
        "content_type": content_classification.content_type,
        "content_type_confidence": Decimal(str(content_classification.confidence)),
        "classification_reasons": content_classification.reasons,
        "classification_metadata": {
            **content_classification.metadata,
            "quality_reasons": content_classification.quality_reasons,
        },
        "rewrite_bucket": bucket_assignment.bucket_type,
        "freshness_bucket": score_result.freshness_bucket,
        "source_tier": score_result.source_tier,
        "title_quality": title_normalization.quality,
        "title_was_generated": title_normalization.was_generated,
        "score_breakdown": score_result.breakdown,
        "ranking_metadata": score_result.ranking_metadata,
        "quality_status": (
            "low_signal" if content_classification.quality_reasons or title_normalization.low_signal else "good"
        ),
        "first_seen_at": now,
        "last_seen_at": now,
        "created_at": now,
        "updated_at": now,
    }
    readiness = evaluate_rewrite_readiness(ContentItem(**values))
    values.update(
        {
            "is_rewrite_ready": readiness.is_ready,
            "rewrite_ready_reason": readiness.reason,
            "rewrite_blockers": readiness.blockers,
        }
    )
    return values


def _preserve_more_complete_content(
    source: Source,
    existing: ContentItem,
    parsed_item: ParsedSourceItem,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Keep the fuller stored body — and everything derived from it.

    A summary-only re-parse of an item first seen with full text must not
    downgrade classification, scoring, quality or rewrite readiness, so the
    derived values are recomputed from the preserved body instead of being
    patched on top of excerpt-derived ones.
    """

    incoming_metrics_raw = values.get("metrics")
    incoming_origin = incoming_metrics_raw.get("content_origin") if isinstance(incoming_metrics_raw, dict) else None
    if incoming_origin not in ("source_excerpt", "unavailable"):
        # Only an explicit downgrade re-parse (feed excerpt, or no body at
        # all) may keep the stored body. A source-provided body — or any
        # ingest path that does not mark its origin — is an authoritative
        # edit even when shorter than what we stored.
        return values

    stored_text = existing.content_text or ""
    incoming_text = str(values.get("content_text") or "")
    if _normalized_content_length(incoming_text) >= _normalized_content_length(stored_text):
        return values

    preserved_item = replace(
        parsed_item,
        content_text=stored_text,
        content_html=existing.content_html_sanitized,
    )
    preserved = _content_item_values(source, preserved_item)

    incoming_metrics = dict(preserved.get("metrics") or {})
    stored_metrics = existing.metrics if isinstance(existing.metrics, dict) else {}
    if "content_origin" in stored_metrics:
        incoming_metrics["content_origin"] = stored_metrics["content_origin"]
    else:
        incoming_metrics.pop("content_origin", None)
    preserved["metrics"] = incoming_metrics
    return preserved


def _normalized_content_length(value: str) -> int:
    return len("".join(value.split()))


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
