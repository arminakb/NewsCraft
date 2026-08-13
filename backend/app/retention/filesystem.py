from __future__ import annotations

import asyncio
import os
import shutil
import stat
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.faults import FaultInjector, NoopFaultInjector
from app.db.models import MediaAsset
from app.retention.contracts import (
    RETENTION_CATEGORIES,
    RetentionConflict,
    RetentionNotFound,
    _snapshot_intents,
)
from app.retention.models import RetentionRun


class _UnsafeStoragePath(ValueError):
    pass


def _owned_root(value: Path) -> tuple[Path, Path]:
    root = Path(value).absolute()
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise _UnsafeStoragePath("storage root contains a symlink")
        if current.exists() and not current.is_dir():
            raise _UnsafeStoragePath("storage root contains a non-directory component")
    try:
        resolved = root.resolve(strict=False)
    except OSError as exc:
        raise _UnsafeStoragePath("storage root cannot be resolved safely") from exc
    return root, resolved


def _export_relative_path(export_root: Path, export_id: UUID) -> str:
    root, resolved_root = _owned_root(export_root)
    target = root / str(export_id)
    if target.is_symlink():
        raise _UnsafeStoragePath("export directory is a symlink")
    if target.exists():
        if not target.is_dir():
            raise _UnsafeStoragePath("export path is not a directory")
        try:
            resolved = target.resolve(strict=True)
        except OSError as exc:
            raise _UnsafeStoragePath("export directory cannot be resolved safely") from exc
        if not resolved.is_relative_to(resolved_root):
            raise _UnsafeStoragePath("export directory escapes the owned root")
    return str(export_id)


def _media_relative_path(media_root: Path, stored_path: str) -> str:
    root, resolved_root = _owned_root(media_root)
    stored = Path(stored_path)
    candidate = stored if stored.is_absolute() else root / stored
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise _UnsafeStoragePath("media path escapes the owned root") from None
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        if current.is_symlink():
            raise _UnsafeStoragePath("media path contains a symlink")
        if current.exists() and index < len(relative.parts) - 1 and not current.is_dir():
            raise _UnsafeStoragePath("media path contains a non-directory component")
    if candidate.exists():
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise _UnsafeStoragePath("media file cannot be resolved safely") from exc
        if not resolved.is_relative_to(resolved_root) or not stat.S_ISREG(resolved.stat().st_mode):
            raise _UnsafeStoragePath("media path is not a regular file under the owned root")
        return resolved.relative_to(resolved_root).as_posix()
    normalized = Path(os.path.normpath(str(candidate)))
    try:
        normalized_relative = normalized.relative_to(root)
    except ValueError:
        raise _UnsafeStoragePath("missing media path escapes the owned root") from None
    return normalized_relative.as_posix()


def _media_claim_identity(media_root: Path, stored_path: str) -> str:
    """Resolve a retained path for protection only; deletion uses stricter no-follow rules."""
    root, resolved_root = _owned_root(media_root)
    stored = Path(stored_path)
    candidate = stored if stored.is_absolute() else root / stored
    candidate = candidate.absolute()
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise _UnsafeStoragePath("media claim cannot be resolved safely") from exc
    if not resolved.is_relative_to(resolved_root):
        raise _UnsafeStoragePath("media claim escapes the owned root")
    if resolved.exists() and not stat.S_ISREG(resolved.stat().st_mode):
        raise _UnsafeStoragePath("media claim does not resolve to a regular file")
    return resolved.relative_to(resolved_root).as_posix()


def _claimed_media_identities(media_root: Path, stored_paths: list[str]) -> tuple[set[str], bool]:
    """Classify stored media paths into canonical claim identities.

    Purely synchronous (many blocking path syscalls), so callers on an event loop
    must hand the whole batch to a worker thread instead of walking row by row.
    """
    identities: set[str] = set()
    unclassifiable = False
    for stored_path in stored_paths:
        try:
            identities.add(_media_claim_identity(media_root, stored_path))
        except _UnsafeStoragePath:
            unclassifiable = True
    return identities, unclassifiable


def _delete_relative_owned(root_value: Path, relative_path: str, *, directory: bool) -> None:
    relative = PurePosixPath(relative_path)
    if (
        not relative_path
        or relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or "\\" in relative_path
    ):
        raise _UnsafeStoragePath("cleanup path is not a safe relative identity")
    root = Path(root_value).absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptors: list[int] = []
    try:
        current_fd = os.open(root.anchor, flags)
        descriptors.append(current_fd)
        for part in root.parts[1:]:
            try:
                current_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                return
            descriptors.append(current_fd)
        for part in relative.parts[:-1]:
            try:
                current_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                return
            descriptors.append(current_fd)
        name = relative.parts[-1]
        try:
            metadata = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if directory:
            if not stat.S_ISDIR(metadata.st_mode):
                raise _UnsafeStoragePath("cleanup target is not a directory")
            shutil.rmtree(name, dir_fd=current_fd)
        else:
            if not stat.S_ISREG(metadata.st_mode):
                raise _UnsafeStoragePath("cleanup target is not a regular file")
            os.unlink(name, dir_fd=current_fd)
    except OSError as exc:
        raise _UnsafeStoragePath("cleanup target could not be traversed without symlinks") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


async def finish_filesystem_phase(
    session: AsyncSession,
    run_id: UUID,
    *,
    export_root: Path,
    media_root: Path,
    now: Callable[[], datetime],
    execution_counts: Callable[[RetentionRun], dict[str, object]],
    referenced_media_ids: Callable[[], Awaitable[set[UUID]]],
    fault_injector: FaultInjector | None = None,
) -> RetentionRun:
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()
    run = await session.scalar(select(RetentionRun).where(RetentionRun.id == run_id).with_for_update())
    if run is None:
        raise RetentionNotFound(f"retention run {run_id} was not found")
    if run.status == "succeeded":
        return run
    if run.status not in {"running", "partial"}:
        raise RetentionConflict(f"retention filesystem cleanup cannot run from status {run.status!r}")
    counts = execution_counts(run)
    errors = [error for error in run.error_snapshot if error.get("phase") != "filesystem"]
    execution = counts["execution"]
    if not isinstance(execution, dict):
        raise RetentionConflict("retention execution count snapshot is invalid")
    deleted_counts = execution["filesystem_deleted"]
    if not isinstance(deleted_counts, dict):
        raise RetentionConflict("retention filesystem count snapshot is invalid")
    for category in RETENTION_CATEGORIES:
        deleted_counts[category] = 0
    database_skipped = execution.get("database_skipped", execution["skipped"])
    if not isinstance(database_skipped, dict):
        raise RetentionConflict("retention database skip snapshot is invalid")
    filesystem_skipped = execution.get("filesystem_skipped")
    if not isinstance(filesystem_skipped, dict):
        filesystem_skipped = {category: 0 for category in RETENTION_CATEGORIES}
        execution["filesystem_skipped"] = filesystem_skipped
    execution["skipped"] = dict(database_skipped)
    for category in RETENTION_CATEGORIES:
        filesystem_skipped[category] = 0
    intents = _snapshot_intents(run)
    reclaimed_media_paths: set[str] = set()
    reclaimed_media_ids: set[UUID] = set()
    unclassifiable_media_claim = False
    claimed_storage_paths: list[str] = []
    if any(intent.category == "unreferenced_media" for intent in intents):
        await session.execute(
            text(
                "LOCK TABLE content_items, item_media, media_assets, "
                "platform_variant_revisions, workflow_jobs IN SHARE MODE"
            )
        )
        reclaimed_media_ids = await referenced_media_ids()
        claimed_media = await session.scalars(select(MediaAsset).where(MediaAsset.storage_path.is_not(None)))
        claimed_storage_paths = [str(media.storage_path) for media in claimed_media]
    # The SHARE lock above only has to cover the protection *read*. Committing here
    # releases it (and the run row lock) before any blocking filesystem work runs, so
    # ingestion/generation/publishing writers are never stalled by a deletion pass.
    await session.commit()
    if claimed_storage_paths:
        reclaimed_media_paths, unclassifiable_media_claim = await asyncio.to_thread(
            _claimed_media_identities, media_root, claimed_storage_paths
        )
    media_record_ids_by_path: dict[str, set[UUID]] = {}
    for intent in intents:
        if intent.category == "unreferenced_media":
            media_record_ids_by_path.setdefault(intent.relative_path, set()).add(intent.record_id)
    seen: set[tuple[str, str]] = set()
    for intent in intents:
        identity = (intent.category, intent.relative_path)
        if identity in seen:
            continue
        seen.add(identity)
        root = export_root if intent.category == "export_artifact" else media_root
        if intent.category == "unreferenced_media" and (
            unclassifiable_media_claim
            or not media_record_ids_by_path[intent.relative_path].isdisjoint(reclaimed_media_ids)
            or intent.relative_path in reclaimed_media_paths
        ):
            filesystem_skipped[intent.category] = int(filesystem_skipped.get(intent.category, 0)) + 1
            skipped = execution["skipped"]
            if isinstance(skipped, dict):
                skipped[intent.category] = int(skipped.get(intent.category, 0)) + 1
            continue
        try:
            await asyncio.to_thread(
                _delete_relative_owned,
                root,
                intent.relative_path,
                directory=intent.operation == "delete_tree",
            )
            deleted_counts[intent.category] = int(deleted_counts.get(intent.category, 0)) + 1
        except OSError, _UnsafeStoragePath:
            errors.append(
                {
                    "phase": "filesystem",
                    "category": intent.category,
                    "record_type": ("workflow_job" if intent.category == "export_artifact" else "media_asset"),
                    "record_id": str(intent.record_id),
                    "code": "unsafe_or_failed_cleanup",
                    "message": "Persisted cleanup identity could not be removed safely",
                }
            )
    await injector.hit(
        "retention.after_filesystem_delete_before_finalize",
        {
            "retention_run_id": str(run_id),
            "cleanup_intent_count": len(intents),
        },
    )
    # Second, short transaction: re-take the run row and persist the outcome. The
    # first transaction was committed before the deletion pass, so `run` may be
    # expired here.
    run = await session.scalar(select(RetentionRun).where(RetentionRun.id == run_id).with_for_update())
    if run is None:  # pragma: no cover - the run row is protected by its own FKs
        raise RetentionNotFound(f"retention run {run_id} was not found")
    run.count_snapshot = counts
    run.error_snapshot = errors
    # Only filesystem-phase findings can be retried by re-running this phase.
    # Database-phase findings stay visible in the snapshot but must not pin the
    # run at "partial", which would make the workflow job retry forever.
    run.status = "partial" if any(error.get("phase") == "filesystem" for error in errors) else "succeeded"
    run.finished_at = now()
    await session.flush()
    await session.commit()
    return run
