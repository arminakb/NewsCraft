#!/usr/bin/env python3
"""Create, verify, and explicitly restore local NewsCraft backups."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

BACKUP_SCHEMA = "newscraft-backup-v1"
MANIFEST_NAME = "manifest.json"
DATABASE_DUMP_NAME = "database.dump"
MEDIA_ARCHIVE_NAME = "media.tar.gz"
EXPORT_ARCHIVE_NAME = "exports.tar.gz"
RUNTIME_SERVICES = (
    "api",
    "worker-source-generation",
    "worker-publishing",
    "scheduler",
    "frontend",
)
STOP_COMMAND = ("docker", "compose", "stop", *RUNTIME_SERVICES)
START_COMMAND = ("docker", "compose", "start", *RUNTIME_SERVICES)
RECOVERY_COMMAND = "docker compose start " + " ".join(RUNTIME_SERVICES)
MAX_MANIFEST_BYTES = 1_000_000
MIN_CUSTOM_DUMP_HEADER_BYTES = 11
CHUNK_SIZE = 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")

MANIFEST_FIELDS = {
    "schema",
    "created_utc",
    "git_sha",
    "alembic_current",
    "alembic_head",
    "postgresql_version",
    "database_dump",
    "media_archive",
    "export_archive",
}
FILE_FIELDS = {"filename", "bytes", "sha256"}
FILE_RECORDS = {
    "database_dump": DATABASE_DUMP_NAME,
    "media_archive": MEDIA_ARCHIVE_NAME,
    "export_archive": EXPORT_ARCHIVE_NAME,
}


class BackupRestoreError(RuntimeError):
    """Raised when a backup or restore operation cannot complete."""


class BackupVerificationError(BackupRestoreError):
    """Raised when an archive does not satisfy the backup contract."""


class Runner(Protocol):
    """Runs commands while allowing binary stdin/stdout to remain streamed."""

    def run(
        self,
        command: Sequence[str],
        *,
        output_path: Path | None = None,
        input_path: Path | None = None,
    ) -> str: ...


class SubprocessRunner:
    """Production command runner."""

    def run(
        self,
        command: Sequence[str],
        *,
        output_path: Path | None = None,
        input_path: Path | None = None,
    ) -> str:
        stdin_handle = input_path.open("rb") if input_path is not None else None
        stdout_handle = output_path.open("wb") if output_path is not None else None
        try:
            result = subprocess.run(
                list(command),
                check=False,
                stdin=stdin_handle,
                stdout=stdout_handle if stdout_handle is not None else subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise BackupRestoreError(f"could not run command {command[0]!r}: {exc}") from exc
        finally:
            if stdin_handle is not None:
                stdin_handle.close()
            if stdout_handle is not None:
                stdout_handle.close()

        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            detail = f": {stderr[:4000]}" if stderr else ""
            raise BackupRestoreError(f"command failed with exit code {result.returncode} ({' '.join(command)}){detail}")
        if output_path is not None:
            return ""
        return (result.stdout or b"").decode("utf-8", errors="strict").strip()


class BackupRestore:
    """Implements the checksummed local backup and destructive restore workflow."""

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.now = now or (lambda: datetime.now(UTC))

    def backup(self, output_dir: Path | str) -> Path:
        destination = Path(output_dir)
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        created = self._created_utc()
        archive_name = f"newscraft-{created.strftime('%Y%m%dT%H%M%SZ')}.newscraft-backup.tar.gz"
        final_archive = destination / archive_name
        if final_archive.exists():
            raise BackupRestoreError(f"backup archive already exists: {final_archive}")

        staging_dir = Path(tempfile.mkdtemp(prefix=".newscraft-backup-", dir=destination))
        staging_dir.chmod(0o700)
        try:
            database_dump = staging_dir / DATABASE_DUMP_NAME
            media_archive = staging_dir / MEDIA_ARCHIVE_NAME
            export_archive = staging_dir / EXPORT_ARCHIVE_NAME

            self.runner.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "-U",
                    "newscraft",
                    "-d",
                    "newscraft",
                    "--format=custom",
                ],
                output_path=database_dump,
            )
            self.runner.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "tar",
                    "-C",
                    "/data/media",
                    "-czf",
                    "-",
                    ".",
                ],
                output_path=media_archive,
            )
            self.runner.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "api",
                    "tar",
                    "-C",
                    "/data/exports",
                    "-czf",
                    "-",
                    ".",
                ],
                output_path=export_archive,
            )

            manifest = {
                "schema": BACKUP_SCHEMA,
                "created_utc": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "git_sha": self._metadata(["git", "rev-parse", "HEAD"], "git SHA"),
                "alembic_current": self._metadata(
                    ["docker", "compose", "exec", "-T", "api", "alembic", "current"],
                    "Alembic current revision",
                ),
                "alembic_head": self._metadata(
                    ["docker", "compose", "exec", "-T", "api", "alembic", "heads"],
                    "Alembic head revision",
                ),
                "postgresql_version": self._metadata(
                    [
                        "docker",
                        "compose",
                        "exec",
                        "-T",
                        "postgres",
                        "psql",
                        "-U",
                        "newscraft",
                        "-d",
                        "newscraft",
                        "-Atqc",
                        "SHOW server_version;",
                    ],
                    "PostgreSQL version",
                ),
                "database_dump": self._file_record(database_dump),
                "media_archive": self._file_record(media_archive),
                "export_archive": self._file_record(export_archive),
            }
            manifest_path = staging_dir / MANIFEST_NAME
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path.chmod(0o600)

            temporary_archive = staging_dir / ".archive.tmp"
            with tarfile.open(temporary_archive, mode="w:gz") as archive:
                for path in (
                    manifest_path,
                    database_dump,
                    media_archive,
                    export_archive,
                ):
                    archive.add(path, arcname=path.name, recursive=False)
            temporary_archive.chmod(0o600)

            verification_dir = staging_dir / ".verification"
            verification_dir.mkdir(mode=0o700)
            self._verify_and_stage(temporary_archive, verification_dir)
            shutil.rmtree(verification_dir)

            self._publish_archive(temporary_archive, final_archive)
            return final_archive
        except BackupRestoreError, BackupVerificationError:
            raise
        except (OSError, tarfile.TarError, UnicodeError, ValueError) as exc:
            raise BackupRestoreError(f"backup failed: {exc}") from exc
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def verify(self, archive_path: Path | str) -> dict[str, Any]:
        archive = Path(archive_path)
        with tempfile.TemporaryDirectory(prefix="newscraft-backup-verify-") as raw_dir:
            staging_dir = Path(raw_dir)
            staging_dir.chmod(0o700)
            return self._verify_and_stage(archive, staging_dir)

    def restore(
        self,
        archive_path: Path | str,
        *,
        confirm_replace: bool = False,
    ) -> dict[str, Any]:
        if not confirm_replace:
            raise BackupRestoreError("restore requires --confirm-replace")

        archive = Path(archive_path)
        with tempfile.TemporaryDirectory(prefix="newscraft-backup-restore-") as raw_dir:
            staging_dir = Path(raw_dir)
            staging_dir.chmod(0o700)
            manifest = self._verify_and_stage(archive, staging_dir)

            self.runner.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "--list",
                ],
                input_path=staging_dir / DATABASE_DUMP_NAME,
            )

            stop_attempted = False
            try:
                stop_attempted = True
                self.runner.run(STOP_COMMAND)
                self.runner.run(
                    [
                        "docker",
                        "compose",
                        "exec",
                        "-T",
                        "postgres",
                        "psql",
                        "-U",
                        "newscraft",
                        "-d",
                        "postgres",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-c",
                        "DROP DATABASE IF EXISTS newscraft WITH (FORCE);",
                    ]
                )
                self.runner.run(
                    [
                        "docker",
                        "compose",
                        "exec",
                        "-T",
                        "postgres",
                        "psql",
                        "-U",
                        "newscraft",
                        "-d",
                        "postgres",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-c",
                        "CREATE DATABASE newscraft OWNER newscraft;",
                    ]
                )
                self.runner.run(
                    [
                        "docker",
                        "compose",
                        "exec",
                        "-T",
                        "postgres",
                        "pg_restore",
                        "--exit-on-error",
                        "-U",
                        "newscraft",
                        "-d",
                        "newscraft",
                    ],
                    input_path=staging_dir / DATABASE_DUMP_NAME,
                )
                self._replace_volume(
                    "/data/media",
                    staging_dir / MEDIA_ARCHIVE_NAME,
                )
                self._replace_volume(
                    "/data/exports",
                    staging_dir / EXPORT_ARCHIVE_NAME,
                )
                self.runner.run(
                    [
                        "docker",
                        "compose",
                        "run",
                        "--rm",
                        "--no-deps",
                        "api",
                        "alembic",
                        "upgrade",
                        "head",
                    ]
                )
                self.runner.run(START_COMMAND)
            except BaseException:
                if stop_attempted:
                    stopped_confirmed = self._contain_runtime_services()
                    if stopped_confirmed:
                        print(
                            "Restore failed; all runtime services remain stopped.",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            "Restore failed; runtime service stop state could not be confirmed.",
                            file=sys.stderr,
                        )
                    print(f"Recovery command: {RECOVERY_COMMAND}", file=sys.stderr)
                raise
            return manifest

    def _contain_runtime_services(self) -> bool:
        try:
            self.runner.run(STOP_COMMAND)
            return True
        except BaseException as stop_error:
            print(
                f"WARNING: could not confirm stopped services: {stop_error}",
                file=sys.stderr,
            )

        stopped = True
        for service in RUNTIME_SERVICES:
            try:
                self.runner.run(("docker", "compose", "stop", service))
            except BaseException as stop_error:
                stopped = False
                print(
                    f"WARNING: could not confirm {service} is stopped: {stop_error}",
                    file=sys.stderr,
                )
        return stopped

    def _replace_volume(self, root: str, archive_path: Path) -> None:
        script = 'root="$1"; find "$root" -mindepth 1 -maxdepth 1 -exec rm -rf -- "{}" +; tar -C "$root" -xzf -'
        self.runner.run(
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "api",
                "sh",
                "-ceu",
                script,
                "restore-volume",
                root,
            ],
            input_path=archive_path,
        )

    def _created_utc(self) -> datetime:
        value = self.now()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(microsecond=0)

    def _metadata(self, command: Sequence[str], label: str) -> str:
        value = self.runner.run(command).strip()
        if not value:
            raise BackupRestoreError(f"{label} command returned an empty value")
        return value

    @staticmethod
    def _file_record(path: Path) -> dict[str, str | int]:
        return {
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }

    @staticmethod
    def _sync_file(path: Path) -> None:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())

    @staticmethod
    def _sync_directory(path: Path) -> None:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @classmethod
    def _sync_file_and_directory(cls, path: Path) -> None:
        cls._sync_file(path)
        cls._sync_directory(path.parent)

    def _publish_archive(self, temporary_archive: Path, final_archive: Path) -> None:
        published = False
        try:
            self._sync_file(temporary_archive)
            os.link(temporary_archive, final_archive)
            published = True
            self._sync_directory(final_archive.parent)
        except FileExistsError as exc:
            raise BackupRestoreError(f"backup archive already exists: {final_archive}") from exc
        except BaseException:
            if published:
                try:
                    final_archive.unlink(missing_ok=True)
                    self._sync_directory(final_archive.parent)
                except BaseException:
                    pass
            raise

    def _verify_and_stage(
        self,
        archive_path: Path,
        staging_dir: Path,
    ) -> dict[str, Any]:
        if not archive_path.is_file():
            raise BackupVerificationError(f"backup archive does not exist: {archive_path}")
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                members = archive.getmembers()
                member_by_name: dict[str, tarfile.TarInfo] = {}
                for member in members:
                    _validate_outer_member(member)
                    if member.name in member_by_name:
                        raise BackupVerificationError(f"duplicate archive member: {member.name}")
                    member_by_name[member.name] = member

                manifest_member = member_by_name.get(MANIFEST_NAME)
                if manifest_member is None:
                    raise BackupVerificationError("missing archive member: manifest.json")
                if manifest_member.size > MAX_MANIFEST_BYTES:
                    raise BackupVerificationError("manifest.json is too large")
                manifest_stream = archive.extractfile(manifest_member)
                if manifest_stream is None:
                    raise BackupVerificationError("could not read manifest.json")
                try:
                    manifest = json.loads(manifest_stream.read().decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise BackupVerificationError(f"invalid manifest JSON: {exc}") from exc

                records = _validate_manifest(manifest)
                expected_members = {MANIFEST_NAME, *records}
                actual_members = set(member_by_name)
                missing = expected_members - actual_members
                if missing:
                    raise BackupVerificationError(f"missing archive member: {sorted(missing)[0]}")
                unexpected = actual_members - expected_members
                if unexpected:
                    raise BackupVerificationError(f"unexpected archive member: {sorted(unexpected)[0]}")

                for filename, record in records.items():
                    member = member_by_name[filename]
                    output_path = staging_dir / filename
                    source = archive.extractfile(member)
                    if source is None:
                        raise BackupVerificationError(f"could not read archive member: {filename}")
                    digest = hashlib.sha256()
                    byte_count = 0
                    with output_path.open("xb") as output:
                        output_path.chmod(0o600)
                        while chunk := source.read(CHUNK_SIZE):
                            output.write(chunk)
                            digest.update(chunk)
                            byte_count += len(chunk)

                    if byte_count != record["bytes"]:
                        raise BackupVerificationError(
                            f"size mismatch for {filename}: expected {record['bytes']}, got {byte_count}"
                        )
                    actual_sha = digest.hexdigest()
                    if actual_sha != record["sha256"]:
                        raise BackupVerificationError(
                            f"checksum mismatch for {filename}: expected {record['sha256']}, got {actual_sha}"
                        )

                _validate_nested_archive(
                    staging_dir / MEDIA_ARCHIVE_NAME,
                    MEDIA_ARCHIVE_NAME,
                )
                _validate_nested_archive(
                    staging_dir / EXPORT_ARCHIVE_NAME,
                    EXPORT_ARCHIVE_NAME,
                )
                _validate_database_dump(staging_dir / DATABASE_DUMP_NAME)
                return manifest
        except BackupVerificationError:
            raise
        except (OSError, tarfile.TarError, EOFError) as exc:
            raise BackupVerificationError(f"invalid backup archive: {exc}") from exc


def _validate_outer_member(member: tarfile.TarInfo) -> None:
    _validate_member_path(member.name)
    if member.issym() or member.islnk():
        raise BackupVerificationError(f"archive link is not allowed: {member.name}")
    if not member.isfile():
        raise BackupVerificationError(f"archive member must be a regular file: {member.name}")


def _validate_member_path(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or name.startswith("/"):
        raise BackupVerificationError(f"absolute archive member path: {name}")
    if ".." in path.parts:
        raise BackupVerificationError(f"archive member path traversal: {name}")
    parts = [part for part in path.parts if part not in {"", "."}]
    return "/".join(parts) or "."


def _validate_nested_archive(path: Path, label: str) -> None:
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            member_types: dict[str, bool] = {}
            for member in archive.getmembers():
                try:
                    normalized = _validate_member_path(member.name)
                except BackupVerificationError as exc:
                    raise BackupVerificationError(f"{label}: {exc}") from exc
                if normalized in member_types:
                    raise BackupVerificationError(f"{label}: duplicate archive member: {member.name}")
                if member.issym() or member.islnk():
                    raise BackupVerificationError(f"{label}: archive link is not allowed: {member.name}")
                if not (member.isfile() or member.isdir()):
                    raise BackupVerificationError(f"{label}: unsupported archive member type: {member.name}")
                directory_only_name = member.name.endswith("/") or member.name.rstrip("/").endswith("/.")
                if directory_only_name and not member.isdir():
                    raise BackupVerificationError(f"{label}: directory path is not a directory: {member.name}")
                if normalized == "." and not member.isdir():
                    raise BackupVerificationError(f"{label}: root member must be a directory")
                member_types[normalized] = member.isdir()

            if member_types.get(".") is not True:
                raise BackupVerificationError(f"{label}: root directory member is missing")
            for normalized in member_types:
                if normalized == ".":
                    continue
                parts = PurePosixPath(normalized).parts
                for length in range(1, len(parts)):
                    ancestor = "/".join(parts[:length])
                    if ancestor in member_types and not member_types[ancestor]:
                        raise BackupVerificationError(
                            f"{label}: non-directory ancestor {ancestor!r} blocks {normalized!r}"
                        )
    except BackupVerificationError:
        raise
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise BackupVerificationError(f"{label} is not a valid gzip tar archive: {exc}") from exc


def _validate_database_dump(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            header = handle.read(MIN_CUSTOM_DUMP_HEADER_BYTES)
    except OSError as exc:
        raise BackupVerificationError(f"could not read {DATABASE_DUMP_NAME}: {exc}") from exc
    if len(header) < MIN_CUSTOM_DUMP_HEADER_BYTES or not header.startswith(b"PGDMP"):
        raise BackupVerificationError(f"{DATABASE_DUMP_NAME} is not a PostgreSQL custom-format dump")


def _validate_manifest(manifest: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(manifest, dict):
        raise BackupVerificationError("manifest must be a JSON object")
    if manifest.get("schema") != BACKUP_SCHEMA:
        raise BackupVerificationError(f"wrong schema: expected {BACKUP_SCHEMA!r}, got {manifest.get('schema')!r}")
    if set(manifest) != MANIFEST_FIELDS:
        missing = sorted(MANIFEST_FIELDS - set(manifest))
        extra = sorted(set(manifest) - MANIFEST_FIELDS)
        raise BackupVerificationError(f"manifest fields do not match schema (missing={missing}, extra={extra})")

    for field in (
        "created_utc",
        "git_sha",
        "alembic_current",
        "alembic_head",
        "postgresql_version",
    ):
        if not isinstance(manifest[field], str) or not manifest[field]:
            raise BackupVerificationError(f"manifest field {field!r} must be non-empty")
    try:
        datetime.strptime(manifest["created_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise BackupVerificationError("manifest created_utc must be UTC") from exc
    if not GIT_SHA_PATTERN.fullmatch(manifest["git_sha"]):
        raise BackupVerificationError("manifest git_sha is invalid")

    records: dict[str, dict[str, Any]] = {}
    for field, required_filename in FILE_RECORDS.items():
        record = manifest[field]
        if not isinstance(record, dict) or set(record) != FILE_FIELDS:
            raise BackupVerificationError(f"manifest file record {field!r} does not match schema")
        if record.get("filename") != required_filename:
            raise BackupVerificationError(f"manifest filename for {field!r} must be {required_filename!r}")
        size = record.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise BackupVerificationError(f"manifest byte count for {required_filename} is invalid")
        sha256 = record.get("sha256")
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            raise BackupVerificationError(f"manifest checksum for {required_filename} is invalid")
        records[required_filename] = record
    return records


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create, verify, or explicitly restore a local NewsCraft backup.",
        epilog=("Restore is destructive and requires: restore ARCHIVE --confirm-replace"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="create and verify an archive")
    backup_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backups"),
        help="directory for the final atomic archive (default: backups)",
    )

    verify_parser = subparsers.add_parser("verify", help="verify an archive without restoring")
    verify_parser.add_argument("archive", type=Path)

    restore_parser = subparsers.add_parser(
        "restore",
        help="destructively replace the database, media, and exports",
    )
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument(
        "--confirm-replace",
        action="store_true",
        help="confirm destructive replacement of current local data",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workflow = BackupRestore()
    if args.command == "backup":
        archive = workflow.backup(args.output_dir)
        print(f"Backup created and verified: {archive}")
        return 0
    if args.command == "verify":
        workflow.verify(args.archive)
        print(f"Backup verified: {args.archive}")
        return 0
    if not args.confirm_replace:
        raise SystemExit("restore requires --confirm-replace")
    workflow.restore(args.archive, confirm_replace=True)
    print(f"Restore completed and services restarted: {args.archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BackupRestoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
