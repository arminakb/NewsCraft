from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, NoReturn
from uuid import UUID

from sqlalchemy import case, exists, false, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContentItem, RawPayload, SourceItem
from app.normalization.fingerprints import fingerprint_text
from app.normalization.urls import hash_value, normalize_url
from app.stories.evidence import (
    EvidenceInput,
    EvidenceRecord,
    build_evidence_key,
    capture_evidence,
    evidence_record_from_snapshot,
)
from app.stories.grouping import GroupingInput, decide_group
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot
from app.stories.states import INBOX, TELEGRAM_PROVISIONAL

CANONICAL_CANDIDATE_LIMIT = 500
STORY_GROUPING_ADVISORY_LOCK_KEY = 0x4E4353544F5259


class EvidenceKeyCollision(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GroupedItemResult:
    content_item_id: UUID
    disposition: Literal["grouped", "skipped", "duplicate", "conflicted"]
    reason: str


@dataclass(frozen=True, slots=True)
class StoryGroupingResult:
    story: Story | None
    items: tuple[GroupedItemResult, ...]
    created_evidence_snapshot_count: int

    @property
    def id(self) -> UUID:
        if self.story is None:
            raise ValueError("conflicted grouping result has no story")
        return self.story.id


@dataclass(frozen=True, slots=True)
class _SnapshotPayload:
    evidence_key: str
    content_item_id: UUID | None
    source_url: str | None
    title: str | None
    content_text: str
    authors: list[str]
    published_at: datetime | None
    content_sha256: str
    snapshot_metadata: dict[str, Any]
    captured_at: datetime


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, UUID)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    raise TypeError(f"unsupported immutable evidence value: {type(value).__name__}")


def _canonical_payload(value: _SnapshotPayload) -> str:
    payload = {
        "content_item_id": value.content_item_id,
        "source_url": value.source_url,
        "title": value.title,
        "content_text": value.content_text,
        "authors": value.authors,
        "published_at": value.published_at,
        "content_sha256": value.content_sha256,
        "snapshot_metadata": value.snapshot_metadata,
        "captured_at": value.captured_at,
    }
    return json.dumps(payload, default=_json_default, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _collision(evidence_key: str) -> NoReturn:
    raise EvidenceKeyCollision(f"same evidence_key has different snapshot payload: {evidence_key}")


def _from_snapshot(row: StoryEvidenceSnapshot) -> _SnapshotPayload:
    return _SnapshotPayload(
        evidence_key=row.evidence_key,
        content_item_id=row.content_item_id,
        source_url=row.source_url,
        title=row.title,
        content_text=row.content_text,
        authors=list(row.authors),
        published_at=row.published_at,
        content_sha256=row.content_sha256,
        snapshot_metadata=dict(row.snapshot_metadata),
        captured_at=row.captured_at,
    )


def _from_content_item(row: ContentItem) -> _SnapshotPayload:
    content_text = row.content_text or ""
    content_sha256 = sha256(content_text.encode("utf-8")).hexdigest()
    return _SnapshotPayload(
        evidence_key=build_evidence_key(
            content_item_id=row.id,
            source_url=row.canonical_url,
            content_sha256=content_sha256,
        ),
        content_item_id=row.id,
        source_url=row.canonical_url,
        title=row.title,
        content_text=content_text,
        authors=list(row.authors),
        published_at=row.published_at,
        content_sha256=content_sha256,
        snapshot_metadata={},
        captured_at=row.created_at,
    )


def _as_grouping_input(row: ContentItem) -> GroupingInput:
    return GroupingInput(
        content_item_id=str(row.id),
        title=row.title or "",
        canonical_url=row.canonical_url,
        published_at=row.published_at or row.sort_at,
    )


def _choose_oldest_matching_canonical(
    items: Sequence[ContentItem],
    candidates: Sequence[tuple[Story, ContentItem]],
) -> Story | None:
    inputs = [_as_grouping_input(row) for row in items]
    matching: dict[UUID, Story] = {}
    for story, candidate_item in candidates:
        candidate = _as_grouping_input(candidate_item)
        if any(decide_group(value, candidate).grouped for value in inputs):
            matching[story.id] = story
    if not matching:
        return None
    return min(matching.values(), key=lambda row: (row.created_at, row.id))


def _story_grouping_lock_statement():
    return select(func.pg_advisory_xact_lock(STORY_GROUPING_ADVISORY_LOCK_KEY))


def _manual_intake_lock_key(job_id: UUID) -> int:
    return int.from_bytes(job_id.bytes[:8], byteorder="big", signed=True)


def _manual_intake_lock_statement(job_id: UUID):
    return select(func.pg_advisory_xact_lock(_manual_intake_lock_key(job_id)))


def _candidate_identity_statement(
    items: Sequence[ContentItem],
    *,
    exact_only: bool = True,
    after: tuple[datetime, UUID, UUID] | None = None,
):
    observed_times = [row.published_at or row.sort_at for row in items]
    window_start = min(observed_times) - timedelta(hours=72)
    window_end = max(observed_times) + timedelta(hours=72)
    url_hashes = {hash_value(normalize_url(row.canonical_url)) for row in items if row.canonical_url}
    exact_url = ContentItem.canonical_url_hash.in_(url_hashes) if url_hashes else false()
    selected_columns: list[Any] = [
        Story.id.label("story_id"),
        ContentItem.id.label("content_item_id"),
        Story.created_at.label("story_created_at"),
    ]
    order_columns: list[Any] = [Story.created_at, Story.id, ContentItem.id]
    if exact_only:
        exact_priority = case((exact_url, 0), else_=1).label("exact_priority")
        selected_columns.append(exact_priority)
        order_columns.insert(0, "exact_priority")

    statement = (
        select(*selected_columns)
        .distinct()
        .join(StoryEvidenceSnapshot, StoryEvidenceSnapshot.story_id == Story.id)
        .join(ContentItem, ContentItem.id == StoryEvidenceSnapshot.content_item_id)
        .where(
            Story.status != TELEGRAM_PROVISIONAL,
            Story.superseded_by_id.is_(None),
            exact_url
            if exact_only
            else func.coalesce(ContentItem.published_at, ContentItem.sort_at).between(
                window_start,
                window_end,
            ),
        )
        .order_by(*order_columns)
        .limit(CANONICAL_CANDIDATE_LIMIT)
    )
    if after is not None:
        statement = statement.where(tuple_(Story.created_at, Story.id, ContentItem.id) > after)
    return statement


class StoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_job(self, job_id: UUID) -> Story | None:
        return await self.session.scalar(
            select(Story)
            .join(StoryEvidenceSnapshot, StoryEvidenceSnapshot.story_id == Story.id)
            .where(StoryEvidenceSnapshot.snapshot_metadata.contains({"workflow_job_id": str(job_id)}))
            .limit(1)
        )

    async def create_from_manual_evidence(
        self,
        evidence: EvidenceInput,
        job_id: UUID,
    ) -> Story:
        await self.session.execute(_manual_intake_lock_statement(job_id))
        existing = await self.get_for_job(job_id)
        if existing is not None:
            return existing
        if evidence.payload_kind not in {"manual_url_input", "manual_text_input"}:
            raise ValueError("manual evidence must identify its intake kind")

        raw_payload = RawPayload(
            run_id=None,
            source_id=None,
            payload_kind=evidence.payload_kind,
            request_url=evidence.request_url or "manual://operator",
            final_url=evidence.final_url,
            http_status=None,
            headers={},
            content_type=None,
            body_sha256=(
                sha256(evidence.raw_text.encode("utf-8")).hexdigest() if evidence.raw_text is not None else None
            ),
            raw_text=evidence.raw_text,
            parser_warnings=list(evidence.extraction_warnings),
        )
        self.session.add(raw_payload)
        await self.session.flush()

        canonical_url = evidence.source_url
        content_item = ContentItem(
            item_type="article",
            canonical_url=canonical_url,
            canonical_url_hash=(hash_value(normalize_url(canonical_url)) if canonical_url else None),
            title=evidence.title,
            title_fingerprint=fingerprint_text(evidence.title or ""),
            summary=evidence.summary,
            content_text=evidence.content_text,
            content_html_sanitized=None,
            language_code=None,
            authors=list(evidence.authors),
            published_at=evidence.published_at,
            sort_at=evidence.published_at or evidence.captured_at,
            date_source="source" if evidence.published_at else None,
            date_parse_status="parsed" if evidence.published_at else "missing",
            primary_source_id=None,
            metrics={"manual_intake": True},
            classification_metadata={
                "manual_intake": True,
                "source_label": evidence.source_label,
            },
        )
        self.session.add(content_item)
        await self.session.flush()

        provenance = {
            "manual_intake": True,
            "workflow_job_id": str(job_id),
            "source_label": evidence.source_label,
            "extraction_status": evidence.extraction_status,
            "extraction_warnings": list(evidence.extraction_warnings),
        }
        source_item = SourceItem(
            source_id=None,
            run_id=None,
            content_item_id=content_item.id,
            raw_payload_id=raw_payload.id,
            external_id_raw=str(job_id),
            external_id_norm=str(job_id),
            source_url=canonical_url,
            source_url_norm=normalize_url(canonical_url) if canonical_url else None,
            canonical_url_candidate=canonical_url,
            title_raw=evidence.title,
            summary_raw=evidence.summary,
            content_html_raw=evidence.content_html,
            content_text_raw=evidence.content_text,
            author_raw=evidence.authors[0] if evidence.authors else None,
            categories=[],
            published_raw=(evidence.published_at.isoformat() if evidence.published_at else None),
            parser_meta=provenance,
        )
        self.session.add(source_item)
        await self.session.flush()

        story = Story(
            title=evidence.title if evidence.title is not None else "Untitled story",
            status=INBOX,
            primary_language="und",
        )
        self.session.add(story)
        await self.session.flush()

        captured = capture_evidence(replace(evidence, content_item_id=content_item.id))
        self.session.add(
            StoryEvidenceSnapshot(
                story_id=story.id,
                content_item_id=content_item.id,
                evidence_key=captured.evidence_key,
                source_url=evidence.source_url,
                title=evidence.title,
                content_text=evidence.content_text,
                authors=list(evidence.authors),
                published_at=evidence.published_at,
                content_sha256=captured.content_sha256,
                snapshot_metadata=provenance,
                captured_at=evidence.captured_at,
            )
        )
        await self.session.flush()
        return story

    async def list_evidence(self, story_id: UUID) -> list[EvidenceRecord]:
        rows = list(
            await self.session.scalars(
                select(StoryEvidenceSnapshot)
                .where(StoryEvidenceSnapshot.story_id == story_id)
                .order_by(StoryEvidenceSnapshot.captured_at, StoryEvidenceSnapshot.id)
            )
        )
        return [evidence_record_from_snapshot(row) for row in rows]

    async def list_pending_content_items(
        self,
        *,
        limit: int,
        cursor: UUID | None,
    ) -> list[ContentItem]:
        has_snapshot = exists(select(1).where(StoryEvidenceSnapshot.content_item_id == ContentItem.id))
        has_active_provisional_snapshot = exists(
            select(1)
            .select_from(StoryEvidenceSnapshot)
            .join(Story, Story.id == StoryEvidenceSnapshot.story_id)
            .where(
                StoryEvidenceSnapshot.content_item_id == ContentItem.id,
                Story.status == TELEGRAM_PROVISIONAL,
                Story.superseded_by_id.is_(None),
            )
        )
        statement = select(ContentItem).where(or_(~has_snapshot, has_active_provisional_snapshot))
        if cursor is not None:
            statement = statement.where(ContentItem.id > cursor)
        return list(await self.session.scalars(statement.order_by(ContentItem.id).limit(limit).with_for_update()))

    async def _matching_active_canonical(self, items: Sequence[ContentItem]) -> Story | None:
        exact_candidate = None
        for exact_only in (True, False):
            after = None
            while True:
                identities = list(
                    (
                        await self.session.execute(
                            _candidate_identity_statement(
                                items,
                                exact_only=exact_only,
                                after=after,
                            )
                        )
                    ).all()
                )
                if not identities:
                    break
                canonical = await self._lock_matching_candidate(items, identities)
                if canonical is not None:
                    if exact_only:
                        exact_candidate = canonical
                        break
                    if exact_candidate is None:
                        return canonical
                    return min(
                        (exact_candidate, canonical),
                        key=lambda row: (row.created_at, row.id),
                    )
                if len(identities) < CANONICAL_CANDIDATE_LIMIT:
                    break
                last = identities[-1]
                after = (last.story_created_at, last.story_id, last.content_item_id)
        return exact_candidate

    async def _lock_matching_candidate(
        self,
        items: Sequence[ContentItem],
        identities: Sequence[Any],
    ) -> Story | None:
        content_item_ids = sorted({row.content_item_id for row in identities})
        observed_items = list(
            await self.session.scalars(
                select(ContentItem).where(ContentItem.id.in_(content_item_ids)).order_by(ContentItem.id)
            )
        )
        observed_by_id = {row.id: row for row in observed_items}
        input_values = [_as_grouping_input(row) for row in items]
        matching_identities = [
            row
            for row in identities
            if row.content_item_id in observed_by_id
            and any(
                decide_group(value, _as_grouping_input(observed_by_id[row.content_item_id])).grouped
                for value in input_values
            )
        ]
        if not matching_identities:
            return None

        story_ids = sorted({row.story_id for row in matching_identities})
        matching_item_ids = sorted({row.content_item_id for row in matching_identities})
        stories = list(
            await self.session.scalars(
                select(Story)
                .where(
                    Story.id.in_(story_ids),
                    Story.status != TELEGRAM_PROVISIONAL,
                    Story.superseded_by_id.is_(None),
                )
                .order_by(Story.id)
                .with_for_update()
            )
        )
        locked_items = list(
            await self.session.scalars(
                select(ContentItem)
                .where(ContentItem.id.in_(matching_item_ids))
                .order_by(ContentItem.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        stories_by_id = {row.id: row for row in stories}
        items_by_id = {row.id: row for row in locked_items}
        candidates = [
            (stories_by_id[row.story_id], items_by_id[row.content_item_id])
            for row in matching_identities
            if row.story_id in stories_by_id and row.content_item_id in items_by_id
        ]
        return _choose_oldest_matching_canonical(items, candidates)

    async def group_content_items(self, content_item_ids: Sequence[UUID]) -> StoryGroupingResult:
        await self.session.execute(_story_grouping_lock_statement())
        requested_ids = tuple(dict.fromkeys(content_item_ids))
        if not requested_ids:
            raise ValueError("content_item_ids must not be empty")
        repeated_ids = tuple(
            content_item_id
            for index, content_item_id in enumerate(content_item_ids)
            if content_item_id in content_item_ids[:index]
        )

        items = list(
            await self.session.scalars(
                select(ContentItem)
                .where(ContentItem.id.in_(requested_ids))
                .order_by(ContentItem.sort_at, ContentItem.id)
                .with_for_update()
            )
        )
        if len(items) != len(requested_ids):
            found = {row.id for row in items}
            return StoryGroupingResult(
                story=None,
                items=tuple(
                    GroupedItemResult(
                        content_item_id=value,
                        disposition="skipped" if value in found else "conflicted",
                        reason="batch_contains_missing_item" if value in found else "content_item_not_found",
                    )
                    for value in requested_ids
                ),
                created_evidence_snapshot_count=0,
            )

        matching_snapshots = list(
            await self.session.scalars(
                select(StoryEvidenceSnapshot)
                .where(StoryEvidenceSnapshot.content_item_id.in_(requested_ids))
                .with_for_update()
            )
        )
        matching_story_ids = {row.story_id for row in matching_snapshots}
        stories: list[Story] = []
        if matching_story_ids:
            stories = list(
                await self.session.scalars(
                    select(Story)
                    .where(
                        or_(
                            Story.id.in_(matching_story_ids),
                            Story.superseded_by_id.in_(matching_story_ids),
                        )
                    )
                    .with_for_update()
                )
            )
            superseding_ids = {row.superseded_by_id for row in stories if row.superseded_by_id is not None}
            missing_superseding_ids = superseding_ids - {row.id for row in stories}
            if missing_superseding_ids:
                stories.extend(
                    await self.session.scalars(
                        select(Story).where(Story.id.in_(missing_superseding_ids)).with_for_update()
                    )
                )

        story_ids = {row.id for row in stories}
        all_story_snapshots: list[StoryEvidenceSnapshot] = []
        if story_ids:
            all_story_snapshots = list(
                await self.session.scalars(
                    select(StoryEvidenceSnapshot).where(StoryEvidenceSnapshot.story_id.in_(story_ids)).with_for_update()
                )
            )
            snapshot_ids = {row.id for row in all_story_snapshots}
            if snapshot_ids:
                list(
                    await self.session.scalars(
                        select(StoryEvidenceLink)
                        .where(StoryEvidenceLink.evidence_snapshot_id.in_(snapshot_ids))
                        .with_for_update()
                    )
                )

        active_canonicals = sorted(
            (row for row in stories if row.status != TELEGRAM_PROVISIONAL and row.superseded_by_id is None),
            key=lambda row: (row.created_at, row.id),
        )
        if len(active_canonicals) > 1:
            return StoryGroupingResult(
                story=None,
                items=tuple(
                    GroupedItemResult(value, "conflicted", "multiple_active_stories") for value in requested_ids
                ),
                created_evidence_snapshot_count=0,
            )
        canonical = active_canonicals[0] if active_canonicals else None
        if canonical is None:
            canonical = await self._matching_active_canonical(items)
            if canonical is not None and canonical.id not in story_ids:
                stories.append(canonical)
                story_ids.add(canonical.id)
                canonical_snapshots = list(
                    await self.session.scalars(
                        select(StoryEvidenceSnapshot)
                        .where(StoryEvidenceSnapshot.story_id == canonical.id)
                        .with_for_update()
                    )
                )
                all_story_snapshots.extend(canonical_snapshots)
                canonical_snapshot_ids = {row.id for row in canonical_snapshots}
                if canonical_snapshot_ids:
                    list(
                        await self.session.scalars(
                            select(StoryEvidenceLink)
                            .where(StoryEvidenceLink.evidence_snapshot_id.in_(canonical_snapshot_ids))
                            .with_for_update()
                        )
                    )
        provisionals = [row for row in stories if row.status == TELEGRAM_PROVISIONAL and row.superseded_by_id is None]
        provisional_ids = {row.id for row in provisionals}
        provisional_snapshots = [row for row in all_story_snapshots if row.story_id in provisional_ids]
        assigned_item_ids = {row.content_item_id for row in matching_snapshots if row.content_item_id is not None}

        incoming = [_from_snapshot(row) for row in provisional_snapshots]
        incoming.extend(_from_content_item(row) for row in items if row.id not in assigned_item_ids)

        existing_by_key: dict[str, _SnapshotPayload] = {}
        if canonical is not None:
            for row in all_story_snapshots:
                if row.story_id != canonical.id:
                    continue
                value = _from_snapshot(row)
                prior = existing_by_key.get(value.evidence_key)
                if prior is not None and _canonical_payload(prior) != _canonical_payload(value):
                    _collision(value.evidence_key)
                existing_by_key[value.evidence_key] = value

        unique_incoming: dict[str, _SnapshotPayload] = {}
        for value in incoming:
            prior = unique_incoming.get(value.evidence_key) or existing_by_key.get(value.evidence_key)
            if prior is not None:
                if _canonical_payload(prior) != _canonical_payload(value):
                    _collision(value.evidence_key)
                continue
            unique_incoming[value.evidence_key] = value

        if canonical is None:
            title = next((row.title for row in items if row.title), None)
            if title is None and provisionals:
                title = sorted(provisionals, key=lambda row: (row.created_at, row.id))[0].title
            canonical = Story(
                title=title or "Untitled story",
                status=INBOX,
                primary_language=next((row.language_code for row in items if row.language_code), "und"),
            )
            self.session.add(canonical)
            await self.session.flush()

        for value in unique_incoming.values():
            self.session.add(
                StoryEvidenceSnapshot(
                    story_id=canonical.id,
                    content_item_id=value.content_item_id,
                    evidence_key=value.evidence_key,
                    source_url=value.source_url,
                    title=value.title,
                    content_text=value.content_text,
                    authors=list(value.authors),
                    published_at=value.published_at,
                    content_sha256=value.content_sha256,
                    snapshot_metadata=dict(value.snapshot_metadata),
                    captured_at=value.captured_at,
                )
            )
        await self.session.flush()

        for provisional in provisionals:
            provisional.superseded_by_id = canonical.id
        await self.session.flush()
        provisional_item_ids = {row.content_item_id for row in provisional_snapshots if row.content_item_id is not None}
        item_results = [
            GroupedItemResult(
                content_item_id=value,
                disposition=(
                    "duplicate" if value in assigned_item_ids and value not in provisional_item_ids else "grouped"
                ),
                reason=(
                    "already_grouped"
                    if value in assigned_item_ids and value not in provisional_item_ids
                    else "provisional_story_merged"
                    if value in provisional_item_ids
                    else "evidence_attached"
                ),
            )
            for value in requested_ids
        ]
        item_results.extend(GroupedItemResult(value, "skipped", "repeated_request") for value in repeated_ids)
        return StoryGroupingResult(
            story=canonical,
            items=tuple(item_results),
            created_evidence_snapshot_count=len(unique_incoming),
        )
