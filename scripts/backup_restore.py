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

BACKUP_SCHEMA = "newscraft-backup-v2"
LEGACY_BACKUP_SCHEMA = "newscraft-backup-v1"
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
WRITER_SERVICES = (
    "api",
    "worker-source-generation",
    "worker-publishing",
    "scheduler",
)
STOP_COMMAND = ("docker", "compose", "stop", *RUNTIME_SERVICES)
START_COMMAND = (
    "docker",
    "compose",
    "up",
    "-d",
    "--no-deps",
    *RUNTIME_SERVICES,
)
RECOVERY_COMMAND = "docker compose up -d --no-deps " + " ".join(RUNTIME_SERVICES)
MAX_MANIFEST_BYTES = 1_000_000
MIN_CUSTOM_DUMP_HEADER_BYTES = 11
CHUNK_SIZE = 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")

LEGACY_MANIFEST_FIELDS = {
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
MANIFEST_FIELDS = {
    "schema",
    "backup_id",
    "created_utc",
    "git_sha",
    "alembic_current",
    "alembic_head",
    "postgresql_version",
    "postgresql_major",
    "pg_dump_version",
    "pg_dump_major",
    "database_inventory",
    "container_image_ids",
    "consistency",
    "database_dump",
    "media_archive",
    "export_archive",
    "media_inventory",
    "export_inventory",
}
FILE_FIELDS = {"filename", "bytes", "sha256"}
INVENTORY_FIELDS = {"entries", "files", "bytes", "root_sha256"}
CONSISTENCY_FIELDS = {"mode", "quiesce_started_utc", "quiesce_completed_utc"}
DATABASE_INVENTORY_FIELDS = {"tables", "root_sha256"}
DATABASE_TABLE_RECORD_FIELDS = {"rows", "content_md5"}
DATABASE_INVENTORY_SQL = r"""
CREATE TEMP TABLE backup_inventory(table_name text PRIMARY KEY, row_count bigint NOT NULL, content_md5 text NOT NULL);
DO $inventory$
DECLARE item record; counted bigint; hashed text;
BEGIN
  FOR item IN
    SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY schemaname, tablename
  LOOP
    EXECUTE format(
      'SELECT count(*), md5(COALESCE(string_agg(row_hash, '''' ORDER BY row_hash), '''')) '
      'FROM (SELECT md5(row_to_json(source_row)::text) AS row_hash FROM %I.%I AS source_row) AS hashes',
      item.schemaname, item.tablename
    ) INTO counted, hashed;
    INSERT INTO backup_inventory VALUES (item.schemaname || '.' || item.tablename, counted, hashed);
  END LOOP;
END
$inventory$;
SELECT jsonb_object_agg(table_name, jsonb_build_object('rows', row_count, 'content_md5', content_md5))
FROM backup_inventory;
""".strip()
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
    """Implements encrypted, checksummed backup and explicit restore workflows."""

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.now = now or (lambda: datetime.now(UTC))

    def backup(
        self,
        output_dir: Path | str,
        *,
        recipient_file: Path | str,
        identity_file: Path | str,
        staging_root: Path | str,
    ) -> Path:
        destination = Path(output_dir)
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_staging_root = Path(staging_root)
        if not private_staging_root.is_dir():
            raise BackupRestoreError(f"private staging directory does not exist: {private_staging_root}")
        if private_staging_root.stat().st_mode & 0o077:
            raise BackupRestoreError(f"private staging directory must be mode 0700: {private_staging_root}")
        recipient = self._private_input_file(recipient_file, "age recipient file")
        identity = self._private_input_file(identity_file, "age identity file")
        created = self._created_utc()
        archive_name = f"newscraft-{created.strftime('%Y%m%dT%H%M%SZ')}.newscraft-backup.tar.gz.age"
        final_archive = destination / archive_name
        if final_archive.exists():
            raise BackupRestoreError(f"backup archive already exists: {final_archive}")

        staging_dir = Path(tempfile.mkdtemp(prefix="newscraft-backup-", dir=private_staging_root))
        staging_dir.chmod(0o700)
        stopped_services: tuple[str, ...] = ()
        services_resumed = False
        try:
            git_sha = self._metadata(["git", "rev-parse", "HEAD"], "git SHA")
            self.runner.run(["docker", "compose", "--profile", "operations", "build", "backup"])
            image_ids = sorted(
                set(
                    self._metadata(
                        ["docker", "compose", "--profile", "operations", "images", "--quiet"],
                        "container image IDs",
                    ).splitlines()
                )
            )
            running = set(self._running_runtime_services())
            stopped_services = tuple(service for service in WRITER_SERVICES if service in running)
            quiesce_started = self._created_utc()
            if stopped_services:
                self.runner.run(("docker", "compose", "stop", *stopped_services))
            self._assert_no_writer_sessions()

            database_dump = staging_dir / DATABASE_DUMP_NAME
            media_archive = staging_dir / MEDIA_ARCHIVE_NAME
            export_archive = staging_dir / EXPORT_ARCHIVE_NAME
            backup_run = [
                "docker",
                "compose",
                "--profile",
                "operations",
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "backup",
            ]
            self.runner.run([*backup_run, "pg_dump", "--format=custom"], output_path=database_dump)
            self.runner.run(
                [*backup_run, "tar", "-C", "/data/media", "-czf", "-", "."],
                output_path=media_archive,
            )
            self.runner.run(
                [*backup_run, "tar", "-C", "/data/exports", "-czf", "-", "."],
                output_path=export_archive,
            )

            postgresql_version = self._metadata(
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
            )
            pg_dump_version = self._metadata([*backup_run, "pg_dump", "--version"], "pg_dump version")
            alembic_current = self._metadata(
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "--no-deps",
                    "migrate",
                    "alembic",
                    "current",
                ],
                "Alembic current revision",
            )
            alembic_head = self._metadata(
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "--no-deps",
                    "migrate",
                    "alembic",
                    "heads",
                ],
                "Alembic head revision",
            )
            database_inventory = self._capture_database_inventory()
            quiesce_completed = self._created_utc()
            manifest = {
                "schema": BACKUP_SCHEMA,
                "backup_id": f"newscraft-{created.strftime('%Y%m%dT%H%M%SZ')}-{git_sha[:12]}",
                "created_utc": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "git_sha": git_sha,
                "alembic_current": alembic_current,
                "alembic_head": alembic_head,
                "postgresql_version": postgresql_version,
                "postgresql_major": _major_version(postgresql_version, "PostgreSQL server"),
                "pg_dump_version": pg_dump_version,
                "pg_dump_major": _major_version(pg_dump_version, "pg_dump"),
                "database_inventory": database_inventory,
                "container_image_ids": image_ids,
                "consistency": {
                    "mode": "quiesced",
                    "quiesce_started_utc": quiesce_started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "quiesce_completed_utc": quiesce_completed.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                "database_dump": self._file_record(database_dump),
                "media_archive": self._file_record(media_archive),
                "export_archive": self._file_record(export_archive),
                "media_inventory": _inventory_nested_archive(media_archive),
                "export_inventory": _inventory_nested_archive(export_archive),
            }
            manifest_path = staging_dir / MANIFEST_NAME
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            manifest_path.chmod(0o600)

            plaintext_archive = staging_dir / ".archive.tar.gz.tmp"
            with tarfile.open(plaintext_archive, mode="w:gz") as archive:
                for path in (
                    manifest_path,
                    database_dump,
                    media_archive,
                    export_archive,
                ):
                    archive.add(path, arcname=path.name, recursive=False)
            plaintext_archive.chmod(0o600)

            plaintext_verification = staging_dir / ".plaintext-verification"
            plaintext_verification.mkdir(mode=0o700)
            self._verify_and_stage(plaintext_archive, plaintext_verification)
            shutil.rmtree(plaintext_verification)

            encrypted_archive = staging_dir / ".archive.age.tmp"
            self._age_encrypt(plaintext_archive, encrypted_archive, recipient)
            encrypted_archive.chmod(0o600)
            encrypted_verification = staging_dir / ".encrypted-verification"
            encrypted_verification.mkdir(mode=0o700)
            decrypted_archive = encrypted_verification / "archive.tar.gz"
            self._age_decrypt(encrypted_archive, decrypted_archive, identity)
            payload_verification = encrypted_verification / "payload"
            payload_verification.mkdir(mode=0o700)
            self._verify_and_stage(decrypted_archive, payload_verification)
            shutil.rmtree(encrypted_verification)

            if stopped_services:
                self.runner.run(("docker", "compose", "up", "-d", "--no-deps", *stopped_services))
            services_resumed = True
            self._publish_archive(encrypted_archive, final_archive)
            return final_archive
        except BackupRestoreError, BackupVerificationError:
            raise
        except (OSError, tarfile.TarError, UnicodeError, ValueError) as exc:
            raise BackupRestoreError(f"backup failed: {exc}") from exc
        finally:
            if stopped_services and not services_resumed:
                try:
                    self.runner.run(
                        (
                            "docker",
                            "compose",
                            "up",
                            "-d",
                            "--no-deps",
                            *stopped_services,
                        )
                    )
                except BaseException as resume_error:
                    print(
                        f"WARNING: could not resume quiesced services: {resume_error}",
                        file=sys.stderr,
                    )
            shutil.rmtree(staging_dir, ignore_errors=True)

    def verify(
        self,
        archive_path: Path | str,
        *,
        identity_file: Path | str | None = None,
    ) -> dict[str, Any]:
        archive = Path(archive_path)
        with tempfile.TemporaryDirectory(prefix="newscraft-backup-verify-") as raw_dir:
            staging_dir = Path(raw_dir)
            staging_dir.chmod(0o700)
            if archive.name.endswith(".age"):
                if identity_file is None:
                    raise BackupVerificationError("encrypted backup verification requires --identity-file")
                identity = self._private_input_file(identity_file, "age identity file")
                decrypted = staging_dir / "archive.tar.gz"
                self._age_decrypt(archive, decrypted, identity)
                payload_dir = staging_dir / "payload"
                payload_dir.mkdir(mode=0o700)
                return self._verify_and_stage(decrypted, payload_dir)
            return self._verify_and_stage(archive, staging_dir)

    def prune(
        self,
        output_dir: Path | str,
        *,
        identity_file: Path | str,
        apply: bool = False,
    ) -> dict[str, list[str]]:
        directory = Path(output_dir)
        if not directory.is_dir():
            raise BackupRestoreError(f"backup directory does not exist: {directory}")
        identity = self._private_input_file(identity_file, "age identity file")
        verified: list[tuple[datetime, Path, str]] = []
        invalid: list[str] = []
        for archive in sorted(directory.glob("*.newscraft-backup.tar.gz.age")):
            try:
                manifest = self.verify(archive, identity_file=identity)
                created = datetime.strptime(manifest["created_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                verified.append((created, archive, _sha256(archive)))
            except BackupRestoreError:
                invalid.append(archive.name)
        verified.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        if not verified:
            raise BackupRestoreError("no verified encrypted backups are available; refusing retention")

        keep: set[Path] = {verified[0][1]}
        for key, generation_count in (
            (lambda value: value.date(), 7),
            (lambda value: value.isocalendar()[:2], 5),
            (lambda value: (value.year, value.month), 12),
        ):
            seen: set[object] = set()
            for created, archive, _digest in verified:
                generation = key(created)
                if generation in seen:
                    continue
                if len(seen) >= generation_count:
                    break
                seen.add(generation)
                keep.add(archive)

        deletions = [(archive, digest) for _created, archive, digest in verified if archive not in keep]
        if apply:
            for archive, expected_digest in deletions:
                if _sha256(archive) != expected_digest:
                    raise BackupRestoreError(f"backup changed after verification; refusing to prune: {archive}")
                archive.unlink()
            if deletions:
                self._sync_directory(directory)
        return {
            "kept": sorted(path.name for path in keep),
            "deleted": sorted(path.name for path, _digest in deletions) if apply else [],
            "would_delete": [] if apply else sorted(path.name for path, _digest in deletions),
            "invalid": invalid,
        }

    def status(
        self,
        output_dir: Path | str,
        *,
        identity_file: Path | str,
        max_age_hours: float = 24.0,
        minimum_free_bytes: int = 5 * 1024**3,
    ) -> dict[str, object]:
        directory = Path(output_dir)
        if max_age_hours <= 0 or minimum_free_bytes < 0:
            raise BackupRestoreError("backup status thresholds must be positive")
        identity = self._private_input_file(identity_file, "age identity file")
        newest: tuple[datetime, Path, dict[str, Any]] | None = None
        for archive in sorted(directory.glob("*.newscraft-backup.tar.gz.age"), reverse=True):
            try:
                manifest = self.verify(archive, identity_file=identity)
            except BackupRestoreError:
                continue
            created = datetime.strptime(manifest["created_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            if newest is None or created > newest[0]:
                newest = (created, archive, manifest)
        if newest is None:
            raise BackupRestoreError("no verified encrypted backup is available")
        age_seconds = max(0.0, (self._created_utc() - newest[0]).total_seconds())
        if age_seconds > max_age_hours * 3600:
            raise BackupRestoreError(
                f"newest verified backup is stale: {age_seconds / 3600:.1f} hours (limit {max_age_hours:.1f})"
            )
        free_bytes = shutil.disk_usage(directory).free
        if free_bytes < minimum_free_bytes:
            raise BackupRestoreError(
                f"backup capacity is below threshold: {free_bytes} bytes free (minimum {minimum_free_bytes})"
            )
        return {
            "status": "healthy",
            "backup_id": newest[2].get("backup_id", "legacy-v1"),
            "archive": newest[1].name,
            "age_seconds": round(age_seconds, 3),
            "free_bytes": free_bytes,
        }

    def restore(
        self,
        archive_path: Path | str,
        *,
        confirm_replace: bool = False,
        identity_file: Path | str | None = None,
    ) -> dict[str, Any]:
        if not confirm_replace:
            raise BackupRestoreError("restore requires --confirm-replace")

        archive = Path(archive_path)
        with tempfile.TemporaryDirectory(prefix="newscraft-backup-restore-") as raw_dir:
            private_dir = Path(raw_dir)
            private_dir.chmod(0o700)
            staging_dir = private_dir
            if archive.name.endswith(".age"):
                if identity_file is None:
                    raise BackupVerificationError("encrypted backup restore requires --identity-file")
                identity = self._private_input_file(identity_file, "age identity file")
                decrypted = private_dir / "archive.tar.gz"
                self._age_decrypt(archive, decrypted, identity)
                staging_dir = private_dir / "payload"
                staging_dir.mkdir(mode=0o700)
                manifest = self._verify_and_stage(decrypted, staging_dir)
            else:
                manifest = self._verify_and_stage(archive, staging_dir)

            self._assert_restore_compatibility(manifest)

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
                        "migrate",
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

    @staticmethod
    def _private_input_file(path: Path | str, label: str) -> Path:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise BackupRestoreError(f"{label} does not exist: {resolved}")
        mode = resolved.stat().st_mode & 0o777
        if mode & 0o077:
            raise BackupRestoreError(f"{label} must not be accessible by group or others: {resolved}")
        return resolved

    def _running_runtime_services(self) -> tuple[str, ...]:
        output = self.runner.run(("docker", "compose", "ps", "--services", "--status", "running"))
        running = set(output.splitlines())
        return tuple(service for service in RUNTIME_SERVICES if service in running)

    def _assert_no_writer_sessions(self) -> None:
        count = self._metadata(
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
                (
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                    "AND backend_type = 'client backend';"
                ),
            ],
            "writer session count",
        )
        if count != "0":
            raise BackupRestoreError(f"backup quiescence failed: {count} database client session(s) remain")

    def _capture_database_inventory(self) -> dict[str, object]:
        output = self._metadata(
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
                DATABASE_INVENTORY_SQL,
            ],
            "database inventory",
        )
        return _parse_database_inventory(output)

    def _age_encrypt(self, source: Path, output: Path, recipient_file: Path) -> None:
        self.runner.run(
            [
                "docker",
                "compose",
                "--profile",
                "operations",
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-v",
                f"{recipient_file}:/run/secrets/backup_recipient:ro",
                "backup",
                "age",
                "--encrypt",
                "--recipients-file",
                "/run/secrets/backup_recipient",
            ],
            input_path=source,
            output_path=output,
        )

    def _age_decrypt(self, source: Path, output: Path, identity_file: Path) -> None:
        self.runner.run(
            [
                "docker",
                "compose",
                "--profile",
                "operations",
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-v",
                f"{identity_file}:/run/secrets/backup_identity:ro",
                "backup",
                "age",
                "--decrypt",
                "--identity",
                "/run/secrets/backup_identity",
            ],
            input_path=source,
            output_path=output,
        )

    def _assert_restore_compatibility(self, manifest: dict[str, Any]) -> None:
        current_server = self._metadata(
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
                "-Atqc",
                "SHOW server_version;",
            ],
            "restore PostgreSQL version",
        )
        if manifest.get("schema") == LEGACY_BACKUP_SCHEMA:
            expected_major = _major_version(manifest["postgresql_version"], "legacy backup PostgreSQL server")
            if _major_version(current_server, "restore PostgreSQL server") != expected_major:
                raise BackupRestoreError(
                    f"unsupported PostgreSQL restore path: backup major {expected_major}, "
                    f"target server {current_server}"
                )
            return
        current_restore = self._metadata(
            ["docker", "compose", "exec", "-T", "postgres", "pg_restore", "--version"],
            "pg_restore version",
        )
        expected_major = manifest["postgresql_major"]
        if _major_version(current_server, "restore PostgreSQL server") != expected_major:
            raise BackupRestoreError(
                f"unsupported PostgreSQL restore path: backup major {expected_major}, target server {current_server}"
            )
        if _major_version(current_restore, "pg_restore") != manifest["pg_dump_major"]:
            raise BackupRestoreError(
                f"unsupported dump client path: backup pg_dump major {manifest['pg_dump_major']}, "
                f"restore client {current_restore}"
            )

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
                "worker-source-generation",
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
        publish_fd, publish_name = tempfile.mkstemp(prefix=".newscraft-encrypted-", dir=final_archive.parent)
        os.close(publish_fd)
        publish_copy = Path(publish_name)
        try:
            self._sync_file(temporary_archive)
            publish_copy.chmod(0o600)
            with temporary_archive.open("rb") as source, publish_copy.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=CHUNK_SIZE)
                destination.flush()
                os.fsync(destination.fileno())
            os.link(publish_copy, final_archive)
            published = True
            publish_copy.unlink()
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
        finally:
            publish_copy.unlink(missing_ok=True)

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
                if manifest["schema"] == BACKUP_SCHEMA:
                    if _inventory_nested_archive(staging_dir / MEDIA_ARCHIVE_NAME) != manifest["media_inventory"]:
                        raise BackupVerificationError("media inventory does not match manifest")
                    if _inventory_nested_archive(staging_dir / EXPORT_ARCHIVE_NAME) != manifest["export_inventory"]:
                        raise BackupVerificationError("export inventory does not match manifest")
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


def _inventory_nested_archive(path: Path) -> dict[str, int | str]:
    _validate_nested_archive(path, path.name)
    records: list[str] = []
    entries = 0
    files = 0
    total_bytes = 0
    with tarfile.open(path, mode="r:gz") as archive:
        for member in sorted(archive.getmembers(), key=lambda item: _validate_member_path(item.name)):
            normalized = _validate_member_path(member.name)
            if normalized == ".":
                continue
            entries += 1
            if member.isdir():
                records.append(f"D\0{normalized}\n")
                continue
            source = archive.extractfile(member)
            if source is None:
                raise BackupVerificationError(f"could not inventory nested member: {member.name}")
            digest = hashlib.sha256()
            byte_count = 0
            while chunk := source.read(CHUNK_SIZE):
                digest.update(chunk)
                byte_count += len(chunk)
            files += 1
            total_bytes += byte_count
            records.append(f"F\0{normalized}\0{byte_count}\0{digest.hexdigest()}\n")
    root = hashlib.sha256("".join(records).encode("utf-8")).hexdigest()
    return {
        "entries": entries,
        "files": files,
        "bytes": total_bytes,
        "root_sha256": root,
    }


def _parse_database_inventory(value: str) -> dict[str, object]:
    try:
        tables = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BackupVerificationError("database inventory is not valid JSON") from exc
    if not isinstance(tables, dict):
        raise BackupVerificationError("database inventory tables must be a JSON object")
    canonical = json.dumps(tables, sort_keys=True, separators=(",", ":")).encode("utf-8")
    inventory: dict[str, object] = {
        "tables": tables,
        "root_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    _validate_database_inventory(inventory)
    return inventory


def _validate_database_inventory(inventory: object) -> None:
    if not isinstance(inventory, dict) or set(inventory) != DATABASE_INVENTORY_FIELDS:
        raise BackupVerificationError("manifest database_inventory does not match schema")
    tables = inventory["tables"]
    if not isinstance(tables, dict):
        raise BackupVerificationError("manifest database_inventory.tables must be an object")
    for table_name, record in tables.items():
        if not isinstance(table_name, str) or re.fullmatch(r"public\.[a-z_][a-z0-9_]*", table_name) is None:
            raise BackupVerificationError("manifest database inventory table name is invalid")
        if not isinstance(record, dict) or set(record) != DATABASE_TABLE_RECORD_FIELDS:
            raise BackupVerificationError(f"manifest database inventory record is invalid: {table_name}")
        rows = record["rows"]
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
            raise BackupVerificationError(f"manifest database inventory row count is invalid: {table_name}")
        content_md5 = record["content_md5"]
        if not isinstance(content_md5, str) or re.fullmatch(r"[0-9a-f]{32}", content_md5) is None:
            raise BackupVerificationError(f"manifest database inventory content hash is invalid: {table_name}")
    root = inventory["root_sha256"]
    canonical = json.dumps(tables, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if not isinstance(root, str) or root != hashlib.sha256(canonical).hexdigest():
        raise BackupVerificationError("manifest database inventory root hash is invalid")


def _major_version(value: str, label: str) -> int:
    match = re.search(r"(?:PostgreSQL\)?\s+)?(\d+)(?:\.\d+)?", value)
    if match is None:
        raise BackupVerificationError(f"{label} version is not parseable: {value!r}")
    return int(match.group(1))


def _validate_manifest(manifest: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(manifest, dict):
        raise BackupVerificationError("manifest must be a JSON object")
    schema = manifest.get("schema")
    if schema not in {BACKUP_SCHEMA, LEGACY_BACKUP_SCHEMA}:
        raise BackupVerificationError(
            f"wrong schema: expected {BACKUP_SCHEMA!r} or {LEGACY_BACKUP_SCHEMA!r}, got {schema!r}"
        )
    expected_fields = MANIFEST_FIELDS if schema == BACKUP_SCHEMA else LEGACY_MANIFEST_FIELDS
    if set(manifest) != expected_fields:
        missing = sorted(expected_fields - set(manifest))
        extra = sorted(set(manifest) - expected_fields)
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

    if schema == BACKUP_SCHEMA:
        backup_id = manifest["backup_id"]
        if not isinstance(backup_id, str) or not re.fullmatch(r"newscraft-\d{8}T\d{6}Z-[0-9a-f]{12}", backup_id):
            raise BackupVerificationError("manifest backup_id is invalid")
        for field in ("postgresql_major", "pg_dump_major"):
            value = manifest[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 12:
                raise BackupVerificationError(f"manifest field {field!r} is invalid")
        if _major_version(manifest["postgresql_version"], "PostgreSQL server") != manifest["postgresql_major"]:
            raise BackupVerificationError("manifest PostgreSQL server major does not match its version")
        if not isinstance(manifest["pg_dump_version"], str) or not manifest["pg_dump_version"]:
            raise BackupVerificationError("manifest pg_dump_version must be non-empty")
        if _major_version(manifest["pg_dump_version"], "pg_dump") != manifest["pg_dump_major"]:
            raise BackupVerificationError("manifest pg_dump major does not match its version")
        _validate_database_inventory(manifest["database_inventory"])
        image_ids = manifest["container_image_ids"]
        if (
            not isinstance(image_ids, list)
            or not image_ids
            or any(
                not isinstance(value, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", value)
                for value in image_ids
            )
            or image_ids != sorted(set(image_ids))
        ):
            raise BackupVerificationError("manifest container_image_ids are invalid")
        consistency = manifest["consistency"]
        if not isinstance(consistency, dict) or set(consistency) != CONSISTENCY_FIELDS:
            raise BackupVerificationError("manifest consistency record does not match schema")
        if consistency.get("mode") != "quiesced":
            raise BackupVerificationError("manifest consistency mode must be quiesced")
        try:
            started = datetime.strptime(consistency["quiesce_started_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            completed = datetime.strptime(consistency["quiesce_completed_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=UTC
            )
        except (TypeError, ValueError) as exc:
            raise BackupVerificationError("manifest quiescence timestamps must be UTC") from exc
        if completed < started:
            raise BackupVerificationError("manifest quiescence completion precedes its start")
        for field in ("media_inventory", "export_inventory"):
            inventory = manifest[field]
            if not isinstance(inventory, dict) or set(inventory) != INVENTORY_FIELDS:
                raise BackupVerificationError(f"manifest {field} does not match schema")
            for count_field in ("entries", "files", "bytes"):
                count = inventory[count_field]
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise BackupVerificationError(f"manifest {field}.{count_field} is invalid")
            if not isinstance(inventory["root_sha256"], str) or not SHA256_PATTERN.fullmatch(inventory["root_sha256"]):
                raise BackupVerificationError(f"manifest {field}.root_sha256 is invalid")

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
    backup_parser.add_argument(
        "--recipient-file",
        type=Path,
        required=True,
        help="0600 file containing the age recipient used for encryption",
    )
    backup_parser.add_argument(
        "--identity-file",
        type=Path,
        required=True,
        help="0600 age identity used only to verify the encrypted result before publication",
    )
    backup_parser.add_argument(
        "--staging-dir",
        type=Path,
        required=True,
        help="existing mode-0700 tmpfs or approved encrypted staging directory",
    )

    verify_parser = subparsers.add_parser("verify", help="verify an archive without restoring")
    verify_parser.add_argument("archive", type=Path)
    verify_parser.add_argument("--identity-file", type=Path, help="0600 age identity for an encrypted archive")

    prune_parser = subparsers.add_parser("prune", help="apply safe daily/weekly/monthly encrypted-backup retention")
    prune_parser.add_argument("--output-dir", type=Path, default=Path("backups"))
    prune_parser.add_argument("--identity-file", type=Path, required=True)
    prune_parser.add_argument("--apply", action="store_true", help="delete verified backups outside retention")

    status_parser = subparsers.add_parser("status", help="fail when verified backup freshness or capacity is unsafe")
    status_parser.add_argument("--output-dir", type=Path, default=Path("backups"))
    status_parser.add_argument("--identity-file", type=Path, required=True)
    status_parser.add_argument("--max-age-hours", type=float, default=24.0)
    status_parser.add_argument("--minimum-free-bytes", type=int, default=5 * 1024**3)

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
    restore_parser.add_argument("--identity-file", type=Path, help="0600 age identity for an encrypted archive")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workflow = BackupRestore()
    if args.command == "backup":
        archive = workflow.backup(
            args.output_dir,
            recipient_file=args.recipient_file,
            identity_file=args.identity_file,
            staging_root=args.staging_dir,
        )
        print(f"Backup created and verified: {archive}")
        return 0
    if args.command == "verify":
        workflow.verify(args.archive, identity_file=args.identity_file)
        print(f"Backup verified: {args.archive}")
        return 0
    if args.command == "prune":
        prune_result = workflow.prune(args.output_dir, identity_file=args.identity_file, apply=args.apply)
        print(json.dumps(prune_result, indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        status_result = workflow.status(
            args.output_dir,
            identity_file=args.identity_file,
            max_age_hours=args.max_age_hours,
            minimum_free_bytes=args.minimum_free_bytes,
        )
        print(json.dumps(status_result, indent=2, sort_keys=True))
        return 0
    if not args.confirm_replace:
        raise SystemExit("restore requires --confirm-replace")
    workflow.restore(args.archive, confirm_replace=True, identity_file=args.identity_file)
    print(f"Restore completed and services restarted: {args.archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BackupRestoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
