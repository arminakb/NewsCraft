from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.db.models import ContentItem, MediaAsset, RawPayload, SourceItem
from app.generation.models import (
    BrandProfile,
    ContentPack,
    GenerationAttempt,
    GenerationRun,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.types import JobStatus
from app.publishing.models import (
    Destination,
    Publication,
    PublishAttempt,
    PublishJob,
    PublishOperationReceipt,
)
from app.research.models import ResearchAttempt, ResearchRun
from app.retention import filesystem as retention_filesystem
from app.retention.models import RetentionRun
from app.retention.service import (
    RETENTION_CONFIRMATION,
    RetentionConfirmationError,
    RetentionConflict,
    RetentionPolicyInput,
    RetentionService,
)
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision

NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)


async def _seed_all_categories(db_session, media_root: Path):
    story = Story(title="Retention fixture", created_at=NOW - timedelta(days=120))
    db_session.add(story)
    await db_session.flush()
    research_run = ResearchRun(
        story_id=story.id,
        requested_mode="standard",
        status="succeeded",
        created_at=NOW - timedelta(days=100),
        started_at=NOW - timedelta(days=100),
        finished_at=NOW - timedelta(days=99),
    )
    db_session.add(research_run)
    await db_session.flush()
    attempt = ResearchAttempt(
        research_run_id=research_run.id,
        attempt_number=1,
        queries=["sensitive query"],
        status="succeeded",
        usage={"tokens": 11},
        started_at=NOW - timedelta(days=100),
        finished_at=NOW - timedelta(days=99),
    )
    raw = RawPayload(
        payload_kind="feed",
        request_url="https://secret.example/feed",
        final_url="https://secret.example/final",
        headers={"authorization": "secret"},
        content_type="application/json",
        body_sha256="a" * 64,
        raw_text="sensitive payload",
        parser_warnings=["warning"],
        captured_at=NOW - timedelta(days=31),
    )
    completed = WorkflowJob(
        job_type="story.group_pending",
        status="succeeded",
        payload={"secret": "request"},
        result={"secret": "response"},
        idempotency_key=f"completed:{uuid4()}",
        origin="manual",
        finished_at=NOW - timedelta(days=91),
        created_at=NOW - timedelta(days=92),
    )
    failed = WorkflowJob(
        job_type="story.group_pending",
        status="failed",
        payload={"must": "remain"},
        result={"must": "remain"},
        idempotency_key=f"failed:{uuid4()}",
        origin="manual",
        finished_at=NOW - timedelta(days=91),
        created_at=NOW - timedelta(days=92),
    )
    content_pack_id = uuid4()
    revision_id = uuid4()
    platform_variant_id = uuid4()
    story_revision_id = uuid4()
    export = WorkflowJob(
        job_type="build_export",
        status="succeeded",
        payload={
            "content_pack_id": str(content_pack_id),
            "revision_ids": [str(revision_id)],
            "revision_hashes": ["d" * 64],
            "platforms": ["telegram"],
            "platform_variant_ids": [str(platform_variant_id)],
            "formats": ["json"],
            "include_media": False,
        },
        result={},
        idempotency_key=f"export:{uuid4()}",
        origin="manual",
        finished_at=NOW - timedelta(days=15),
        created_at=NOW - timedelta(days=16),
    )
    db_session.add_all([attempt, raw, completed, failed, export])
    await db_session.flush()
    manifest = {
        "schema_version": "newscraft-export-v1",
        "content_pack_id": str(content_pack_id),
        "story_revision_id": str(story_revision_id),
        "created_at": (NOW - timedelta(days=16)).isoformat().replace("+00:00", "Z"),
        "variants": [
            {
                "platform": "telegram",
                "platform_variant_id": str(platform_variant_id),
                "revision_id": str(revision_id),
                "content_hash": "d" * 64,
                "approval_state": "approved",
                "evidence_urls": [],
            }
        ],
        "files": [
            {
                "file_name": f"telegram/{revision_id}/post.json",
                "sha256": "f" * 64,
                "byte_length": 2,
                "kind": "json",
                "platform": "telegram",
                "revision_id": str(revision_id),
                "media_asset_id": None,
            }
        ],
    }
    manifest_sha256 = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    export.result = {
        "export_id": str(export.id),
        "content_pack_id": str(content_pack_id),
        "state": "complete",
        "manifest_file": "manifest.json",
        "manifest_sha256": manifest_sha256,
        "archive_file": None,
        "archive_sha256": None,
        "manifest": manifest,
    }
    media_file = media_root / "aa" / "asset.bin"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"retained media")
    media = MediaAsset(
        original_url="https://example.test/asset.bin",
        normalized_url="https://example.test/asset.bin",
        url_hash="b" * 64,
        kind="image",
        byte_length=media_file.stat().st_size,
        source_field="fixture",
        checksum_sha256="c" * 64,
        storage_path=str(media_file),
        fetch_status="downloaded",
        raw_metadata={"source": "fixture"},
        created_at=NOW - timedelta(days=31),
        updated_at=NOW - timedelta(days=31),
    )
    db_session.add(media)
    await db_session.flush()
    export_dir = media_root.parent / "exports" / str(export.id)
    export_dir.mkdir(parents=True)
    (export_dir / "manifest.json").write_text("{}", encoding="utf-8")
    return {
        "attempt": attempt,
        "raw": raw,
        "completed": completed,
        "failed": failed,
        "export": export,
        "media": media,
        "media_file": media_file,
        "export_dir": export_dir,
    }


@pytest.mark.asyncio
async def test_preview_persists_sorted_server_snapshot_and_enqueue_is_exact_and_idempotent(
    db_session,
    tmp_path,
):
    rows = await _seed_all_categories(db_session, tmp_path / "media")
    service = RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path / "media",
    )

    preview = await service.preview()

    assert [candidate.category for candidate in preview.candidates] == [
        "attempt_metadata",
        "completed_job",
        "export_artifact",
        "raw_payload",
        "unreferenced_media",
    ]
    assert [candidate.record_type for candidate in preview.candidates] == [
        "research_attempt",
        "workflow_job",
        "workflow_job",
        "raw_payload",
        "media_asset",
    ]
    assert preview.counts["completed_job"].count == 1
    assert rows["failed"].id not in {candidate.record_id for candidate in preview.candidates}
    persisted = await db_session.get(RetentionRun, preview.run_id)
    assert persisted is not None
    assert persisted.candidate_snapshot == [candidate.model_dump(mode="json") for candidate in preview.candidates]
    assert persisted.previewed_at == NOW
    assert persisted.preview_expires_at == NOW + timedelta(minutes=30)

    with pytest.raises(RetentionConfirmationError):
        await service.enqueue(preview_token=preview.preview_token, confirmation="delete")
    with pytest.raises(RetentionConflict, match="preview token does not match"):
        await service.enqueue(preview_token="f" * 64, confirmation=RETENTION_CONFIRMATION)

    first = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    second = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    assert first.created is True
    assert second.created is False
    assert first.job.id == second.job.id
    assert first.job.pause_sensitive is True
    assert first.job.idempotency_key == f"retention:{preview.preview_token}"
    assert set(first.job.payload) == {"run_id", "preview_token"}
    first.job.status = "cancelled"
    first.job.finished_at = NOW
    first.run.status = "failed"
    first.run.finished_at = NOW
    first.run.error_snapshot = [{"phase": "workflow", "code": "retention_job_cancelled", "message": "cancelled"}]
    await db_session.flush()
    revived = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    assert revived.created is False
    assert revived.job.id == first.job.id
    assert revived.job.status == "queued"
    assert revived.run.status == "queued"
    assert revived.run.finished_at is None
    assert revived.run.error_snapshot == []
    revived.job.status = "cancelled"
    revived.job.finished_at = NOW
    revived.run.status = "partial"
    revived.run.started_at = NOW - timedelta(minutes=2)
    revived.run.finished_at = NOW - timedelta(minutes=1)
    cleanup_snapshot = [
        {
            "category": "export_artifact",
            "record_id": str(rows["export"].id),
            "operation": "delete_tree",
            "relative_path": str(rows["export"].id),
        }
    ]
    revived.run.cleanup_intent_snapshot = cleanup_snapshot
    revived.run.error_snapshot = [{"phase": "workflow", "code": "retention_job_cancelled", "message": "cancelled"}]
    await db_session.flush()
    resumed_cleanup = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    assert resumed_cleanup.job.status == "queued"
    assert resumed_cleanup.run.status == "partial"
    assert resumed_cleanup.run.started_at == NOW - timedelta(minutes=2)
    assert resumed_cleanup.run.cleanup_intent_snapshot == cleanup_snapshot
    assert resumed_cleanup.run.error_snapshot == []


@pytest.mark.asyncio
async def test_execution_revalidates_new_references_marks_db_before_safe_filesystem_cleanup(
    db_session,
    tmp_path,
):
    media_root = tmp_path / "media"
    rows = await _seed_all_categories(db_session, media_root)
    service = RetentionService(db_session, clock=lambda: NOW, media_root=media_root)
    preview = await service.preview()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    db_session.add(
        ContentItem(
            item_type="article",
            sort_at=NOW,
            date_parse_status="parsed",
            primary_image_id=rows["media"].id,
        )
    )
    await db_session.flush()

    plan = await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )

    await db_session.refresh(rows["raw"])
    await db_session.refresh(rows["completed"])
    await db_session.refresh(rows["attempt"])
    await db_session.refresh(rows["export"])
    await db_session.refresh(rows["media"])
    await db_session.refresh(enqueued.run)
    assert rows["raw"].raw_text is None
    assert rows["completed"].payload == {}
    assert rows["completed"].result == {}
    assert rows["attempt"].queries == []
    assert rows["attempt"].usage == {}
    assert rows["export"].result == {
        "export_id": str(rows["export"].id),
        "content_pack_id": rows["export"].payload["content_pack_id"],
        "state": "expired",
        "expired_at": NOW.isoformat(),
    }
    assert rows["media"].storage_path == str(rows["media_file"])
    assert rows["media"].fetch_status == "downloaded"
    assert rows["media_file"].exists()
    assert rows["export_dir"].exists()
    assert enqueued.run.status == "running"
    assert len(plan.cleanup_intents) == 1
    assert plan.cleanup_intents[0].model_dump() == {
        "category": "export_artifact",
        "record_id": rows["export"].id,
        "operation": "delete_tree",
        "relative_path": str(rows["export"].id),
    }
    replayed_plan = await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )
    assert replayed_plan == plan

    # Simulate a crash after deletion but before the final audit commit.
    shutil.rmtree(rows["export_dir"])

    finished = await service.finish_filesystem_phase(
        enqueued.run.id,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )

    assert finished.status == "succeeded"
    assert not rows["export_dir"].exists()
    assert rows["media_file"].exists()
    assert finished.count_snapshot["execution"]["skipped"]["unreferenced_media"] == 1
    first_counts = json.loads(json.dumps(finished.count_snapshot))
    replayed_finish = await service.finish_filesystem_phase(
        enqueued.run.id,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )
    assert replayed_finish.status == "succeeded"
    assert replayed_finish.count_snapshot == first_counts


@pytest.mark.asyncio
async def test_execution_never_marks_or_deletes_media_outside_owned_root(db_session, tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"do not delete")
    media = MediaAsset(
        original_url="https://example.test/outside.bin",
        normalized_url="https://example.test/outside.bin",
        url_hash="d" * 64,
        kind="image",
        byte_length=outside.stat().st_size,
        source_field="fixture",
        checksum_sha256="e" * 64,
        storage_path=str(outside),
        fetch_status="downloaded",
        created_at=NOW - timedelta(days=31),
        updated_at=NOW - timedelta(days=31),
    )
    db_session.add(media)
    await db_session.flush()
    service = RetentionService(db_session, clock=lambda: NOW, media_root=tmp_path)
    preview = await service.preview()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    media_root = tmp_path / "media"
    media_root.mkdir()

    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )
    await db_session.refresh(media)
    assert media.storage_path == str(outside)
    assert media.fetch_status == "downloaded"
    assert outside.exists()
    await db_session.refresh(enqueued.run)
    assert enqueued.run.cleanup_intent_snapshot == []
    assert enqueued.run.error_snapshot[0]["code"] == "unsafe_media_path"


@pytest.mark.asyncio
async def test_execution_rejects_symlinked_export_root_before_tombstone(db_session, tmp_path):
    media_root = tmp_path / "media"
    rows = await _seed_all_categories(db_session, media_root)
    service = RetentionService(db_session, clock=lambda: NOW, media_root=media_root)
    preview = await service.preview()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    real_export_root = tmp_path / "real-exports"
    (tmp_path / "exports").rename(real_export_root)
    (tmp_path / "exports").symlink_to(real_export_root, target_is_directory=True)

    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )

    await db_session.refresh(rows["export"])
    await db_session.refresh(enqueued.run)
    assert rows["export"].result["state"] == "complete"
    assert all(intent["category"] != "export_artifact" for intent in enqueued.run.cleanup_intent_snapshot)
    assert any(error["code"] == "unsafe_export_path" for error in enqueued.run.error_snapshot)


@pytest.mark.asyncio
async def test_filesystem_phase_rejects_nested_symlink_swap_after_database_commit(
    db_session,
    tmp_path,
):
    media_root = tmp_path / "media"
    original_parent = media_root / "aa"
    original_parent.mkdir(parents=True)
    original_file = original_parent / "asset.bin"
    original_file.write_bytes(b"original")
    media = MediaAsset(
        original_url="https://example.test/swap.bin",
        normalized_url="https://example.test/swap.bin",
        url_hash="e" * 64,
        kind="image",
        source_field="fixture",
        storage_path=str(original_file),
        fetch_status="downloaded",
        created_at=NOW - timedelta(days=31),
        updated_at=NOW - timedelta(days=31),
    )
    db_session.add(media)
    await db_session.flush()
    service = RetentionService(db_session, clock=lambda: NOW, media_root=media_root)
    preview = await service.preview()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )

    preserved_parent = media_root / "preserved-aa"
    original_parent.rename(preserved_parent)
    outside_parent = tmp_path / "outside"
    outside_parent.mkdir()
    outside_file = outside_parent / "asset.bin"
    outside_file.write_bytes(b"outside")
    original_parent.symlink_to(outside_parent, target_is_directory=True)

    finished = await service.finish_filesystem_phase(
        enqueued.run.id,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )

    assert finished.status == "partial"
    assert outside_file.read_bytes() == b"outside"
    assert (preserved_parent / "asset.bin").read_bytes() == b"original"
    assert finished.error_snapshot[0]["code"] == "unsafe_or_failed_cleanup"


@pytest.mark.asyncio
async def test_state_hash_drift_is_skipped_without_scrubbing_unpreviewed_state(
    db_session,
    tmp_path,
):
    raw = RawPayload(
        payload_kind="feed",
        request_url="https://example.test/feed",
        headers={"version": 1},
        raw_text="original",
        captured_at=NOW - timedelta(days=31),
    )
    db_session.add(raw)
    await db_session.flush()
    service = RetentionService(db_session, clock=lambda: NOW, media_root=tmp_path / "media")
    preview = await service.preview()
    raw.headers = {"version": 2, "new": "must survive"}
    await db_session.flush()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )

    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )

    await db_session.refresh(raw)
    await db_session.refresh(enqueued.run)
    assert raw.request_url == "https://example.test/feed"
    assert raw.raw_text == "original"
    assert raw.headers == {"version": 2, "new": "must survive"}
    assert enqueued.run.count_snapshot["execution"]["skipped"]["raw_payload"] == 1


@pytest.mark.asyncio
async def test_preview_protects_canonical_file_claimed_by_newer_symlink_alias_row(
    db_session,
    tmp_path,
):
    media_root = tmp_path / "media"
    path = media_root / "aa" / "shared.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"shared")
    (media_root / "alias").symlink_to(path.parent, target_is_directory=True)
    old = MediaAsset(
        original_url="https://example.test/old.bin",
        normalized_url="https://example.test/old.bin",
        url_hash="1" * 64,
        kind="image",
        source_field="fixture",
        storage_path=str(path),
        fetch_status="downloaded",
        created_at=NOW - timedelta(days=31),
        updated_at=NOW - timedelta(days=31),
    )
    newer_alias = MediaAsset(
        original_url="https://example.test/new.bin",
        normalized_url="https://example.test/new.bin",
        url_hash="2" * 64,
        kind="image",
        source_field="fixture",
        storage_path=str(media_root / "alias" / "shared.bin"),
        fetch_status="downloaded",
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )
    db_session.add_all([old, newer_alias])
    await db_session.flush()
    service = RetentionService(db_session, clock=lambda: NOW, media_root=media_root)
    preview = await service.preview()
    assert old.id not in {candidate.record_id for candidate in preview.candidates}
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )

    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )

    await db_session.refresh(old)
    await db_session.refresh(enqueued.run)
    assert old.storage_path == str(path)
    assert old.fetch_status == "downloaded"
    assert path.exists()
    assert enqueued.run.cleanup_intent_snapshot == []
    assert enqueued.run.count_snapshot["execution"]["skipped"]["unreferenced_media"] == 0


@pytest.mark.asyncio
async def test_preview_protects_evidence_revision_media_and_active_attempt_lineages(
    db_session,
    tmp_path,
):
    story = Story(title="Protected story")
    content_item = ContentItem(
        item_type="article",
        sort_at=NOW,
        date_parse_status="parsed",
    )
    raw = RawPayload(
        payload_kind="feed",
        request_url="https://example.test/evidence",
        raw_text="immutable evidence input",
        captured_at=NOW - timedelta(days=60),
    )
    db_session.add_all([story, content_item, raw])
    await db_session.flush()
    db_session.add_all(
        [
            SourceItem(
                content_item_id=content_item.id,
                raw_payload_id=raw.id,
                title_raw="must remain",
                content_text_raw="must remain",
            ),
            StoryEvidenceSnapshot(
                story_id=story.id,
                content_item_id=content_item.id,
                evidence_key="evidence:protected",
                source_url="https://example.test/evidence",
                content_text="must remain",
                content_sha256="3" * 64,
                captured_at=NOW - timedelta(days=60),
            ),
        ]
    )
    revision = StoryRevision(
        story_id=story.id,
        revision_number=1,
        narrative="protected revision",
        created_by="operator",
        created_at=NOW - timedelta(days=120),
    )
    brand = BrandProfile(
        name=f"brand-{uuid4()}",
        output_language="en",
        tone="neutral",
    )
    prompt = PromptTemplate(
        purpose_key=f"purpose-{uuid4()}",
        name="Protected prompt",
    )
    db_session.add_all([revision, brand, prompt])
    await db_session.flush()
    prompt_version = PromptTemplateVersion(
        prompt_template_id=prompt.id,
        version=1,
        system_template="system",
        user_template="user",
        output_schema_version="v1",
        output_schema={},
        checksum_sha256="4" * 64,
    )
    pack = ContentPack(
        story_revision_id=revision.id,
        brand_profile_id=brand.id,
    )
    db_session.add_all([prompt_version, pack])
    await db_session.flush()
    generation_run = GenerationRun(
        story_revision_id=revision.id,
        prompt_template_version_id=prompt_version.id,
        status="succeeded",
        input_hash="5" * 64,
        request_payload={"must": "remain"},
        output_payload={"must": "remain"},
        started_at=NOW - timedelta(days=100),
        finished_at=NOW - timedelta(days=99),
        created_at=NOW - timedelta(days=100),
    )
    variant = PlatformVariant(content_pack_id=pack.id, platform="telegram")
    db_session.add_all([generation_run, variant])
    await db_session.flush()
    generation_attempt = GenerationAttempt(
        generation_run_id=generation_run.id,
        attempt_number=1,
        provider="fixture",
        prompt_snapshot={"must": "remain"},
        response_payload={"must": "remain"},
        usage={"tokens": 1},
        status="succeeded",
        started_at=NOW - timedelta(days=100),
        finished_at=NOW - timedelta(days=99),
    )
    media_root = tmp_path / "media"
    media_file = media_root / "protected.bin"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"protected")
    media = MediaAsset(
        original_url="https://example.test/protected.bin",
        normalized_url="https://example.test/protected.bin",
        url_hash="6" * 64,
        kind="image",
        source_field="fixture",
        storage_path=str(media_file),
        fetch_status="downloaded",
        created_at=NOW - timedelta(days=60),
        updated_at=NOW - timedelta(days=60),
    )
    db_session.add_all([generation_attempt, media])
    await db_session.flush()
    platform_revision = PlatformVariantRevision(
        platform_variant_id=variant.id,
        generation_attempt_id=generation_attempt.id,
        revision_number=1,
        content={"media_asset_id": str(media.id)},
        content_hash="7" * 64,
        evidence_map=[],
        created_by="generator",
    )
    research_run = ResearchRun(
        story_id=story.id,
        requested_mode="standard",
        status="running",
        created_at=NOW - timedelta(days=100),
        started_at=NOW - timedelta(days=100),
    )
    destination = Destination(
        name=f"destination-{uuid4()}",
        platform="telegram",
        target_ref="@protected",
        secret_ref="secret-ref",
    )
    db_session.add_all([platform_revision, research_run, destination])
    await db_session.flush()
    research_attempt = ResearchAttempt(
        research_run_id=research_run.id,
        attempt_number=1,
        queries=["must remain"],
        status="succeeded",
        usage={"tokens": 1},
        started_at=NOW - timedelta(days=100),
        finished_at=NOW - timedelta(days=99),
    )
    publish_job = PublishJob(
        destination_id=destination.id,
        platform_variant_revision_id=platform_revision.id,
        status="succeeded",
        idempotency_key=f"publish:{uuid4()}",
        payload_hash="8" * 64,
        created_at=NOW - timedelta(days=100),
    )
    db_session.add_all([research_attempt, publish_job])
    await db_session.flush()
    publish_attempt = PublishAttempt(
        publish_job_id=publish_job.id,
        attempt_number=1,
        sanitized_payload={"must": "remain"},
        payload_hash="8" * 64,
        status="succeeded",
        remote_response={"must": "remain"},
        started_at=NOW - timedelta(days=100),
        finished_at=NOW - timedelta(days=99),
    )
    receipt = PublishOperationReceipt(
        publish_job_id=publish_job.id,
        operation_index=0,
        operation_key="send:0",
        method="sendMessage",
        request_hash="9" * 64,
        status="ambiguous",
    )
    db_session.add_all([publish_attempt, receipt])
    await db_session.flush()

    preview = await RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=media_root,
    ).preview()

    protected = {
        raw.id,
        media.id,
        generation_attempt.id,
        research_attempt.id,
        publish_attempt.id,
    }
    assert protected.isdisjoint({candidate.record_id for candidate in preview.candidates})


@pytest.mark.asyncio
async def test_published_revision_event_protects_completed_workflow_job_from_scrubbing(
    db_session,
    tmp_path,
):
    story = Story(title="Published audit story", created_at=NOW - timedelta(days=120))
    brand = BrandProfile(
        name=f"published-audit-brand-{uuid4()}",
        output_language="en",
        tone="neutral",
    )
    route_job = WorkflowJob(
        job_type="telegram.route.process",
        status="succeeded",
        payload={"audit": "must remain"},
        result={"audit": "must remain"},
        idempotency_key=f"published-audit-route:{uuid4()}",
        origin="automation",
        finished_at=NOW - timedelta(days=91),
        created_at=NOW - timedelta(days=92),
    )
    db_session.add_all([story, brand, route_job])
    await db_session.flush()
    story_revision = StoryRevision(
        story_id=story.id,
        revision_number=1,
        narrative="Published audit revision",
        created_by="automation",
        created_at=NOW - timedelta(days=92),
    )
    destination = Destination(
        name=f"published-audit-destination-{uuid4()}",
        platform="telegram",
        target_ref="@published_audit",
        secret_ref="published-audit-secret",
    )
    db_session.add_all([story_revision, destination])
    await db_session.flush()
    pack = ContentPack(story_revision_id=story_revision.id, brand_profile_id=brand.id)
    db_session.add(pack)
    await db_session.flush()
    variant = PlatformVariant(content_pack_id=pack.id, platform="telegram")
    db_session.add(variant)
    await db_session.flush()
    platform_revision = PlatformVariantRevision(
        platform_variant_id=variant.id,
        revision_number=1,
        content={"body": "Published"},
        content_hash="a" * 64,
        evidence_map=[],
        created_by="automation",
    )
    db_session.add(platform_revision)
    await db_session.flush()
    event_payload = {
        "revision_id": str(platform_revision.id),
        "audit": "must remain",
    }
    audit_event = WorkflowEvent(
        workflow_job_id=route_job.id,
        event_type="telegram.revision.auto_approved",
        actor="automation",
        event_data=event_payload,
        created_at=NOW - timedelta(days=91),
    )
    publish_job = PublishJob(
        destination_id=destination.id,
        platform_variant_revision_id=platform_revision.id,
        status="succeeded",
        idempotency_key=f"published-audit:{uuid4()}",
        payload_hash="b" * 64,
        created_at=NOW - timedelta(days=91),
    )
    db_session.add_all([audit_event, publish_job])
    await db_session.flush()
    publication = Publication(
        publish_job_id=publish_job.id,
        destination_id=destination.id,
        platform_variant_revision_id=platform_revision.id,
        remote_message_ids=[12345],
        permalink="https://t.me/published_audit/12345",
        payload_hash=publish_job.payload_hash,
        published_at=NOW - timedelta(days=91),
    )
    db_session.add(publication)
    await db_session.flush()

    service = RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path / "media",
    )
    preview = await service.preview()

    assert route_job.id not in {candidate.record_id for candidate in preview.candidates}

    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )

    await db_session.refresh(route_job)
    await db_session.refresh(audit_event)
    assert route_job.payload == {"audit": "must remain"}
    assert route_job.result == {"audit": "must remain"}
    assert audit_event.event_data == event_payload


@pytest.mark.asyncio
async def test_reconfirmation_retries_an_all_skipped_database_phase_after_root_is_fixed(
    db_session,
    tmp_path,
):
    rows = await _seed_all_categories(db_session, tmp_path / "media")
    policy = RetentionPolicyInput(
        raw_payload_days=3650,
        completed_job_days=3650,
        attempt_metadata_days=3650,
        export_artifact_days=14,
        unreferenced_media_days=3650,
    )
    service = RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path / "media",
    )
    preview = await service.preview(policy)
    assert [(candidate.category, candidate.record_id) for candidate in preview.candidates] == [
        ("export_artifact", rows["export"].id)
    ]
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    export_root = tmp_path / "exports"
    real_export_root = tmp_path / "real-exports"
    export_root.rename(real_export_root)
    export_root.symlink_to(real_export_root, target_is_directory=True)

    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=export_root,
        media_root=tmp_path / "media",
    )
    first_pass = await service.finish_filesystem_phase(
        enqueued.run.id,
        export_root=export_root,
        media_root=tmp_path / "media",
    )

    # The database-phase finding stays visible and tagged, but must not pin the run
    # at "partial": that made the workflow job retry a state re-running the phase
    # can never clear. Operator reconfirmation is the retry path.
    assert first_pass.status == "succeeded"
    assert [error["phase"] for error in first_pass.error_snapshot] == ["database"]
    assert [error["code"] for error in first_pass.error_snapshot] == ["unsafe_export_path"]
    assert first_pass.cleanup_intent_snapshot == []
    assert first_pass.count_snapshot["execution"]["expired"]["export_artifact"] == 0
    assert first_pass.count_snapshot["execution"]["database_skipped"]["export_artifact"] == 1
    assert rows["export"].result["state"] == "complete"
    enqueued.job.status = JobStatus.FAILED
    enqueued.job.attempt_count = enqueued.job.max_attempts
    enqueued.job.result = {"partial": True}
    enqueued.job.finished_at = NOW
    await db_session.flush()

    export_root.unlink()
    real_export_root.rename(export_root)
    refreshed_preview = await service.preview(policy)
    assert refreshed_preview.run_id == preview.run_id
    reconfirmed = await service.enqueue(
        preview_token=refreshed_preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )

    assert reconfirmed.run.status == "queued"
    assert reconfirmed.job.status == JobStatus.QUEUED
    assert reconfirmed.job.attempt_count == 0
    assert reconfirmed.job.result == {}
    await service.execute_db_phase(
        reconfirmed.run.id,
        refreshed_preview.preview_token,
        export_root=export_root,
        media_root=tmp_path / "media",
    )
    finished = await service.finish_filesystem_phase(
        reconfirmed.run.id,
        export_root=export_root,
        media_root=tmp_path / "media",
    )

    await db_session.refresh(rows["export"])
    assert finished.status == "succeeded"
    assert rows["export"].result["state"] == "expired"
    assert not rows["export_dir"].exists()


@pytest.mark.asyncio
async def test_reconfirmation_retries_a_succeeded_all_skipped_run_after_reference_is_removed(
    db_session,
    tmp_path,
):
    rows = await _seed_all_categories(db_session, tmp_path / "media")
    policy = RetentionPolicyInput(
        raw_payload_days=3650,
        completed_job_days=3650,
        attempt_metadata_days=3650,
        export_artifact_days=3650,
        unreferenced_media_days=30,
    )
    service = RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path / "media",
    )
    preview = await service.preview(policy)
    assert [(candidate.category, candidate.record_id) for candidate in preview.candidates] == [
        ("unreferenced_media", rows["media"].id)
    ]
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    reference = ContentItem(
        item_type="article",
        title="Late media reference",
        content_text="Retain this media",
        sort_at=NOW,
        date_parse_status="parsed",
        primary_image_id=rows["media"].id,
    )
    db_session.add(reference)
    await db_session.flush()

    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )
    skipped = await service.finish_filesystem_phase(
        enqueued.run.id,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )

    assert skipped.status == "succeeded"
    assert skipped.cleanup_intent_snapshot == []
    assert skipped.count_snapshot["execution"]["expired"]["unreferenced_media"] == 0
    assert skipped.count_snapshot["execution"]["database_skipped"]["unreferenced_media"] == 1
    assert rows["media"].fetch_status == "downloaded"
    assert rows["media_file"].exists()

    enqueued.job.status = JobStatus.SUCCEEDED
    enqueued.job.attempt_count = 1
    enqueued.job.result = {"run_id": str(enqueued.run.id), "status": "succeeded"}
    enqueued.job.finished_at = NOW
    reference.primary_image_id = None
    await db_session.flush()
    refreshed_preview = await service.preview(policy)
    assert refreshed_preview.run_id == preview.run_id
    reconfirmed = await service.enqueue(
        preview_token=refreshed_preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )

    assert reconfirmed.run.status == "queued"
    assert reconfirmed.job.status == JobStatus.QUEUED
    assert reconfirmed.job.attempt_count == 0
    assert reconfirmed.job.result == {}
    await service.execute_db_phase(
        reconfirmed.run.id,
        refreshed_preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )
    finished = await service.finish_filesystem_phase(
        reconfirmed.run.id,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )

    await db_session.refresh(rows["media"])
    assert finished.status == "succeeded"
    assert rows["media"].fetch_status == "expired"
    assert rows["media"].storage_path is None
    assert not rows["media_file"].exists()


@pytest.mark.asyncio
async def test_filesystem_phase_rechecks_reclaimed_media_and_keeps_exact_replay_counts(
    db_session,
    tmp_path,
):
    media_root = tmp_path / "media"
    media_root.mkdir()
    old_rows: list[MediaAsset] = []
    paths = [
        media_root / "first.bin",
        media_root / "second.bin",
        media_root / "third.bin",
    ]
    for index, path in enumerate(paths, start=1):
        path.write_bytes(f"asset-{index}".encode())
        row = MediaAsset(
            original_url=f"https://example.test/{index}.bin",
            normalized_url=f"https://example.test/{index}.bin",
            url_hash=f"{index + 2}" * 64,
            kind="image",
            source_field="fixture",
            storage_path=str(path),
            fetch_status="downloaded",
            created_at=NOW - timedelta(days=31),
            updated_at=NOW - timedelta(days=31),
        )
        old_rows.append(row)
    db_session.add_all(old_rows)
    await db_session.flush()
    service = RetentionService(db_session, clock=lambda: NOW, media_root=media_root)
    preview = await service.preview()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    plan = await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )
    assert len(plan.cleanup_intents) == 3

    reclaim_alias = media_root / "reclaim-alias"
    reclaim_alias.symlink_to(media_root, target_is_directory=True)
    reclaimed = MediaAsset(
        original_url="https://example.test/reclaimed.bin",
        normalized_url="https://example.test/reclaimed.bin",
        url_hash="a" * 64,
        kind="image",
        source_field="fixture",
        storage_path=str(reclaim_alias / paths[0].name),
        fetch_status="downloaded",
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(reclaimed)
    await db_session.flush()

    finished = await service.finish_filesystem_phase(
        enqueued.run.id,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )
    assert finished.status == "succeeded"
    assert paths[0].exists()
    assert not paths[1].exists()
    assert not paths[2].exists()
    assert finished.count_snapshot["execution"]["filesystem_deleted"]["unreferenced_media"] == 2
    assert finished.count_snapshot["execution"]["skipped"]["unreferenced_media"] == 1
    assert finished.count_snapshot["execution"]["filesystem_skipped"]["unreferenced_media"] == 1
    assert finished.error_snapshot == []

    reclaimed.storage_path = None
    await db_session.flush()
    replay = await service.finish_filesystem_phase(
        enqueued.run.id,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )
    assert replay.status == "succeeded"
    assert paths[0].exists()
    assert replay.count_snapshot == finished.count_snapshot


@pytest.mark.asyncio
async def test_shared_file_survives_new_reference_to_any_expired_owner(
    db_session,
    tmp_path,
):
    media_root = tmp_path / "media"
    media_root.mkdir()
    shared_file = media_root / "shared.bin"
    shared_file.write_bytes(b"shared")
    owners = [
        MediaAsset(
            original_url=f"https://example.test/shared-{index}.bin",
            normalized_url=f"https://example.test/shared-{index}.bin",
            url_hash=f"{index}" * 64,
            kind="image",
            source_field="fixture",
            storage_path=str(shared_file),
            fetch_status="downloaded",
            created_at=NOW - timedelta(days=31),
            updated_at=NOW - timedelta(days=31),
        )
        for index in (7, 8)
    ]
    db_session.add_all(owners)
    await db_session.flush()
    service = RetentionService(db_session, clock=lambda: NOW, media_root=media_root)
    preview = await service.preview()
    assert {owner.id for owner in owners}.issubset({candidate.record_id for candidate in preview.candidates})
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    plan = await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )
    assert len(plan.cleanup_intents) == 2
    assert {intent.relative_path for intent in plan.cleanup_intents} == {"shared.bin"}
    db_session.add(
        ContentItem(
            item_type="article",
            sort_at=NOW,
            date_parse_status="parsed",
            primary_image_id=owners[1].id,
        )
    )
    await db_session.flush()

    finished = await service.finish_filesystem_phase(
        enqueued.run.id,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )

    assert finished.status == "succeeded"
    assert shared_file.exists()
    assert finished.count_snapshot["execution"]["filesystem_skipped"]["unreferenced_media"] == 1


@pytest.mark.asyncio
async def test_generation_parent_is_not_scrubbed_when_any_sibling_state_drifts(
    db_session,
    tmp_path,
):
    prompt = PromptTemplate(
        purpose_key=f"drift-{uuid4()}",
        name="Drift prompt",
    )
    db_session.add(prompt)
    await db_session.flush()
    prompt_version = PromptTemplateVersion(
        prompt_template_id=prompt.id,
        version=1,
        system_template="system",
        user_template="user",
        output_schema_version="v1",
        output_schema={},
        checksum_sha256="c" * 64,
    )
    db_session.add(prompt_version)
    await db_session.flush()
    generation_run = GenerationRun(
        prompt_template_version_id=prompt_version.id,
        status="succeeded",
        input_hash="d" * 64,
        request_payload={"parent": "must remain"},
        output_payload={"parent": "must remain"},
        started_at=NOW - timedelta(days=100),
        finished_at=NOW - timedelta(days=99),
        created_at=NOW - timedelta(days=100),
    )
    db_session.add(generation_run)
    await db_session.flush()
    attempts = [
        GenerationAttempt(
            generation_run_id=generation_run.id,
            attempt_number=number,
            provider="fixture",
            prompt_snapshot={"attempt": number},
            response_payload={"attempt": number},
            usage={"tokens": number},
            status="succeeded",
            started_at=NOW - timedelta(days=100),
            finished_at=NOW - timedelta(days=99),
        )
        for number in (1, 2)
    ]
    db_session.add_all(attempts)
    await db_session.flush()
    service = RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path / "media",
    )
    preview = await service.preview()
    assert {
        candidate.record_id for candidate in preview.candidates if candidate.record_type == "generation_attempt"
    } == {attempt.id for attempt in attempts}
    attempts[0].usage = {"tokens": 999, "drift": True}
    await db_session.flush()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )

    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )

    for attempt in attempts:
        await db_session.refresh(attempt)
        assert attempt.prompt_snapshot != {}
        assert attempt.response_payload != {}
    await db_session.refresh(generation_run)
    await db_session.refresh(enqueued.run)
    assert generation_run.request_payload == {"parent": "must remain"}
    assert generation_run.output_payload == {"parent": "must remain"}
    assert enqueued.run.count_snapshot["execution"]["skipped"]["attempt_metadata"] == 2


@pytest.mark.asyncio
async def test_completed_generation_run_and_mixed_success_siblings_are_retention_candidates(
    db_session,
    tmp_path,
):
    prompt = PromptTemplate(
        purpose_key=f"completed-{uuid4()}",
        name="Completed generation prompt",
    )
    db_session.add(prompt)
    await db_session.flush()
    prompt_version = PromptTemplateVersion(
        prompt_template_id=prompt.id,
        version=1,
        system_template="system",
        user_template="user",
        output_schema_version="v1",
        output_schema={},
        checksum_sha256="f" * 64,
    )
    db_session.add(prompt_version)
    await db_session.flush()
    completed_run = GenerationRun(
        prompt_template_version_id=prompt_version.id,
        status="completed",
        input_hash="a" * 64,
        request_payload={"terminal": True},
        output_payload={"terminal": True},
        started_at=NOW - timedelta(days=100),
        finished_at=NOW - timedelta(days=99),
        created_at=NOW - timedelta(days=100),
    )
    active_run = GenerationRun(
        prompt_template_version_id=prompt_version.id,
        status="running",
        input_hash="b" * 64,
        request_payload={"active": True},
        output_payload={},
        started_at=NOW - timedelta(days=100),
        created_at=NOW - timedelta(days=100),
    )
    db_session.add_all([completed_run, active_run])
    await db_session.flush()
    terminal_attempts = [
        GenerationAttempt(
            generation_run_id=completed_run.id,
            attempt_number=number,
            provider="fixture",
            prompt_snapshot={"attempt": number},
            response_payload={"attempt": number},
            usage={"tokens": number},
            status=status,
            started_at=NOW - timedelta(days=100),
            finished_at=NOW - timedelta(days=99),
        )
        for number, status in ((1, "completed"), (2, "succeeded"))
    ]
    active_attempt = GenerationAttempt(
        generation_run_id=active_run.id,
        attempt_number=1,
        provider="fixture",
        prompt_snapshot={"active": True},
        response_payload={"active": True},
        usage={"tokens": 1},
        status="completed",
        started_at=NOW - timedelta(days=100),
        finished_at=NOW - timedelta(days=99),
    )
    db_session.add_all([*terminal_attempts, active_attempt])
    await db_session.flush()

    preview = await RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path / "media",
    ).preview()
    selected = {
        candidate.record_id for candidate in preview.candidates if candidate.record_type == "generation_attempt"
    }
    selected_candidates = [
        candidate
        for candidate in preview.candidates
        if candidate.record_id in {attempt.id for attempt in terminal_attempts}
    ]

    assert selected == {attempt.id for attempt in terminal_attempts}
    assert active_attempt.id not in selected
    assert [candidate.byte_length for candidate in selected_candidates] == [None, None]
    assert preview.counts["attempt_metadata"].byte_length is None

    completed_run.request_payload = {"terminal": True, "drift": "parent state"}
    await db_session.flush()
    drifted = await RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path / "media",
    ).preview()
    assert drifted.preview_token != preview.preview_token


@pytest.mark.asyncio
async def test_concurrent_identical_previews_converge_on_one_persisted_run(session_factory):
    async with session_factory() as seed_session:
        seed_session.add(
            RawPayload(
                payload_kind="feed",
                request_url="https://example.test/concurrent",
                raw_text="payload",
                captured_at=NOW - timedelta(days=31),
            )
        )
        await seed_session.commit()

    async def create_preview():
        async with session_factory() as session:
            preview = await RetentionService(session, clock=lambda: NOW).preview()
            await session.commit()
            return preview

    first, second = await asyncio.gather(create_preview(), create_preview())

    assert first.run_id == second.run_id
    assert first.preview_token == second.preview_token
    async with session_factory() as check_session:
        count = await check_session.scalar(
            select(func.count(RetentionRun.id)).where(RetentionRun.preview_token == first.preview_token)
        )
    assert count == 1


@pytest.mark.asyncio
async def test_reference_table_fence_serializes_no_fk_primary_image_insert(
    session_factory,
    tmp_path,
):
    media_root = tmp_path / "media"
    media_root.mkdir()
    media_file = media_root / "fenced.bin"
    media_file.write_bytes(b"fenced")
    async with session_factory() as seed_session:
        media = MediaAsset(
            original_url="https://example.test/fenced.bin",
            normalized_url="https://example.test/fenced.bin",
            url_hash="b" * 64,
            kind="image",
            source_field="fixture",
            storage_path=str(media_file),
            fetch_status="downloaded",
            created_at=NOW - timedelta(days=31),
            updated_at=NOW - timedelta(days=31),
        )
        seed_session.add(media)
        await seed_session.flush()
        preview = await RetentionService(
            seed_session,
            clock=lambda: NOW,
            media_root=media_root,
        ).preview()
        enqueued = await RetentionService(
            seed_session,
            clock=lambda: NOW,
            media_root=media_root,
        ).enqueue(
            preview_token=preview.preview_token,
            confirmation=RETENTION_CONFIRMATION,
        )
        media_id = media.id
        run_id = enqueued.run.id
        await seed_session.commit()

    revalidated = asyncio.Event()
    resume = asyncio.Event()

    class PausingRetentionService(RetentionService):
        async def _collect_candidates(self, *args, **kwargs):
            candidates = await super()._collect_candidates(*args, **kwargs)
            if kwargs.get("lock"):
                revalidated.set()
                await resume.wait()
            return candidates

    async def execute_retention():
        async with session_factory() as session:
            return await PausingRetentionService(
                session,
                clock=lambda: NOW,
                media_root=media_root,
            ).execute_db_phase(
                run_id,
                preview.preview_token,
                export_root=tmp_path / "exports",
                media_root=media_root,
            )

    async def insert_reference():
        async with session_factory() as session:
            session.add(
                ContentItem(
                    item_type="article",
                    sort_at=NOW,
                    date_parse_status="parsed",
                    primary_image_id=media_id,
                )
            )
            await session.flush()
            await session.commit()

    execute_task = asyncio.create_task(execute_retention())
    await revalidated.wait()
    reference_task = asyncio.create_task(insert_reference())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(reference_task), timeout=0.1)
    resume.set()
    await execute_task
    await asyncio.wait_for(reference_task, timeout=2)
    async with session_factory() as finish_session:
        finished = await RetentionService(
            finish_session,
            clock=lambda: NOW,
            media_root=media_root,
        ).finish_filesystem_phase(
            run_id,
            export_root=tmp_path / "exports",
            media_root=media_root,
        )
        assert finished.status == "succeeded"
        assert media_file.exists()
        assert finished.count_snapshot["execution"]["filesystem_skipped"]["unreferenced_media"] == 1


@pytest.mark.asyncio
async def test_database_phase_errors_do_not_pin_the_run_at_partial_forever(db_session, tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"do not delete")
    media = MediaAsset(
        original_url="https://example.test/unphased.bin",
        normalized_url="https://example.test/unphased.bin",
        url_hash="9" * 64,
        kind="image",
        byte_length=outside.stat().st_size,
        source_field="fixture",
        checksum_sha256="8" * 64,
        storage_path=str(outside),
        fetch_status="downloaded",
        created_at=NOW - timedelta(days=31),
        updated_at=NOW - timedelta(days=31),
    )
    db_session.add(media)
    await db_session.flush()
    service = RetentionService(db_session, clock=lambda: NOW, media_root=tmp_path)
    preview = await service.preview()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    media_root = tmp_path / "media"
    media_root.mkdir()

    await service.execute_db_phase(
        enqueued.run.id,
        preview.preview_token,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )
    finished = await service.finish_filesystem_phase(
        enqueued.run.id,
        export_root=tmp_path / "exports",
        media_root=media_root,
    )

    assert [error["code"] for error in finished.error_snapshot] == ["unsafe_media_path"]
    assert [error["phase"] for error in finished.error_snapshot] == ["database"]
    # A database-phase finding must stay visible without forcing the workflow job
    # into an unbreakable retry loop, so the terminal status is not "partial".
    assert finished.status == "succeeded"
    assert outside.exists()


@pytest.mark.asyncio
async def test_filesystem_cleanup_never_holds_table_locks_across_deletion(
    session_factory,
    tmp_path,
    monkeypatch,
):
    media_root = tmp_path / "media"
    media_root.mkdir()
    media_file = media_root / "unlocked.bin"
    media_file.write_bytes(b"unlocked")
    async with session_factory() as seed_session:
        media = MediaAsset(
            original_url="https://example.test/unlocked.bin",
            normalized_url="https://example.test/unlocked.bin",
            url_hash="7" * 64,
            kind="image",
            source_field="fixture",
            storage_path=str(media_file),
            fetch_status="downloaded",
            created_at=NOW - timedelta(days=31),
            updated_at=NOW - timedelta(days=31),
        )
        seed_session.add(media)
        await seed_session.flush()
        service = RetentionService(seed_session, clock=lambda: NOW, media_root=media_root)
        preview = await service.preview()
        enqueued = await service.enqueue(
            preview_token=preview.preview_token,
            confirmation=RETENTION_CONFIRMATION,
        )
        run_id = enqueued.run.id
        await service.execute_db_phase(
            run_id,
            preview.preview_token,
            export_root=tmp_path / "exports",
            media_root=media_root,
        )
        await seed_session.commit()

    loop = asyncio.get_running_loop()
    probe: dict[str, str] = {}
    original_delete = retention_filesystem._delete_relative_owned

    async def writer_probe() -> None:
        async with session_factory() as probe_session:
            await probe_session.execute(text("SET LOCAL lock_timeout = '2s'"))
            await probe_session.execute(text("LOCK TABLE media_assets IN ROW EXCLUSIVE MODE"))
            await probe_session.rollback()

    def delete_with_probe(root, relative_path, *, directory):
        if "result" not in probe:
            try:
                asyncio.run_coroutine_threadsafe(writer_probe(), loop).result(timeout=8)
                probe["result"] = "writers_unblocked"
            except BaseException as exc:  # noqa: BLE001 - failure detail is the assertion message
                probe["result"] = f"writers_blocked: {exc!r}"
        return original_delete(root, relative_path, directory=directory)

    monkeypatch.setattr(retention_filesystem, "_delete_relative_owned", delete_with_probe)

    async with session_factory() as finish_session:
        finished = await RetentionService(
            finish_session,
            clock=lambda: NOW,
            media_root=media_root,
        ).finish_filesystem_phase(
            run_id,
            export_root=tmp_path / "exports",
            media_root=media_root,
        )

    # The deletion pass must run with no retention transaction open: a concurrent
    # writer taking ROW EXCLUSIVE on media_assets may not be blocked, and the
    # blocking unlink may not occupy the event loop.
    assert probe["result"] == "writers_unblocked"
    assert finished.status == "succeeded"
    assert not media_file.exists()
    assert finished.count_snapshot["execution"]["filesystem_deleted"]["unreferenced_media"] == 1
