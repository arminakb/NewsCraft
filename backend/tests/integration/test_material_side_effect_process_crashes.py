from __future__ import annotations

import asyncio
import hashlib
import multiprocessing
import os
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.automations.models import AutomationDispatch
from app.automations.telegram.media import TelegramMediaStore
from app.generation.models import (
    ContentPack,
    GenerationAttempt,
    GenerationRun,
    PlatformVariantRevision,
)
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobHandlerRegistry
from app.jobs.repository import JobRepository
from app.jobs.types import JobStatus
from app.jobs.worker import WorkerRunner
from app.publishing.models import Publication, PublishJob, PublishOperationReceipt
from app.publishing.telegram.contracts import TelegramOperationResult
from app.research.models import ResearchAttempt, ResearchRun
from app.retention.models import RetentionRun
from app.retention.service import RETENTION_CONFIRMATION, RetentionService
from app.stories.models import StoryRevision
from tests.integration.test_publish_crash_recovery import _seed_publish_job
from tests.postgres.test_retention_service import _seed_all_categories
from tests.postgres.test_telegram_process_handler import seed_dispatch

CRASH_EXIT_CODE = 86
CHILD_ERROR_EXIT_CODE = 87
LEASE_SECONDS = 30
TELEGRAM_ROUTE_JOB_TYPES = (
    "telegram.route.backfill",
    "telegram.route.dry_run",
    "telegram.route.initialize",
    "telegram.route.poll",
)


class ProcessExitFaultInjector:
    """A true process-death injector; it never raises a Python exception."""

    def __init__(self, target: str) -> None:
        self.target = target

    async def hit(self, point: str, context) -> None:
        if point == self.target:
            os._exit(CRASH_EXIT_CODE)


class FileLedgerTelegramClient:
    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = ledger_path

    async def execute(self, operation, token):
        assert token == "destination-token"
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as ledger:
            ledger.write(f"{operation.key}\n")
            ledger.flush()
            os.fsync(ledger.fileno())
        return TelegramOperationResult(
            remote_message_ids=(9301,),
            response_metadata={"ok": True, "result_count": 1},
        )


async def _resolve_destination_secret(secret_ref: str) -> str:
    assert secret_ref == "TELEGRAM_DESTINATION_TOKEN"
    return "destination-token"


def _build_handler(job_type: str, config: dict[str, str], injector):
    if job_type == "content_pack.generate":
        from app.generation.handlers import build_canonical_generation_handler
        from tests.integration.conftest import _AcceptanceProfileResolver

        return build_canonical_generation_handler(
            _AcceptanceProfileResolver(),
            fault_injector=injector,
        )
    if job_type == "content_pack.generate_telegram":
        from app.generation.handlers import build_pack_generation_handler
        from tests.integration.conftest import _AcceptanceProfileResolver

        return build_pack_generation_handler(
            _AcceptanceProfileResolver(),
            fault_injector=injector,
        )
    if job_type == "content_pack.regenerate":
        from app.generation.handlers import build_regenerate_handler
        from tests.integration.conftest import _AcceptanceProfileResolver

        return build_regenerate_handler(
            _AcceptanceProfileResolver(),
            fault_injector=injector,
        )
    if job_type == "research_story":
        from app.research.fake import FakeResearchBackend
        from app.research.handlers import build_research_story_handler

        fixture_path = Path(config["research_fixture"])
        return build_research_story_handler(
            lambda _profile: FakeResearchBackend.from_fixture(fixture_path),
            fault_injector=injector,
        )
    if job_type == "telegram.route.process":
        from app.automations.telegram.handlers import build_telegram_process_handler
        from tests.postgres.test_telegram_process_handler import FakeProfileResolver

        return build_telegram_process_handler(
            FakeProfileResolver(),
            fault_injector=injector,
        )
    if job_type == "build_export":
        from app.exports.handlers import build_export_handler

        return build_export_handler(
            export_root=Path(config["export_root"]),
            media_root=Path(config["media_root"]),
            fault_injector=injector,
        )
    if job_type == "execute_retention":
        from app.retention.handlers import build_retention_handler

        return build_retention_handler(
            export_root=Path(config["export_root"]),
            media_root=Path(config["media_root"]),
            fault_injector=injector,
        )
    if job_type == "telegram.publish":
        from app.publishing.telegram.handlers import build_telegram_publish_handlers

        handlers = build_telegram_publish_handlers(
            FileLedgerTelegramClient(Path(config["telegram_ledger"])),
            _resolve_destination_secret,
            fault_injector=injector,
        )
        return handlers.publish
    raise AssertionError(f"unsupported process-crash handler: {job_type}")


async def _run_actual_worker(
    database_url: str,
    job_type: str,
    fault_point: str | None,
    observed_at: str,
    config: dict[str, str],
) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    injector = ProcessExitFaultInjector(fault_point) if fault_point is not None else None
    registry = JobHandlerRegistry()
    registry.register(job_type, _build_handler(job_type, config, injector))
    runner = WorkerRunner(
        session_factory=factory,
        handler_registry=registry,
        worker_id=f"material-crash:{job_type}:{fault_point or 'healthy'}",
        capabilities=(),
        clock=lambda: datetime.fromisoformat(observed_at),
        lease_seconds=LEASE_SECONDS,
        heartbeat_seconds=3600,
        fault_injector=injector,
    )
    try:
        processed = await runner.run_once()
        if not processed:
            raise AssertionError(f"no {job_type} job was claimable")
    finally:
        await runner.close()
        await engine.dispose()


def _actual_worker_process(
    database_url: str,
    job_type: str,
    fault_point: str | None,
    observed_at: str,
    config: dict[str, str],
    error_path: str,
) -> None:
    try:
        asyncio.run(_run_actual_worker(database_url, job_type, fault_point, observed_at, config))
    except BaseException:  # pragma: no cover - parent reports the child traceback
        Path(error_path).write_text(traceback.format_exc(), encoding="utf-8")
        os._exit(CHILD_ERROR_EXIT_CODE)


def _persist_route_media_then_die(root: str, error_path: str) -> None:
    try:
        TelegramMediaStore(
            Path(root),
            max_photo_bytes=1024,
            max_file_bytes=1024,
        ).persist(
            b"phase-2-route-media",
            mime_type="image/jpeg",
            file_name="route.jpg",
            kind="photo",
        )
        os._exit(CRASH_EXIT_CODE)
    except BaseException:  # pragma: no cover - parent reports the child traceback
        Path(error_path).write_text(traceback.format_exc(), encoding="utf-8")
        os._exit(CHILD_ERROR_EXIT_CODE)


def _run_child(
    *,
    job_type: str,
    fault_point: str | None,
    observed_at: datetime,
    config: dict[str, str],
    error_path: Path,
    expected_exit_code: int = CRASH_EXIT_CODE,
) -> None:
    process = multiprocessing.get_context("spawn").Process(
        target=_actual_worker_process,
        args=(
            os.environ["TEST_DATABASE_URL"],
            job_type,
            fault_point,
            observed_at.isoformat(),
            config,
            str(error_path),
        ),
    )
    process.start()
    process.join(timeout=45)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
        pytest.fail(f"child worker hung for {job_type} at {fault_point}")
    child_error = error_path.read_text(encoding="utf-8") if error_path.exists() else ""
    assert process.exitcode == expected_exit_code, child_error


async def _recover(release3_factory, *, recovered_at: datetime) -> None:
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()


def _base_config(app_harness) -> dict[str, str]:
    return {
        "export_root": str(app_harness.export_root),
        "media_root": str(app_harness.media_root),
        "research_fixture": str(Path(__file__).resolve().parents[1] / "fixtures/research_brief.json"),
    }


async def _assert_succeeded(release3_factory, job_id: UUID, *, attempts: int = 2) -> WorkflowJob:
    async with release3_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        assert job is not None
        assert job.status == JobStatus.SUCCEEDED
        assert job.attempt_count == attempts
        return job


@pytest.mark.parametrize("job_type", TELEGRAM_ROUTE_JOB_TYPES)
def test_telegram_route_media_is_content_addressed_across_literal_process_death(
    tmp_path: Path,
    job_type: str,
):
    """The four route handlers share this production media persistence path."""

    media_root = tmp_path / job_type / "stored"
    error_path = tmp_path / job_type / "child-error.txt"
    process = multiprocessing.get_context("spawn").Process(
        target=_persist_route_media_then_die,
        args=(str(media_root), str(error_path)),
    )
    process.start()
    process.join(timeout=30)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
        pytest.fail(f"route media child hung for {job_type}")
    child_error = error_path.read_text(encoding="utf-8") if error_path.exists() else ""
    assert process.exitcode == CRASH_EXIT_CODE, child_error

    store = TelegramMediaStore(media_root, max_photo_bytes=1024, max_file_bytes=1024)
    replay = store.persist(
        b"phase-2-route-media",
        mime_type="image/jpeg",
        file_name="route.jpg",
        kind="photo",
    )
    files = [path for path in media_root.rglob("*") if path.is_file()]
    assert files == [replay.path]
    assert replay.path.read_bytes() == b"phase-2-route-media"
    assert replay.checksum_sha256 == hashlib.sha256(b"phase-2-route-media").hexdigest()


async def test_canonical_generation_hard_death_retries_to_one_durable_revision(
    app_harness,
    release3_factory,
    tmp_path: Path,
):
    researched = await app_harness.create_researched_story()
    requested = await app_harness.request_pack(
        researched.id,
        research_run_id=researched.research_run_id,
        platforms=["telegram"],
    )
    job_id = UUID(requested["job_id"])
    async with release3_factory() as session:
        revisions_before = await session.scalar(
            select(func.count()).select_from(StoryRevision).where(StoryRevision.story_id == researched.id)
        )

    crashed_at = datetime.now(UTC) + timedelta(seconds=1)
    config = _base_config(app_harness)
    _run_child(
        job_type="content_pack.generate",
        fault_point="generation.after_provider_before_persist",
        observed_at=crashed_at,
        config=config,
        error_path=tmp_path / "canonical-crash.txt",
    )

    async with release3_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        runs = list(await session.scalars(select(GenerationRun)))
        attempts = list(await session.scalars(select(GenerationAttempt)))
        revisions_after_crash = await session.scalar(
            select(func.count()).select_from(StoryRevision).where(StoryRevision.story_id == researched.id)
        )
    assert job is not None and job.status == JobStatus.RUNNING
    assert len(runs) == len(attempts) == 1
    assert runs[0].status == attempts[0].status == "running"
    assert revisions_after_crash == revisions_before

    recovered_at = crashed_at + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover(release3_factory, recovered_at=recovered_at)
    _run_child(
        job_type="content_pack.generate",
        fault_point=None,
        observed_at=recovered_at,
        config=config,
        error_path=tmp_path / "canonical-retry.txt",
        expected_exit_code=0,
    )
    succeeded = await _assert_succeeded(release3_factory, job_id)
    async with release3_factory() as session:
        runs = list(await session.scalars(select(GenerationRun)))
        attempts = list(
            await session.scalars(
                select(GenerationAttempt)
                .where(GenerationAttempt.generation_run_id == runs[0].id)
                .order_by(GenerationAttempt.attempt_number)
            )
        )
        revisions_after_retry = await session.scalar(
            select(func.count()).select_from(StoryRevision).where(StoryRevision.story_id == researched.id)
        )
        continuation = await session.get(WorkflowJob, UUID(succeeded.result["continuation_job_id"]))
    assert len(runs) == 1 and runs[0].status == "succeeded"
    assert [item.status for item in attempts] == ["failed", "succeeded"]
    assert revisions_after_retry == revisions_before + 1
    assert continuation is not None and continuation.status == JobStatus.QUEUED


async def test_pack_generation_hard_death_retries_to_one_pack_artifact(
    app_harness,
    release3_factory,
    tmp_path: Path,
):
    researched = await app_harness.create_researched_story()
    requested = await app_harness.request_pack(
        researched.id,
        research_run_id=researched.research_run_id,
        platforms=["telegram"],
    )
    assert await app_harness.worker.run_once() is True
    async with release3_factory() as session:
        canonical = await session.get(WorkflowJob, UUID(requested["job_id"]))
        assert canonical is not None and canonical.status == JobStatus.SUCCEEDED
        job_id = UUID(canonical.result["continuation_job_id"])

    crashed_at = datetime.now(UTC) + timedelta(seconds=1)
    config = _base_config(app_harness)
    _run_child(
        job_type="content_pack.generate_telegram",
        fault_point="generation.after_provider_before_persist",
        observed_at=crashed_at,
        config=config,
        error_path=tmp_path / "pack-crash.txt",
    )
    async with release3_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        packs_after_crash = await session.scalar(select(func.count()).select_from(ContentPack))
    assert job is not None and job.status == JobStatus.RUNNING
    assert packs_after_crash == 0

    recovered_at = crashed_at + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover(release3_factory, recovered_at=recovered_at)
    _run_child(
        job_type="content_pack.generate_telegram",
        fault_point=None,
        observed_at=recovered_at,
        config=config,
        error_path=tmp_path / "pack-retry.txt",
        expected_exit_code=0,
    )
    succeeded = await _assert_succeeded(release3_factory, job_id)
    async with release3_factory() as session:
        packs = list(await session.scalars(select(ContentPack)))
        revisions = list(await session.scalars(select(PlatformVariantRevision)))
    assert len(packs) == 1
    assert len(revisions) == 1
    assert succeeded.result["content_pack_id"] == str(packs[0].id)
    assert succeeded.result["revision_id"] == str(revisions[0].id)


async def test_regeneration_hard_death_retries_to_one_child_revision(
    app_harness,
    release3_factory,
    tmp_path: Path,
):
    researched = await app_harness.create_researched_story()
    requested = await app_harness.request_pack(
        researched.id,
        research_run_id=researched.research_run_id,
        platforms=["telegram"],
    )
    await app_harness.run_until_idle()
    pack = await app_harness.pack_for_job(requested["job_id"])
    variant = pack["variants"][0]
    variant_id = UUID(variant["id"])
    async with release3_factory() as session:
        revisions_before = await session.scalar(
            select(func.count())
            .select_from(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant_id)
        )
    accepted = await app_harness.post_json(
        f"/platform-variants/{variant_id}/regenerate",
        {
            "generation_provider_profile_id": str(app_harness.fake_provider_profile_id),
            "instruction": "Use a sharper but still sourced opening.",
        },
        expected_status=202,
    )
    job_id = UUID(accepted["job_id"])

    crashed_at = datetime.now(UTC) + timedelta(seconds=1)
    config = _base_config(app_harness)
    _run_child(
        job_type="content_pack.regenerate",
        fault_point="generation.after_provider_before_persist",
        observed_at=crashed_at,
        config=config,
        error_path=tmp_path / "regenerate-crash.txt",
    )
    async with release3_factory() as session:
        revisions_after_crash = await session.scalar(
            select(func.count())
            .select_from(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant_id)
        )
    assert revisions_after_crash == revisions_before

    recovered_at = crashed_at + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover(release3_factory, recovered_at=recovered_at)
    _run_child(
        job_type="content_pack.regenerate",
        fault_point=None,
        observed_at=recovered_at,
        config=config,
        error_path=tmp_path / "regenerate-retry.txt",
        expected_exit_code=0,
    )
    await _assert_succeeded(release3_factory, job_id)
    async with release3_factory() as session:
        revisions_after_retry = await session.scalar(
            select(func.count())
            .select_from(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant_id)
        )
    assert revisions_after_retry == revisions_before + 1


async def test_research_hard_death_retries_to_one_result_revision(
    app_harness,
    release3_factory,
    tmp_path: Path,
):
    intake = await app_harness.post_json(
        "/stories/manual",
        {
            "kind": "text",
            "title": "Process crash research",
            "text": "Persisted source evidence. " * 40,
            "source_label": "Phase 2",
            "source_url": None,
        },
        expected_status=202,
    )
    await app_harness.run_until_idle()
    story = await app_harness.story_for_job(intake["job_id"])
    research = await app_harness.post_json(
        f"/stories/{story.id}/research-runs",
        {
            "mode": "manual",
            "depth": "standard",
            "provider_profile_id": str(app_harness.fake_provider_profile_id),
            "query_hint": "Verify the process-crash fixture",
        },
        expected_status=202,
    )
    job_id = UUID(research["job_id"])
    run_id = UUID(research["run_id"])
    async with release3_factory() as session:
        revisions_before = await session.scalar(
            select(func.count()).select_from(StoryRevision).where(StoryRevision.story_id == story.id)
        )

    crashed_at = datetime.now(UTC) + timedelta(seconds=1)
    config = _base_config(app_harness)
    _run_child(
        job_type="research_story",
        fault_point="research.after_provider_before_persist",
        observed_at=crashed_at,
        config=config,
        error_path=tmp_path / "research-crash.txt",
    )
    async with release3_factory() as session:
        run = await session.get(ResearchRun, run_id)
        attempts = list(await session.scalars(select(ResearchAttempt).where(ResearchAttempt.research_run_id == run_id)))
    assert run is not None and run.status == "running" and run.result_story_revision_id is None
    assert len(attempts) == 1 and attempts[0].status == "running"

    recovered_at = crashed_at + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover(release3_factory, recovered_at=recovered_at)
    _run_child(
        job_type="research_story",
        fault_point=None,
        observed_at=recovered_at,
        config=config,
        error_path=tmp_path / "research-retry.txt",
        expected_exit_code=0,
    )
    await _assert_succeeded(release3_factory, job_id)
    async with release3_factory() as session:
        run = await session.get(ResearchRun, run_id)
        attempts = list(
            await session.scalars(
                select(ResearchAttempt)
                .where(ResearchAttempt.research_run_id == run_id)
                .order_by(ResearchAttempt.attempt_number)
            )
        )
        revisions_after = await session.scalar(
            select(func.count()).select_from(StoryRevision).where(StoryRevision.story_id == story.id)
        )
    assert run is not None and run.status == "succeeded" and run.result_story_revision_id is not None
    assert [item.status for item in attempts] == ["failed", "succeeded"]
    assert revisions_after == revisions_before + 1


async def test_telegram_process_hard_death_retries_to_one_revision(
    release3_factory,
    tmp_path: Path,
):
    async with release3_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(session, route_name="LiteralProcessCrash")
            dispatch_id = dispatch.id
            job_id = job.id
            job.status = JobStatus.QUEUED
            job.attempt_count = 0
            job.started_at = None
            job.lease_owner = None
            job.lease_expires_at = None

    crashed_at = datetime.now(UTC) + timedelta(seconds=1)
    config = {"export_root": str(tmp_path / "exports"), "media_root": str(tmp_path / "media")}
    _run_child(
        job_type="telegram.route.process",
        fault_point="telegram_process.after_provider_before_persist",
        observed_at=crashed_at,
        config=config,
        error_path=tmp_path / "telegram-process-crash.txt",
    )
    async with release3_factory() as session:
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        runs = list(await session.scalars(select(GenerationRun)))
        attempts = list(await session.scalars(select(GenerationAttempt)))
        revision_count = await session.scalar(select(func.count()).select_from(PlatformVariantRevision))
    assert dispatch is not None and dispatch.status == "generating" and dispatch.variant_revision_id is None
    assert len(runs) == len(attempts) == 1
    assert runs[0].status == attempts[0].status == "running"
    assert revision_count == 0

    recovered_at = crashed_at + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover(release3_factory, recovered_at=recovered_at)
    _run_child(
        job_type="telegram.route.process",
        fault_point=None,
        observed_at=recovered_at,
        config=config,
        error_path=tmp_path / "telegram-process-retry.txt",
        expected_exit_code=0,
    )
    await _assert_succeeded(release3_factory, job_id)
    async with release3_factory() as session:
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        attempts = list(await session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number)))
        revision_count = await session.scalar(select(func.count()).select_from(PlatformVariantRevision))
    assert dispatch is not None and dispatch.variant_revision_id is not None
    assert [item.status for item in attempts] == ["failed", "completed"]
    assert revision_count == 1


async def test_export_hard_death_reuses_complete_manifest_without_duplicate_tree(
    app_harness,
    release3_factory,
    tmp_path: Path,
):
    researched = await app_harness.create_researched_story()
    requested = await app_harness.request_pack(
        researched.id,
        research_run_id=researched.research_run_id,
        platforms=["telegram"],
    )
    await app_harness.run_until_idle()
    pack = await app_harness.pack_for_job(requested["job_id"])
    revision = await app_harness.approve_exact_revision(pack["variants"][0]["current_revision"])
    accepted = await app_harness.request_export(
        pack["id"],
        revision_ids=[revision["id"]],
        formats=["json", "markdown"],
        include_media=False,
    )
    job_id = UUID(accepted["job_id"])
    config = _base_config(app_harness)
    crashed_at = datetime.now(UTC) + timedelta(seconds=1)
    _run_child(
        job_type="build_export",
        fault_point="export.after_manifest_before_commit",
        observed_at=crashed_at,
        config=config,
        error_path=tmp_path / "export-crash.txt",
    )
    export_dir = app_harness.export_root / str(job_id)
    manifest_path = export_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    recovered_at = crashed_at + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover(release3_factory, recovered_at=recovered_at)
    _run_child(
        job_type="build_export",
        fault_point=None,
        observed_at=recovered_at,
        config=config,
        error_path=tmp_path / "export-retry.txt",
        expected_exit_code=0,
    )
    succeeded = await _assert_succeeded(release3_factory, job_id)
    assert succeeded.result["state"] == "complete"
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == manifest_hash
    assert [path.name for path in app_harness.export_root.iterdir()] == [str(job_id)]


async def test_retention_hard_death_after_delete_replays_missing_paths_exactly_once(
    release3_factory,
    tmp_path: Path,
):
    media_root = tmp_path / "media"
    export_root = tmp_path / "exports"
    observed_at = datetime.now(UTC)
    async with release3_factory() as session:
        rows = await _seed_all_categories(session, media_root)
        service = RetentionService(session, clock=lambda: observed_at, media_root=media_root)
        preview = await service.preview()
        enqueued = await service.enqueue(
            preview_token=preview.preview_token,
            confirmation=RETENTION_CONFIRMATION,
        )
        job_id = enqueued.job.id
        run_id = enqueued.run.id
        media_file = Path(rows["media_file"])
        export_dir = Path(rows["export_dir"])
        await session.commit()

    crashed_at = observed_at + timedelta(seconds=1)
    config = {"export_root": str(export_root), "media_root": str(media_root)}
    _run_child(
        job_type="execute_retention",
        fault_point="retention.after_filesystem_delete_before_finalize",
        observed_at=crashed_at,
        config=config,
        error_path=tmp_path / "retention-crash.txt",
    )
    assert not media_file.exists()
    assert not export_dir.exists()
    async with release3_factory() as session:
        run = await session.get(RetentionRun, run_id)
        job = await session.get(WorkflowJob, job_id)
    assert run is not None and run.status == "running"
    assert job is not None and job.status == JobStatus.RUNNING

    recovered_at = crashed_at + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover(release3_factory, recovered_at=recovered_at)
    _run_child(
        job_type="execute_retention",
        fault_point=None,
        observed_at=recovered_at,
        config=config,
        error_path=tmp_path / "retention-retry.txt",
        expected_exit_code=0,
    )
    await _assert_succeeded(release3_factory, job_id)
    async with release3_factory() as session:
        run = await session.get(RetentionRun, run_id)
    assert run is not None and run.status == "succeeded"
    execution = run.count_snapshot["execution"]
    assert execution["filesystem_deleted"]["export_artifact"] == 1
    assert execution["filesystem_deleted"]["unreferenced_media"] == 1
    assert not media_file.exists() and not export_dir.exists()


def _ledger_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


@pytest.mark.parametrize(
    ("fault_point", "sent_count", "publication_before_recovery", "terminal_on_recovery"),
    (
        ("telegram.before_send", 0, 0, JobStatus.NEEDS_REVIEW),
        ("telegram.after_send_before_receipt", 1, 0, JobStatus.NEEDS_REVIEW),
        ("publication.after_receipt_before_commit", 1, 0, JobStatus.QUEUED),
        ("worker.after_handler_before_terminal", 1, 1, JobStatus.QUEUED),
    ),
)
async def test_publish_literal_death_never_resends_ambiguous_or_receipted_operation(
    release3_factory,
    tmp_path: Path,
    fault_point: str,
    sent_count: int,
    publication_before_recovery: int,
    terminal_on_recovery: JobStatus,
):
    publish_job_id = await _seed_publish_job(
        release3_factory,
        route_name=f"Literal-{fault_point}",
    )
    async with release3_factory() as session:
        publish_job = await session.get(PublishJob, publish_job_id)
        assert publish_job is not None
        workflow_job_id = publish_job.workflow_job_id
    ledger = tmp_path / "telegram-send-ledger.txt"
    config = {"telegram_ledger": str(ledger)}
    crashed_at = datetime.now(UTC) + timedelta(seconds=1)
    _run_child(
        job_type="telegram.publish",
        fault_point=fault_point,
        observed_at=crashed_at,
        config=config,
        error_path=tmp_path / "publish-crash.txt",
    )
    assert _ledger_count(ledger) == sent_count
    async with release3_factory() as session:
        publication_count = await session.scalar(
            select(func.count()).select_from(Publication).where(Publication.publish_job_id == publish_job_id)
        )
    assert publication_count == publication_before_recovery

    recovered_at = crashed_at + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover(release3_factory, recovered_at=recovered_at)
    async with release3_factory() as session:
        recovered = await session.get(WorkflowJob, workflow_job_id)
        receipt = await session.scalar(
            select(PublishOperationReceipt).where(PublishOperationReceipt.publish_job_id == publish_job_id)
        )
    assert recovered is not None and recovered.status == terminal_on_recovery

    if terminal_on_recovery == JobStatus.NEEDS_REVIEW:
        assert receipt is not None and receipt.status == "ambiguous"
        assert _ledger_count(ledger) == sent_count
        return

    _run_child(
        job_type="telegram.publish",
        fault_point=None,
        observed_at=recovered_at,
        config=config,
        error_path=tmp_path / "publish-retry.txt",
        expected_exit_code=0,
    )
    await _assert_succeeded(release3_factory, workflow_job_id)
    async with release3_factory() as session:
        publication_count = await session.scalar(
            select(func.count()).select_from(Publication).where(Publication.publish_job_id == publish_job_id)
        )
    assert publication_count == 1
    assert _ledger_count(ledger) == 1
