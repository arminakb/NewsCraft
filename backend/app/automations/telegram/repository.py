from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.contracts import (
    MaterializedTelegramMedia,
    TelegramEnvelope,
    telegram_envelope_fingerprint,
)
from app.automations.telegram.media import StoredTelegramMedia, TelegramMediaStore
from app.db.models import Source
from app.ingestion.repository import IngestionRepository, build_item_identities
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin
from app.research.schemas import CitationRef
from app.sources.base import MediaCandidate, ParsedSourceItem
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision

DispatchKind = Literal["live", "backfill", "dry_run", "source_edit"]


class TelegramCaptureRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        media_store: TelegramMediaStore,
        ingestion_repository: IngestionRepository | None = None,
        job_repository: JobRepository | None = None,
    ) -> None:
        self.session = session
        self.media_store = media_store
        self.ingestion = ingestion_repository or IngestionRepository(session)
        self.jobs = job_repository or JobRepository(session)

    async def capture_and_enqueue(
        self,
        *,
        route_id: UUID,
        source: Source,
        cursor: AutomationRoute,
        envelope: TelegramEnvelope,
        materialized_media: tuple[MaterializedTelegramMedia, ...],
        dispatch_kind: DispatchKind,
        dry_run_job_id: UUID | None,
        enqueue_process: bool = True,
        process_scheduled_for: datetime | None = None,
        process_max_attempts: int = 3,
        force_review: bool = False,
        filter_reason: str | None = None,
    ) -> AutomationDispatch:
        route = await self.session.scalar(
            select(AutomationRoute).where(AutomationRoute.id == route_id).with_for_update()
        )
        if route is None:
            raise LookupError(f"automation route {route_id} was not found")
        if route is not cursor and route.id != cursor.id:
            raise ValueError("cursor does not belong to the locked automation route")
        if route.source_id != source.id:
            raise ValueError("source does not belong to the locked automation route")

        source_fingerprint = telegram_envelope_fingerprint(envelope)
        source_key = _dispatch_source_key(
            envelope.source_key,
            source_fingerprint=source_fingerprint,
            dispatch_kind=dispatch_kind,
            dry_run_job_id=dry_run_job_id,
        )
        existing = await self.session.scalar(
            select(AutomationDispatch).where(
                AutomationDispatch.route_id == route_id,
                AutomationDispatch.source_key == source_key,
            )
        )
        if existing is not None:
            _update_cursor(route, envelope, source_fingerprint, dispatch_kind)
            await self.session.flush()
            return existing
        parent_revision = None
        if dispatch_kind == "source_edit":
            original_dispatch = await self.session.scalar(
                select(AutomationDispatch)
                .where(
                    AutomationDispatch.route_id == route_id,
                    AutomationDispatch.source_key == envelope.source_key,
                )
                .with_for_update()
            )
            if original_dispatch is None:
                raise ValueError("source edit capture requires an existing source revision")
            story_id = (
                select(StoryRevision.story_id)
                .where(StoryRevision.id == original_dispatch.story_revision_id)
                .scalar_subquery()
            )
            parent_revision = await self.session.scalar(
                select(StoryRevision)
                .where(StoryRevision.story_id == story_id)
                .order_by(StoryRevision.revision_number.desc())
                .limit(1)
                .with_for_update()
            )
            if parent_revision is None:
                raise ValueError("source edit capture could not resolve its prior story revision")

        stored_media = self._persist_materialized_media(materialized_media)
        parsed_item = _parsed_item(envelope, source_fingerprint, stored_media, dispatch_kind)
        run = await self.ingestion.create_run("telegram_capture", "telegram.v1")
        raw_payload = await self.ingestion.save_raw_payload(
            run_id=run.id,
            source_id=source.id,
            payload_kind="telegram_envelope",
            request_url=envelope.source_url
            or f"telegram://{envelope.channel_ref}/{envelope.anchor_message_id}",
            final_url=envelope.source_url,
            http_status=None,
            headers={},
            content_type="text/plain",
            raw_text=envelope.text,
            parser_warnings=[],
        )
        source_item = await self.ingestion.upsert_source_item(
            run.id,
            source.id,
            raw_payload.id,
            parsed_item,
        )
        await self.session.flush()
        identities = build_item_identities(source, parsed_item)
        if dispatch_kind == "source_edit":
            identities = [identity for identity in identities if identity["identity_type"] == "telegram_post"]
        content_item = await self.ingestion.upsert_content_item(source, source_item, parsed_item, identities)
        await self.ingestion.attach_identities(
            content_item_id=content_item.id,
            source_item_id=source_item.id,
            source_id=source.id,
            identities=identities,
        )
        media_assets = await self.ingestion.upsert_media_assets(parsed_item)
        await self.ingestion.attach_item_media(content_item.id, media_assets, parsed_item)
        await self.ingestion.finish_run(run.id, "succeeded", {"captured": 1, "media": len(media_assets)})

        story = None
        if parent_revision is None:
            story = Story(
                title=_story_title(envelope),
                status="telegram_provisional",
                primary_language=source.language_hint or "und",
            )
            self.session.add(story)
            await self.session.flush()
            story_id = story.id
            revision_number = 1
            parent_revision_id = None
            created_by = "telegram_capture"
        else:
            story_id = parent_revision.story_id
            revision_number = parent_revision.revision_number + 1
            parent_revision_id = parent_revision.id
            created_by = "telegram_source_edit"
        content_sha256 = sha256(envelope.text.encode("utf-8")).hexdigest()
        snapshot = StoryEvidenceSnapshot(
            story_id=story_id,
            content_item_id=content_item.id,
            evidence_key=f"content-item:{content_item.id}:{content_sha256}",
            source_url=envelope.source_url,
            title=_story_title(envelope),
            content_text=envelope.text,
            authors=[],
            published_at=envelope.published_at,
            content_sha256=content_sha256,
            snapshot_metadata={
                "peer_id": envelope.peer_id,
                "message_ids": list(envelope.message_ids),
                "grouped_id": envelope.grouped_id,
                "entities": list(envelope.entities),
                "edited_at": envelope.edited_at.isoformat() if envelope.edited_at else None,
                "source_fingerprint": source_fingerprint,
            },
        )
        self.session.add(snapshot)
        await self.session.flush()
        citations = []
        if snapshot.content_text:
            citation = CitationRef(
                evidence_key=snapshot.evidence_key,
                evidence_snapshot_id=snapshot.id,
                source_url=snapshot.source_url,
                locator=f"chars:0-{len(snapshot.content_text)}",
                excerpt_sha256=snapshot.content_sha256,
            )
            citations.append(citation.model_dump(mode="json"))
        revision = StoryRevision(
            story_id=story_id,
            parent_revision_id=parent_revision_id,
            revision_number=revision_number,
            narrative=envelope.text,
            facts=[],
            disagreements=[],
            angles=[],
            citations=citations,
            created_by=created_by,
        )
        self.session.add(revision)
        await self.session.flush()
        link = StoryEvidenceLink(
            story_revision_id=revision.id,
            evidence_snapshot_id=snapshot.id,
            claim_key="telegram.source",
            relationship="supports",
        )
        self.session.add(link)
        await self.session.flush()

        dispatch = AutomationDispatch(
            route_id=route_id,
            source_item_id=source_item.id,
            story_revision_id=revision.id,
            source_key=source_key,
            source_fingerprint=source_fingerprint,
            source_message_ids=list(envelope.message_ids),
            dispatch_kind=dispatch_kind,
            status="captured" if enqueue_process else "filtered",
        )
        self.session.add(dispatch)
        await self.session.flush()
        enqueue_result = None
        if enqueue_process:
            enqueue_result = await self.jobs.enqueue_job(
                job_type="telegram.route.process",
                payload={"dispatch_id": str(dispatch.id), "force_review": force_review},
                idempotency_key=f"telegram-process:{route_id}:{dispatch.source_key}",
                origin=JobOrigin.AUTOMATION,
                scheduled_for=process_scheduled_for,
                max_attempts=process_max_attempts,
            )
        _update_cursor(route, envelope, source_fingerprint, dispatch_kind)
        await self.session.flush()
        self.session.add(
            WorkflowEvent(
                workflow_job_id=enqueue_result.job.id if enqueue_result is not None else None,
                event_type="telegram.source.captured",
                actor="automation",
                event_data=redact_event_data(
                    {
                        "route_id": str(route_id),
                        "dispatch_id": str(dispatch.id),
                        "source_item_id": str(source_item.id),
                        "message_ids": list(envelope.message_ids),
                        "media_count": len(media_assets),
                        "filter_reason": filter_reason,
                    }
                ),
            )
        )
        await self.session.flush()
        return dispatch

    def _persist_materialized_media(
        self, materialized_media: tuple[MaterializedTelegramMedia, ...]
    ) -> tuple[tuple[MaterializedTelegramMedia, StoredTelegramMedia], ...]:
        stored = []
        for materialized in sorted(materialized_media, key=lambda item: item.reference.position):
            content = materialized.path.read_bytes()
            value = self.media_store.persist(
                content,
                mime_type=materialized.mime_type,
                file_name=materialized.reference.file_name,
                kind=materialized.reference.kind,
            )
            stored.append((materialized, value))
        return tuple(stored)

    @staticmethod
    def cleanup_staged_media(materialized_media: tuple[MaterializedTelegramMedia, ...]) -> None:
        """Remove staging files only after the caller's transaction has committed."""

        for item in materialized_media:
            item.path.unlink(missing_ok=True)


def _dispatch_source_key(
    source_key: str,
    *,
    source_fingerprint: str,
    dispatch_kind: DispatchKind,
    dry_run_job_id: UUID | None,
) -> str:
    if dispatch_kind == "dry_run":
        if dry_run_job_id is None:
            raise ValueError("dry_run_job_id is required for a dry-run capture")
        return f"dry:{dry_run_job_id}:{source_key}"
    if dispatch_kind == "source_edit":
        return f"{source_key}:edit:{source_fingerprint}"
    return source_key


def _parsed_item(
    envelope: TelegramEnvelope,
    source_fingerprint: str,
    stored_media: tuple[tuple[MaterializedTelegramMedia, StoredTelegramMedia], ...],
    dispatch_kind: DispatchKind,
) -> ParsedSourceItem:
    external_id = f"telegram:{envelope.peer_id}:{envelope.anchor_message_id}"
    if dispatch_kind == "source_edit":
        external_id = f"{external_id}:edit:{source_fingerprint}"
    candidates = []
    for materialized, stored in stored_media:
        identity = sha256(materialized.reference.key.encode("utf-8")).hexdigest()
        candidates.append(
            MediaCandidate(
                original_url=f"telegram-media:{identity}",
                normalized_url=f"telegram-media:{identity}",
                kind="image" if stored.kind == "photo" else stored.kind,
                source_field="telegram_capture",
                mime_type=stored.mime_type,
                storage_path=str(stored.path),
                checksum_sha256=stored.checksum_sha256,
                byte_length=stored.byte_length,
                fetch_status="downloaded",
            )
        )
    return ParsedSourceItem(
        external_id_raw=external_id,
        external_id_norm=external_id,
        source_url=envelope.source_url,
        source_url_norm=envelope.source_url,
        canonical_url_candidate=envelope.source_url,
        title=_story_title(envelope),
        summary=envelope.text[:500],
        content_html=envelope.html,
        content_text=envelope.text,
        author=None,
        categories=[],
        published_raw=envelope.published_at.isoformat(),
        published_at=envelope.published_at,
        date_parse_status="parsed",
        media_candidates=candidates,
        parser_meta={
            "content_text": envelope.text,
            "message_ids": list(envelope.message_ids),
            "grouped_id": envelope.grouped_id,
            "entities": list(envelope.entities),
            "edited_at": envelope.edited_at.isoformat() if envelope.edited_at else None,
            "source_fingerprint": source_fingerprint,
        },
    )


def _story_title(envelope: TelegramEnvelope) -> str:
    first_line = next((line.strip() for line in envelope.text.splitlines() if line.strip()), "")
    return first_line[:500] or f"Telegram post {envelope.anchor_message_id}"


def _update_cursor(
    route: AutomationRoute,
    envelope: TelegramEnvelope,
    source_fingerprint: str,
    dispatch_kind: DispatchKind,
) -> None:
    if dispatch_kind not in {"live", "source_edit"}:
        return
    state = dict(route.cursor_state or {})
    recent = dict(state.get("recent_fingerprints") or {})
    recent[str(envelope.anchor_message_id)] = source_fingerprint
    retained = sorted(recent.items(), key=lambda item: int(item[0]), reverse=True)[:50]
    state["recent_fingerprints"] = dict(retained)
    if dispatch_kind == "live":
        current = state.get("last_message_id")
        highest = max(envelope.message_ids)
        state["last_message_id"] = max(int(current), highest) if current is not None else highest
    route.cursor_state = state
