#!/usr/bin/env python3
"""Restore an encrypted backup into a strictly named disposable Compose project."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from backup_restore import (
    DATABASE_INVENTORY_SQL,
    EXPORT_ARCHIVE_NAME,
    MEDIA_ARCHIVE_NAME,
    RUNTIME_SERVICES,
    BackupRestore,
    BackupRestoreError,
    _inventory_nested_archive,
    _parse_database_inventory,
    _sha256,
)

PROJECT_PATTERN = r"newscraft-restore-drill-[a-z0-9][a-z0-9-]{5,39}"
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.restore-drill.yml")


def _run(command: Sequence[str], *, output_path: Path | None = None) -> str:
    output = output_path.open("wb") if output_path is not None else subprocess.PIPE
    try:
        result = subprocess.run(list(command), check=False, stdout=output, stderr=subprocess.PIPE)
    finally:
        if output_path is not None:
            output.close()  # type: ignore[union-attr]
    if result.returncode:
        detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()[:4000]
        raise BackupRestoreError(f"drill command failed ({' '.join(command)}): {detail}")
    if output_path is not None:
        return ""
    return (result.stdout or b"").decode("utf-8", errors="strict").strip()


def _compose(*arguments: str) -> list[str]:
    return ["docker", "compose", *arguments]


def _private_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.stat().st_mode & 0o077:
        raise BackupRestoreError(f"{label} must be an existing 0600 file: {resolved}")
    return resolved


def _assert_project_name(project_name: str) -> None:
    import re

    if re.fullmatch(PROJECT_PATTERN, project_name) is None:
        raise BackupRestoreError("project name must match newscraft-restore-drill-[a-z0-9][a-z0-9-]{5,39}")


def _assert_port_available(port: int) -> None:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise BackupRestoreError(f"drill API port {port} is unavailable") from exc


def _assert_disposable_project(project_name: str) -> None:
    container_ids = _run(_compose("ps", "-q")).splitlines()
    for container_id in container_ids:
        actual = _run(
            [
                "docker",
                "inspect",
                "--format",
                '{{ index .Config.Labels "com.docker.compose.project" }}',
                container_id,
            ]
        )
        if actual != project_name:
            raise BackupRestoreError(
                f"refusing cleanup: container {container_id} belongs to project {actual!r}, not {project_name!r}"
            )
    volume_names = _run(
        [
            "docker",
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={project_name}",
            "--format",
            "{{.Name}}",
        ]
    ).splitlines()
    for volume_name in volume_names:
        actual = _run(
            [
                "docker",
                "volume",
                "inspect",
                "--format",
                '{{ index .Labels "com.docker.compose.project" }}',
                volume_name,
            ]
        )
        if actual != project_name:
            raise BackupRestoreError(
                f"refusing cleanup: volume {volume_name} belongs to project {actual!r}, not {project_name!r}"
            )


def _canary_count_in_tar(path: Path, canary: bytes) -> int:
    count = 0
    with tarfile.open(path, mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            source = archive.extractfile(member)
            if source is not None:
                count += source.read().count(canary)
    return count


def _write_signed_report(report: dict[str, object], path: Path, signing_key: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(payload)
    path.chmod(0o600)
    signature_path = path.with_suffix(path.suffix + ".hmac-sha256")
    signature_path.write_text(
        hmac.new(signing_key, payload, hashlib.sha256).hexdigest() + "\n",
        encoding="ascii",
    )
    signature_path.chmod(0o600)


def _start_restored_runtime() -> None:
    _run(_compose("up", "-d", "--no-deps", "--wait", *RUNTIME_SERVICES))


def run_drill(
    *,
    archive: Path,
    identity_file: Path,
    secret_canary_file: Path,
    report_signing_key_file: Path,
    project_name: str,
    api_port: int,
    output_dir: Path,
    cleanup: bool,
) -> Path:
    _assert_project_name(project_name)
    _assert_port_available(api_port)
    archive = archive.resolve()
    if not archive.is_file() or not archive.name.endswith(".newscraft-backup.tar.gz.age"):
        raise BackupRestoreError("restore drill requires an encrypted .newscraft-backup.tar.gz.age archive")
    if shutil.disk_usage(archive.parent).free < archive.stat().st_size * 5:
        raise BackupRestoreError("insufficient free space for the disposable restore drill")
    identity = _private_file(identity_file, "age identity")
    canary_path = _private_file(secret_canary_file, "secret canary")
    signing_key_path = _private_file(report_signing_key_file, "report signing key")
    canary = canary_path.read_bytes().strip()
    signing_key = signing_key_path.read_bytes()
    if len(canary) < 16 or len(signing_key) < 32:
        raise BackupRestoreError("canary must be >=16 bytes and report signing key >=32 bytes")

    repository = Path(__file__).resolve().parents[1]
    prior_environment = {
        key: os.environ.get(key)
        for key in (
            "COMPOSE_PROJECT_NAME",
            "COMPOSE_FILE",
            "DRILL_API_PORT",
            "SECRET_MASTER_KEY",
        )
    }
    os.environ["COMPOSE_PROJECT_NAME"] = project_name
    os.environ["COMPOSE_FILE"] = os.pathsep.join(str(repository / name) for name in COMPOSE_FILES)
    os.environ["DRILL_API_PORT"] = str(api_port)
    if not os.environ.get("SECRET_MASTER_KEY"):
        os.environ["SECRET_MASTER_KEY"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    started = datetime.now(UTC)
    monotonic_started = time.monotonic()
    report_path = output_dir / f"{project_name}.json"
    try:
        workflow = BackupRestore()
        _run(_compose("--profile", "operations", "build", "backup"))
        manifest = workflow.verify(archive, identity_file=identity)
        _run(_compose("--profile", "operations", "up", "-d", "--build", "--wait", "postgres"))
        workflow.restore(
            archive,
            confirm_replace=True,
            identity_file=identity,
            restart_services=False,
        )

        with tempfile.TemporaryDirectory(prefix="newscraft-restore-proof-") as raw_dir:
            evidence = Path(raw_dir)
            evidence.chmod(0o700)
            backup_run = _compose("--profile", "operations", "run", "--rm", "--no-deps", "-T", "backup")
            restored_data = evidence / "database-data.sql"
            restored_media = evidence / MEDIA_ARCHIVE_NAME
            restored_exports = evidence / EXPORT_ARCHIVE_NAME
            _run(
                [
                    *backup_run,
                    "pg_dump",
                    "--data-only",
                    "--column-inserts",
                    "--no-owner",
                    "--no-privileges",
                ],
                output_path=restored_data,
            )
            _run(
                [*backup_run, "tar", "-C", "/data/media", "-czf", "-", "."],
                output_path=restored_media,
            )
            _run(
                [*backup_run, "tar", "-C", "/data/exports", "-czf", "-", "."],
                output_path=restored_exports,
            )
            database_inventory = _parse_database_inventory(
                _run(
                    _compose(
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
                    )
                )
            )
            media_inventory = _inventory_nested_archive(restored_media)
            export_inventory = _inventory_nested_archive(restored_exports)
            if database_inventory != manifest["database_inventory"]:
                raise BackupRestoreError("restored database inventory does not match the backup")
            if media_inventory != manifest["media_inventory"] or export_inventory != manifest["export_inventory"]:
                raise BackupRestoreError("restored file inventory does not match the backup")
            canary_count = (
                restored_data.read_bytes().count(canary)
                + _canary_count_in_tar(restored_media, canary)
                + _canary_count_in_tar(restored_exports, canary)
                + json.dumps(manifest, sort_keys=True).encode().count(canary)
            )
            if canary_count:
                raise BackupRestoreError("secret canary was found in restored backup data")

        invalid_constraints = _run(
            _compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "newscraft",
                "-d",
                "newscraft",
                "-Atqc",
                "SELECT count(*) FROM pg_constraint WHERE NOT convalidated;",
            )
        )
        if invalid_constraints != "0":
            raise BackupRestoreError(f"restored database has {invalid_constraints} unvalidated constraints")
        _start_restored_runtime()
        ready_url = f"http://127.0.0.1:{api_port}/health/ready"
        with urllib.request.urlopen(ready_url, timeout=10) as response:
            if response.status != 200:
                raise BackupRestoreError(f"restored readiness returned HTTP {response.status}")
        smoke_dir = output_dir / f"{project_name}-smoke"
        _run(
            [
                sys.executable,
                str(repository / "scripts" / "smoke.py"),
                "--base-url",
                f"http://127.0.0.1:{api_port}",
                "--provider",
                "fake",
                "--telegram-mode",
                "dry-run",
                "--output-dir",
                str(smoke_dir),
            ]
        )
        completed = datetime.now(UTC)
        rpo_seconds = max(
            0,
            int(
                (
                    started - datetime.strptime(manifest["created_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                ).total_seconds()
            ),
        )
        report: dict[str, object] = {
            "schema": "newscraft-restore-drill-v1",
            "project_name": project_name,
            "archive": archive.name,
            "archive_sha256": _sha256(archive),
            "backup_id": manifest["backup_id"],
            "status": "passed",
            "started_utc": started.isoformat(),
            "completed_utc": completed.isoformat(),
            "rpo_seconds": rpo_seconds,
            "rto_seconds": round(time.monotonic() - monotonic_started, 3),
            "database_inventory": database_inventory,
            "media_inventory": media_inventory,
            "export_inventory": export_inventory,
            "unvalidated_constraints": 0,
            "secret_canary_count": 0,
            "readiness": "passed",
            "credential_free_smoke": "passed",
            "cleanup": "pending" if cleanup else "retained_for_review",
        }
        _write_signed_report(report, report_path, signing_key)
        if cleanup:
            _assert_disposable_project(project_name)
            _run(_compose("down", "-v", "--remove-orphans"))
            report["cleanup"] = "completed"
        _write_signed_report(report, report_path, signing_key)
        return report_path
    except BaseException as exc:
        failed_report: dict[str, object] = {
            "schema": "newscraft-restore-drill-v1",
            "project_name": project_name,
            "archive": archive.name,
            "archive_sha256": _sha256(archive),
            "started_utc": started.isoformat(),
            "completed_utc": datetime.now(UTC).isoformat(),
            "rto_seconds": round(time.monotonic() - monotonic_started, 3),
            "status": "failed",
            "failure_type": type(exc).__name__,
            "cleanup": "not_completed",
        }
        _write_signed_report(failed_report, report_path, signing_key)
        raise
    finally:
        for key, value in prior_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a contained encrypted NewsCraft restore drill")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--identity-file", type=Path, required=True)
    parser.add_argument("--secret-canary-file", type=Path, required=True)
    parser.add_argument("--report-signing-key-file", type=Path, required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--api-port", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/restore-drills"))
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="remove only the label-verified disposable project",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_drill(
        archive=args.archive,
        identity_file=args.identity_file,
        secret_canary_file=args.secret_canary_file,
        report_signing_key_file=args.report_signing_key_file,
        project_name=args.project_name,
        api_port=args.api_port,
        output_dir=args.output_dir,
        cleanup=args.cleanup,
    )
    print(f"Restore drill completed: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BackupRestoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
