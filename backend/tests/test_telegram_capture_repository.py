from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.contracts import (
    MaterializedTelegramMedia,
    TelegramEnvelope,
    TelegramMediaReference,
)
from app.automations.telegram.media import TelegramMediaStore
from app.automations.telegram.repository import TelegramCaptureRepository
from app.db.models import ContentItem, IngestRun, MediaAsset, RawPayload, Source, SourceItem
from app.jobs.repository import EnqueueJobResult
from app.stories.models import StoryRevision

ROUTE_ID = UUID("00000000-0000-0000-0000-000000000301")
EXISTING_DISPATCH_ID = UUID("00000000-0000-0000-0000-000000000302")
SOURCE_ID = UUID("00000000-0000-0000-0000-000000000303")


async def test_capture_records_evidence_and_process_job_before_cursor_advance(tmp_path):
    events: list[str] = []
    capture, session, jobs, ingestion, route = _build_capture_repository(tmp_path, events)
    staged = _staged_album(tmp_path)

    dispatch = await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=_telegram_source(),
        cursor=route,
        envelope=_telegram_album(message_ids=(101, 102, 103)),
        materialized_media=staged,
        dispatch_kind="live",
        dry_run_job_id=None,
    )

    assert dispatch.source_message_ids == [101, 102, 103]
    assert events.index("route_locked") < events.index("source_item_flushed")
    assert events.index("source_item_flushed") < events.index("dispatch_flushed")
    assert events.index("dispatch_flushed") < events.index("process_job_enqueued")
    assert events.index("process_job_enqueued") < events.index("cursor_advanced:103")
    assert jobs.enqueued[0].job_type == "telegram.route.process"
    assert jobs.enqueued[0].idempotency_key == f"telegram-process:{ROUTE_ID}:album:900"
    assert ingestion.captured_item.external_id_norm == "telegram:-100900:103"
    assert route.cursor_state["last_message_id"] == 103
    assert session.story.status == "telegram_provisional"
    assert session.revision.revision_number == 1
    assert session.revision.created_by == "telegram_capture"
    assert session.revision.citations == [_expected_snapshot_citation(session.snapshot)]
    assert session.evidence_link.evidence_snapshot_id == session.snapshot.id
    assert session.evidence_link.story_revision_id == session.revision.id
    assert session.evidence_link.claim_key == "telegram.source"
    assert all(path.exists() for path in (item.path for item in staged))

    capture.cleanup_staged_media(staged)

    assert all(not path.exists() for path in (item.path for item in staged))


async def test_media_only_capture_keeps_snapshot_without_invalid_empty_text_citation(tmp_path):
    capture, session, jobs, _, route = _build_capture_repository(tmp_path, [])

    dispatch = await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=_telegram_source(),
        cursor=route,
        envelope=_telegram_album(message_ids=(101, 102, 103), text=""),
        materialized_media=_staged_album(tmp_path),
        dispatch_kind="live",
        dry_run_job_id=None,
    )

    assert session.snapshot.content_text == ""
    assert session.revision.citations == []
    assert session.evidence_link.evidence_snapshot_id == session.snapshot.id
    assert dispatch.story_revision_id == session.revision.id
    assert jobs.enqueued[0].job_type == "telegram.route.process"


async def test_duplicate_route_source_returns_existing_before_mutation_or_cursor_regression(tmp_path):
    events: list[str] = []
    existing = AutomationDispatch(
        id=EXISTING_DISPATCH_ID,
        route_id=ROUTE_ID,
        source_item_id=uuid4(),
        story_revision_id=uuid4(),
        source_key="album:900",
        source_fingerprint="existing",
        source_message_ids=[101, 102, 103],
        dispatch_kind="backfill",
        status="captured",
    )
    capture, _, jobs, ingestion, route = _build_capture_repository(
        tmp_path, events, existing_dispatch=existing
    )
    original_cursor = dict(route.cursor_state)

    replay = await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=_telegram_source(),
        cursor=route,
        envelope=_telegram_album(message_ids=(101, 102, 103)),
        materialized_media=_staged_album(tmp_path),
        dispatch_kind="backfill",
        dry_run_job_id=None,
    )

    assert replay.id == EXISTING_DISPATCH_ID
    assert events == ["route_locked", "dispatch_replay_checked"]
    assert jobs.enqueued == []
    assert ingestion.captured_item is None
    assert route.cursor_state == original_cursor


async def test_source_edit_reuses_story_and_creates_linked_child_revision(tmp_path):
    events: list[str] = []
    story_id = uuid4()
    parent = StoryRevision(
        id=uuid4(),
        story_id=story_id,
        parent_revision_id=None,
        revision_number=1,
        narrative="Original",
        created_by="telegram_capture",
    )
    original = AutomationDispatch(
        id=uuid4(),
        route_id=ROUTE_ID,
        source_item_id=uuid4(),
        story_revision_id=parent.id,
        source_key="album:900",
        source_fingerprint="original",
        source_message_ids=[101, 102, 103],
        dispatch_kind="live",
        status="captured",
    )
    capture, session, jobs, ingestion, route = _build_capture_repository(
        tmp_path,
        events,
        dispatch_results=[None, original],
        revision_results=[parent],
    )
    original_cursor = dict(route.cursor_state)
    edited_envelope = _telegram_album(message_ids=(101, 102, 103), text="Edited album text")

    dispatch = await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=_telegram_source(),
        cursor=route,
        envelope=edited_envelope,
        materialized_media=_staged_album(tmp_path),
        dispatch_kind="source_edit",
        dry_run_job_id=None,
    )

    assert session.story is None
    assert session.snapshot.story_id == story_id
    assert session.revision.story_id == story_id
    assert session.revision.parent_revision_id == parent.id
    assert session.revision.revision_number == 2
    assert session.revision.created_by == "telegram_source_edit"
    assert session.revision.citations == [_expected_snapshot_citation(session.snapshot)]
    assert session.evidence_link.evidence_snapshot_id == session.snapshot.id
    assert dispatch.source_key.startswith("album:900:edit:")
    assert dispatch.dispatch_kind == "source_edit"
    assert ingestion.captured_item.external_id_norm.startswith("telegram:-100900:103:edit:")
    assert jobs.enqueued[0].idempotency_key == f"telegram-process:{ROUTE_ID}:{dispatch.source_key}"
    assert route.cursor_state["last_message_id"] == original_cursor["last_message_id"]
    assert route.cursor_state["recent_fingerprints"]["103"] == dispatch.source_fingerprint


def _expected_snapshot_citation(snapshot):
    return {
        "evidence_key": snapshot.evidence_key,
        "evidence_snapshot_id": str(snapshot.id),
        "source_url": snapshot.source_url,
        "locator": f"chars:0-{len(snapshot.content_text)}",
        "excerpt_sha256": snapshot.content_sha256,
    }


async def test_same_text_entity_only_edit_uses_distinct_content_identity_and_evidence_key(tmp_path):
    events: list[str] = []
    story_id = uuid4()
    original_content_item_id = uuid4()
    same_text = "Unchanged source text"
    original_hash = sha256(same_text.encode("utf-8")).hexdigest()
    original_evidence_key = f"content-item:{original_content_item_id}:{original_hash}"
    parent = StoryRevision(
        id=uuid4(),
        story_id=story_id,
        parent_revision_id=None,
        revision_number=1,
        narrative=same_text,
        created_by="telegram_capture",
    )
    original = AutomationDispatch(
        id=uuid4(),
        route_id=ROUTE_ID,
        source_item_id=uuid4(),
        story_revision_id=parent.id,
        source_key="album:900",
        source_fingerprint="original-fingerprint",
        source_message_ids=[101, 102, 103],
        dispatch_kind="live",
        status="captured",
    )
    capture, session, _, ingestion, route = _build_capture_repository(
        tmp_path,
        events,
        dispatch_results=[None, original],
        revision_results=[parent],
    )
    edited = _telegram_album(message_ids=(101, 102, 103), text=same_text)
    edited = replace(
        edited,
        entities=({"type": "italic", "offset": 0, "length": 9},),
    )

    await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=_telegram_source(),
        cursor=route,
        envelope=edited,
        materialized_media=_staged_album(tmp_path),
        dispatch_kind="source_edit",
        dry_run_job_id=None,
    )

    assert [identity["identity_type"] for identity in ingestion.content_identities] == ["telegram_post"]
    assert ingestion.content_identities[0]["identity_value"].startswith("telegram:-100900:103:edit:")
    assert session.snapshot.content_text == same_text
    assert session.snapshot.content_sha256 == original_hash
    assert session.snapshot.evidence_key != original_evidence_key
    assert session.snapshot.evidence_key.startswith(f"content-item:{ingestion.content_item.id}:")


async def test_replayed_source_edit_fingerprint_returns_existing_without_new_revision(tmp_path):
    existing = AutomationDispatch(
        id=EXISTING_DISPATCH_ID,
        route_id=ROUTE_ID,
        source_item_id=uuid4(),
        story_revision_id=uuid4(),
        source_key="album:900:edit:existing-fingerprint",
        source_fingerprint="existing-fingerprint",
        source_message_ids=[101, 102, 103],
        dispatch_kind="source_edit",
        status="captured",
    )
    capture, session, jobs, ingestion, route = _build_capture_repository(
        tmp_path, [], dispatch_results=[existing]
    )

    replay = await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=_telegram_source(),
        cursor=route,
        envelope=_telegram_album(message_ids=(101, 102, 103)),
        materialized_media=_staged_album(tmp_path),
        dispatch_kind="source_edit",
        dry_run_job_id=None,
    )

    assert replay is existing
    assert session.revision is None
    assert jobs.enqueued == []
    assert ingestion.captured_item is None


@pytest.mark.parametrize("dispatch_kind", ["backfill", "dry_run"])
async def test_backfill_and_dry_run_preserve_live_cursor_state(tmp_path, dispatch_kind):
    capture, _, jobs, ingestion, route = _build_capture_repository(tmp_path, [])
    original_state = route.cursor_state
    original_value = {
        **original_state,
        "recent_fingerprints": dict(original_state["recent_fingerprints"]),
    }
    dry_run_job_id = uuid4() if dispatch_kind == "dry_run" else None

    dispatch = await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=_telegram_source(),
        cursor=route,
        envelope=_telegram_album(message_ids=(80,)),
        materialized_media=(),
        dispatch_kind=dispatch_kind,
        dry_run_job_id=dry_run_job_id,
    )

    assert route.cursor_state is original_state
    assert route.cursor_state == original_value
    if dispatch_kind == "dry_run":
        assert dispatch.source_key == f"dry:{dry_run_job_id}:album:900"
    else:
        assert dispatch.source_key == "album:900"
    assert ingestion.captured_item.external_id_norm == "telegram:-100900:80"
    assert jobs.enqueued[0].idempotency_key == f"telegram-process:{ROUTE_ID}:{dispatch.source_key}"


async def test_live_cursor_never_regresses_and_retains_highest_50_numeric_fingerprints(tmp_path):
    capture, _, _, _, route = _build_capture_repository(tmp_path, [])
    original_state = route.cursor_state
    route.cursor_state = {
        **original_state,
        "last_message_id": 100,
        "recent_fingerprints": {str(value): f"fingerprint-{value}" for value in range(9, 59)},
    }
    replaced_state = route.cursor_state

    await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=_telegram_source(),
        cursor=route,
        envelope=_telegram_album(message_ids=(8,)),
        materialized_media=(),
        dispatch_kind="live",
        dry_run_job_id=None,
    )

    assert route.cursor_state is not replaced_state
    assert route.cursor_state["last_message_id"] == 100
    assert list(route.cursor_state["recent_fingerprints"]) == [str(value) for value in range(58, 8, -1)]
    for key in ("activation_requested_at", "activation_boundary_at", "activation_message_id", "initialized_at"):
        assert route.cursor_state[key] == original_state[key]


async def test_job_failure_preserves_staging_and_cursor_for_transaction_rollback(tmp_path):
    events: list[str] = []
    capture, session, jobs, _, route = _build_capture_repository(tmp_path, events)
    jobs.error = RuntimeError("database job insert failed")
    staged = _staged_album(tmp_path)
    original_cursor = dict(route.cursor_state)

    with pytest.raises(RuntimeError, match="database job insert failed"):
        await capture.capture_and_enqueue(
            route_id=ROUTE_ID,
            source=_telegram_source(),
            cursor=route,
            envelope=_telegram_album(message_ids=(101, 102, 103)),
            materialized_media=staged,
            dispatch_kind="live",
            dry_run_job_id=None,
        )

    assert all(item.path.exists() for item in staged)
    assert route.cursor_state == original_cursor
    assert not any(type(value).__name__ == "WorkflowEvent" for value in session.added)


async def test_route_source_mismatch_fails_before_all_capture_side_effects(tmp_path):
    events: list[str] = []
    capture, session, jobs, ingestion, route = _build_capture_repository(tmp_path, events)
    staged = _staged_album(tmp_path)
    original_cursor = dict(route.cursor_state)
    mismatched_source = _telegram_source()
    mismatched_source.id = uuid4()

    with pytest.raises(ValueError, match="source does not belong"):
        await capture.capture_and_enqueue(
            route_id=ROUTE_ID,
            source=mismatched_source,
            cursor=route,
            envelope=_telegram_album(message_ids=(101, 102, 103)),
            materialized_media=staged,
            dispatch_kind="live",
            dry_run_job_id=None,
        )

    assert events == ["route_locked"]
    assert ingestion.captured_item is None
    assert jobs.enqueued == []
    assert session.added == []
    assert route.cursor_state == original_cursor
    assert all(item.path.exists() for item in staged)
    assert not (tmp_path / "stored").exists()


async def test_capture_event_and_mtproto_media_identity_exclude_remote_material(tmp_path):
    capture, session, _, ingestion, route = _build_capture_repository(tmp_path, [])
    staged = _staged_album(tmp_path)

    await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=_telegram_source(),
        cursor=route,
        envelope=_telegram_album(message_ids=(101, 102, 103)),
        materialized_media=staged,
        dispatch_kind="live",
        dry_run_job_id=None,
    )

    candidates = ingestion.captured_item.media_candidates
    assert [candidate.fetch_status for candidate in candidates] == ["downloaded"] * 3
    assert [candidate.byte_length for candidate in candidates] == [9, 9, 9]
    assert all(candidate.original_url.startswith("telegram-media:") for candidate in candidates)
    assert all("opaque-remote" not in candidate.original_url for candidate in candidates)
    assert all(candidate.source_field == "telegram_capture" for candidate in candidates)
    event = next(value for value in session.added if type(value).__name__ == "WorkflowEvent")
    assert event.event_data["media_count"] == 3
    assert "photo-101" not in str(event.event_data)
    assert "opaque-remote" not in str(event.event_data)
    assert "api_hash" not in str(event.event_data).lower()


def _telegram_source() -> Source:
    return Source(
        id=SOURCE_ID,
        platform="telegram_public",
        name="Telegram source",
        telegram_username="one_channel",
        source_group="telegram",
        language_hint="fa",
    )


def _route() -> AutomationRoute:
    return AutomationRoute(
        id=ROUTE_ID,
        name="route",
        source_id=SOURCE_ID,
        destination_id=uuid4(),
        brand_profile_id=uuid4(),
        prompt_template_version_id=uuid4(),
        ai_provider_profile_id=uuid4(),
        access_mode="mtproto_user",
        cursor_state={
            "last_message_id": 100,
            "recent_fingerprints": {},
            "activation_requested_at": "2026-07-12T00:00:00+00:00",
            "activation_boundary_at": "2026-07-12T00:01:00+00:00",
            "activation_message_id": 100,
            "initialized_at": "2026-07-12T00:02:00+00:00",
        },
    )


def _telegram_album(*, message_ids: tuple[int, ...], text: str = "Album text") -> TelegramEnvelope:
    references = tuple(
        TelegramMediaReference(
            key=f"one_channel:{message_id}:photo",
            position=position,
            kind="photo",
            source_url=None,
            remote_ref=f"opaque-remote-{message_id}",
            file_name=f"{message_id}.jpg",
            mime_type="image/jpeg",
        )
        for position, message_id in enumerate(message_ids)
    )
    return TelegramEnvelope(
        source_key="album:900",
        peer_id="-100900",
        channel_ref="one_channel",
        anchor_message_id=max(message_ids),
        message_ids=message_ids,
        grouped_id="900",
        text=text,
        html=None,
        entities=({"type": "bold", "offset": 0, "length": 5},),
        published_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
        edited_at=None,
        source_url=None,
        media=references,
    )


def _staged_album(tmp_path: Path) -> tuple[MaterializedTelegramMedia, ...]:
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    result = []
    for position, message_id in enumerate((101, 102, 103)):
        reference = TelegramMediaReference(
            key=f"one_channel:{message_id}:photo",
            position=position,
            kind="photo",
            source_url=None,
            remote_ref=f"opaque-remote-{message_id}",
            file_name=f"{message_id}.jpg",
            mime_type="image/jpeg",
        )
        path = staging / f"{message_id}.jpg"
        content = f"photo-{message_id}".encode()
        path.write_bytes(content)
        result.append(
            MaterializedTelegramMedia(
                reference=reference,
                path=path,
                byte_length=len(content),
                checksum_sha256="adapter-checksum",
                mime_type="image/jpeg",
            )
        )
    return tuple(result)


def _build_capture_repository(
    tmp_path,
    events,
    *,
    existing_dispatch=None,
    dispatch_results=None,
    revision_results=None,
):
    route = _route()
    if dispatch_results is None:
        dispatch_results = [existing_dispatch]
    session = RecordingSession(
        events,
        route=route,
        dispatch_results=dispatch_results,
        revision_results=revision_results or [],
    )
    ingestion = RecordingIngestionRepository(events, session)
    jobs = RecordingJobRepository(events)
    capture = TelegramCaptureRepository(
        session,
        media_store=TelegramMediaStore(tmp_path / "stored", max_photo_bytes=100, max_file_bytes=100),
        ingestion_repository=ingestion,
        job_repository=jobs,
    )
    return capture, session, jobs, ingestion, route


class RecordingSession:
    def __init__(self, events, *, route, dispatch_results, revision_results):
        self.events = events
        self.route = route
        self.dispatch_results = list(dispatch_results)
        self.revision_results = list(revision_results)
        self.added = []
        self.story = None
        self.snapshot = None
        self.revision = None
        self.evidence_link = None
        self._dispatch_flushed = False

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is AutomationRoute:
            self.events.append("route_locked")
            return self.route
        if entity is AutomationDispatch:
            self.events.append("dispatch_replay_checked")
            return self.dispatch_results.pop(0) if self.dispatch_results else None
        if entity is StoryRevision:
            return self.revision_results.pop(0) if self.revision_results else None
        return None

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        self.added.append(value)
        name = type(value).__name__
        if name == "Story":
            self.story = value
        elif name == "StoryEvidenceSnapshot":
            self.snapshot = value
        elif name == "StoryRevision":
            self.revision = value
        elif name == "StoryEvidenceLink":
            self.evidence_link = value

    async def flush(self):
        if any(isinstance(value, AutomationDispatch) for value in self.added) and not self._dispatch_flushed:
            self.events.append("dispatch_flushed")
            self._dispatch_flushed = True
        elif (
            self._dispatch_flushed
            and self.route.cursor_state.get("last_message_id") == 103
            and "process_job_enqueued" in self.events
            and "cursor_advanced:103" not in self.events
        ):
            self.events.append("cursor_advanced:103")


class RecordingIngestionRepository:
    def __init__(self, events, session):
        self.events = events
        self.session = session
        self.captured_item = None
        self.content_identities = None
        self.content_item = None

    async def create_run(self, trigger, parser_version):
        return IngestRun(id=uuid4(), trigger=trigger, parser_version=parser_version, status="running")

    async def save_raw_payload(self, **kwargs):
        return RawPayload(id=uuid4(), **kwargs)

    async def upsert_source_item(self, run_id, source_id, raw_payload_id, parsed_item):
        self.captured_item = parsed_item
        item = SourceItem(
            id=uuid4(), source_id=source_id, run_id=run_id, raw_payload_id=raw_payload_id
        )
        self.events.append("source_item_flushed")
        return item

    async def upsert_content_item(self, source, source_item, parsed_item, identities):
        self.content_identities = identities
        item = ContentItem(id=uuid4(), item_type="telegram_post", sort_at=parsed_item.published_at)
        self.content_item = item
        source_item.content_item_id = item.id
        return item

    async def attach_identities(self, **kwargs):
        return None

    async def upsert_media_assets(self, parsed_item):
        return [
            MediaAsset(
                id=uuid4(),
                original_url=candidate.original_url,
                normalized_url=candidate.normalized_url,
                url_hash=str(index),
                kind=candidate.kind,
                source_field=candidate.source_field,
                storage_path=candidate.storage_path,
                checksum_sha256=candidate.checksum_sha256,
                byte_length=candidate.byte_length,
                fetch_status=candidate.fetch_status,
            )
            for index, candidate in enumerate(parsed_item.media_candidates)
        ]

    async def attach_item_media(self, content_item_id, media_assets, parsed_item):
        return None

    async def finish_run(self, run_id, status, stats, error=None):
        return None


class RecordingJobRepository:
    def __init__(self, events):
        self.events = events
        self.enqueued = []
        self.error = None

    async def enqueue_job(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.enqueued.append(SimpleNamespace(**kwargs))
        self.events.append("process_job_enqueued")
        return EnqueueJobResult(job=SimpleNamespace(id=uuid4()), created=True)
