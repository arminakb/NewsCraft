from __future__ import annotations

import hashlib
import io
import json
import stat
import sys
import tarfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import ANY

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from backup_restore import (  # noqa: E402
    BackupRestore,
    BackupRestoreError,
    BackupVerificationError,
    main,
)

FIXED_NOW = datetime(2026, 7, 13, 12, 34, 56, tzinfo=UTC)
RUNTIME_SERVICES = [
    "api",
    "worker-source-generation",
    "worker-publishing",
    "scheduler",
    "frontend",
]
STOP_COMMAND = ["docker", "compose", "stop", *RUNTIME_SERVICES]
START_COMMAND = ["docker", "compose", "up", "-d", "--no-deps", *RUNTIME_SERVICES]
RECOVERY_COMMAND = "docker compose up -d --no-deps " + " ".join(RUNTIME_SERVICES)


def _content_archive(files: dict[str, bytes] | None = None) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        archive.addfile(root)
        for name, content in (files or {"payload.txt": b"payload"}).items():
            member = tarfile.TarInfo(f"./{name}")
            member.size = len(content)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


class FakeRunner:
    def __init__(
        self,
        *,
        fail_when: Callable[[list[str]], bool] | None = None,
    ) -> None:
        self.commands: list[list[str]] = []
        self.calls: list[dict[str, object]] = []
        self.private_directory_modes: list[int] = []
        self.fail_when = fail_when

    def run(
        self,
        command: Sequence[str],
        *,
        output_path: Path | None = None,
        input_path: Path | None = None,
    ) -> str:
        normalized = list(command)
        self.commands.append(normalized)
        call: dict[str, object] = {"command": normalized}
        if output_path is not None:
            call["output_path"] = output_path
            self.private_directory_modes.append(stat.S_IMODE(output_path.parent.stat().st_mode))
        if input_path is not None:
            call["input_path"] = input_path
            call["input_bytes"] = input_path.read_bytes()
            self.private_directory_modes.append(stat.S_IMODE(input_path.parent.stat().st_mode))
        self.calls.append(call)

        if self.fail_when is not None and self.fail_when(normalized):
            raise BackupRestoreError(f"injected command failure: {' '.join(normalized)}")

        if output_path is not None:
            if "pg_dump" in normalized:
                output_path.write_bytes(b"PGDMP\x01database")
            elif "/data/media" in normalized:
                output_path.write_bytes(_content_archive({"photo.jpg": b"media"}))
            elif "/data/exports" in normalized:
                output_path.write_bytes(_content_archive({"bundle.json": b"export"}))
            else:  # pragma: no cover - a new binary command must be handled explicitly
                raise AssertionError(f"unexpected binary command: {normalized}")

        if normalized[:2] == ["git", "rev-parse"]:
            return "a" * 40 + "\n"
        if normalized[-2:] == ["alembic", "current"]:
            return "0009_operational_retention (head)\n"
        if normalized[-2:] == ["alembic", "heads"]:
            return "0009_operational_retention (head)\n"
        if "SHOW server_version;" in normalized:
            return "18.4\n"
        return ""


@pytest.fixture
def fake_runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def valid_archive(tmp_path: Path, fake_runner: FakeRunner) -> Path:
    return BackupRestore(runner=fake_runner, now=lambda: FIXED_NOW).backup(tmp_path)


def _read_outer_archive(archive_path: Path) -> list[tuple[tarfile.TarInfo, bytes]]:
    entries: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            content = archive.extractfile(member).read() if member.isfile() else b""
            copy = tarfile.TarInfo(member.name)
            copy.size = len(content)
            copy.mode = member.mode
            copy.type = member.type
            copy.linkname = member.linkname
            entries.append((copy, content))
    return entries


def _write_outer_archive(
    archive_path: Path,
    entries: list[tuple[tarfile.TarInfo, bytes]],
) -> Path:
    with tarfile.open(archive_path, "w:gz") as archive:
        for member, content in entries:
            archive.addfile(member, io.BytesIO(content) if member.isfile() else None)
    return archive_path


def _mutate_manifest(
    valid_archive: Path,
    tmp_path: Path,
    mutate: Callable[[dict[str, object]], None],
) -> Path:
    entries = _read_outer_archive(valid_archive)
    changed: list[tuple[tarfile.TarInfo, bytes]] = []
    for member, content in entries:
        if member.name == "manifest.json":
            manifest = json.loads(content)
            mutate(manifest)
            content = json.dumps(manifest, sort_keys=True).encode()
            member.size = len(content)
        changed.append((member, content))
    return _write_outer_archive(tmp_path / "mutated.newscraft-backup.tar.gz", changed)


def _replace_nested_archive(
    valid_archive: Path,
    tmp_path: Path,
    *,
    member_name: str,
    content: bytes,
) -> Path:
    entries = _read_outer_archive(valid_archive)
    manifest: dict[str, object] | None = None
    changed: list[tuple[tarfile.TarInfo, bytes]] = []
    for member, current in entries:
        if member.name == "manifest.json":
            manifest = json.loads(current)
            continue
        if member.name == member_name:
            current = content
            member.size = len(current)
        changed.append((member, current))
    assert manifest is not None
    record_name = {
        "database.dump": "database_dump",
        "media.tar.gz": "media_archive",
        "exports.tar.gz": "export_archive",
    }[member_name]
    record = manifest[record_name]
    assert isinstance(record, dict)
    record["bytes"] = len(content)
    record["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    manifest_member = tarfile.TarInfo("manifest.json")
    manifest_member.size = len(manifest_bytes)
    changed.insert(0, (manifest_member, manifest_bytes))
    return _write_outer_archive(
        tmp_path / "nested-mutated.newscraft-backup.tar.gz",
        changed,
    )


def test_backup_runs_exact_consistent_database_media_and_export_commands(
    tmp_path: Path,
    fake_runner: FakeRunner,
) -> None:
    archive = BackupRestore(runner=fake_runner, now=lambda: FIXED_NOW).backup(tmp_path)

    assert fake_runner.commands[:3] == [
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
    ]
    assert archive.name == "newscraft-20260713T123456Z.newscraft-backup.tar.gz"
    assert archive.parent == tmp_path
    assert archive.is_file()
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert fake_runner.private_directory_modes
    assert set(fake_runner.private_directory_modes) == {0o700}
    assert list(tmp_path.iterdir()) == [archive]


def test_backup_manifest_records_metadata_sizes_and_checksums(
    valid_archive: Path,
) -> None:
    manifest = BackupRestore().verify(valid_archive)

    assert manifest == {
        "schema": "newscraft-backup-v1",
        "created_utc": "2026-07-13T12:34:56Z",
        "git_sha": "a" * 40,
        "alembic_current": "0009_operational_retention (head)",
        "alembic_head": "0009_operational_retention (head)",
        "postgresql_version": "18.4",
        "database_dump": {
            "filename": "database.dump",
            "bytes": len(b"PGDMP\x01database"),
            "sha256": hashlib.sha256(b"PGDMP\x01database").hexdigest(),
        },
        "media_archive": {
            "filename": "media.tar.gz",
            "bytes": ANY,
            "sha256": ANY,
        },
        "export_archive": {
            "filename": "exports.tar.gz",
            "bytes": ANY,
            "sha256": ANY,
        },
    }


def test_backup_failure_does_not_publish_a_partial_archive(tmp_path: Path) -> None:
    runner = FakeRunner(fail_when=lambda command: "/data/exports" in command)

    with pytest.raises(BackupRestoreError, match="injected command failure"):
        BackupRestore(runner=runner, now=lambda: FIXED_NOW).backup(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_backup_never_overwrites_archive_created_during_publication(
    tmp_path: Path,
) -> None:
    rival = tmp_path / "newscraft-20260713T123456Z.newscraft-backup.tar.gz"

    class RacingRunner(FakeRunner):
        def run(self, command, *, output_path=None, input_path=None):
            result = super().run(
                command,
                output_path=output_path,
                input_path=input_path,
            )
            if "SHOW server_version;" in command:
                rival.write_bytes(b"rival-archive")
            return result

    with pytest.raises(BackupRestoreError, match="already exists"):
        BackupRestore(runner=RacingRunner(), now=lambda: FIXED_NOW).backup(tmp_path)

    assert rival.read_bytes() == b"rival-archive"


def test_backup_removes_published_archive_when_durability_sync_fails(
    tmp_path: Path,
    fake_runner: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = BackupRestore(runner=fake_runner, now=lambda: FIXED_NOW)

    def fail_sync(_path: Path) -> None:
        raise OSError("injected durability failure")

    monkeypatch.setattr(workflow, "_sync_directory", fail_sync)

    with pytest.raises(BackupRestoreError, match="injected durability failure"):
        workflow.backup(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_backup_removes_published_archive_when_durability_sync_is_interrupted(
    tmp_path: Path,
    fake_runner: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = BackupRestore(runner=fake_runner, now=lambda: FIXED_NOW)

    def interrupt_sync(_path: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(workflow, "_sync_directory", interrupt_sync)

    with pytest.raises(KeyboardInterrupt):
        workflow.backup(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_verify_rejects_checksum_mismatch(valid_archive: Path, tmp_path: Path) -> None:
    entries = _read_outer_archive(valid_archive)
    tampered: list[tuple[tarfile.TarInfo, bytes]] = []
    for member, content in entries:
        if member.name == "media.tar.gz":
            content = bytes([content[0] ^ 1]) + content[1:]
        tampered.append((member, content))
    archive = _write_outer_archive(tmp_path / "tampered.tar.gz", tampered)

    with pytest.raises(BackupVerificationError, match="checksum mismatch.*media.tar.gz"):
        BackupRestore().verify(archive)


@pytest.mark.parametrize("database_dump", [b"", b"not-a-custom-dump", b"PGDMP"])
def test_verify_rejects_non_custom_or_truncated_database_dump(
    valid_archive: Path,
    tmp_path: Path,
    database_dump: bytes,
) -> None:
    unsafe = _replace_nested_archive(
        valid_archive,
        tmp_path,
        member_name="database.dump",
        content=database_dump,
    )

    with pytest.raises(BackupVerificationError, match="database.dump"):
        BackupRestore().verify(unsafe)


@pytest.mark.parametrize(
    ("bad_name", "message"),
    [
        ("../escape", "traversal"),
        ("/absolute", "absolute"),
    ],
)
def test_verify_rejects_unsafe_outer_member_paths(
    valid_archive: Path,
    tmp_path: Path,
    bad_name: str,
    message: str,
) -> None:
    entries = _read_outer_archive(valid_archive)
    member = tarfile.TarInfo(bad_name)
    member.size = 3
    entries.append((member, b"bad"))
    archive = _write_outer_archive(tmp_path / "unsafe.tar.gz", entries)

    with pytest.raises(BackupVerificationError, match=message):
        BackupRestore().verify(archive)


@pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_verify_rejects_outer_links(
    valid_archive: Path,
    tmp_path: Path,
    link_type: bytes,
) -> None:
    entries = _read_outer_archive(valid_archive)
    member = tarfile.TarInfo("linked.dump")
    member.type = link_type
    member.linkname = "database.dump"
    entries.append((member, b""))
    archive = _write_outer_archive(tmp_path / "linked.tar.gz", entries)

    with pytest.raises(BackupVerificationError, match="link"):
        BackupRestore().verify(archive)


def test_verify_rejects_duplicate_members(valid_archive: Path, tmp_path: Path) -> None:
    entries = _read_outer_archive(valid_archive)
    duplicate = next(entry for entry in entries if entry[0].name == "database.dump")
    entries.append(duplicate)
    archive = _write_outer_archive(tmp_path / "duplicate.tar.gz", entries)

    with pytest.raises(BackupVerificationError, match="duplicate.*database.dump"):
        BackupRestore().verify(archive)


def test_verify_rejects_unexpected_and_missing_members(
    valid_archive: Path,
    tmp_path: Path,
) -> None:
    entries = _read_outer_archive(valid_archive)
    extra = tarfile.TarInfo("credentials.env")
    extra.size = 6
    with_extra = _write_outer_archive(
        tmp_path / "extra.tar.gz",
        [*entries, (extra, b"secret")],
    )
    missing = _write_outer_archive(
        tmp_path / "missing.tar.gz",
        [entry for entry in entries if entry[0].name != "exports.tar.gz"],
    )

    with pytest.raises(BackupVerificationError, match="unexpected.*credentials.env"):
        BackupRestore().verify(with_extra)
    with pytest.raises(BackupVerificationError, match="missing.*exports.tar.gz"):
        BackupRestore().verify(missing)


def test_verify_rejects_wrong_or_extra_manifest_schema(
    valid_archive: Path,
    tmp_path: Path,
) -> None:
    wrong = _mutate_manifest(
        valid_archive,
        tmp_path,
        lambda manifest: manifest.__setitem__("schema", "newscraft-backup-v0"),
    )

    with pytest.raises(BackupVerificationError, match="wrong schema"):
        BackupRestore().verify(wrong)

    extra = _mutate_manifest(
        valid_archive,
        tmp_path,
        lambda manifest: manifest.__setitem__("credential", "must-not-exist"),
    )
    with pytest.raises(BackupVerificationError, match="manifest fields"):
        BackupRestore().verify(extra)


def test_verify_rejects_size_mismatch(valid_archive: Path, tmp_path: Path) -> None:
    archive = _mutate_manifest(
        valid_archive,
        tmp_path,
        lambda manifest: manifest["database_dump"].__setitem__("bytes", 999),  # type: ignore[union-attr]
    )

    with pytest.raises(BackupVerificationError, match="size mismatch.*database.dump"):
        BackupRestore().verify(archive)


def test_verify_rejects_unsafe_nested_volume_archive(
    valid_archive: Path,
    tmp_path: Path,
) -> None:
    nested = io.BytesIO()
    with tarfile.open(fileobj=nested, mode="w:gz") as archive:
        member = tarfile.TarInfo("../../host-file")
        member.size = 3
        archive.addfile(member, io.BytesIO(b"bad"))
    nested_bytes = nested.getvalue()

    entries = _read_outer_archive(valid_archive)
    manifest: dict[str, object] | None = None
    changed: list[tuple[tarfile.TarInfo, bytes]] = []
    for member, content in entries:
        if member.name == "manifest.json":
            manifest = json.loads(content)
            continue
        if member.name == "media.tar.gz":
            content = nested_bytes
            member.size = len(content)
        changed.append((member, content))
    assert manifest is not None
    media = manifest["media_archive"]
    assert isinstance(media, dict)
    media["bytes"] = len(nested_bytes)
    media["sha256"] = hashlib.sha256(nested_bytes).hexdigest()
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    manifest_member = tarfile.TarInfo("manifest.json")
    manifest_member.size = len(manifest_bytes)
    changed.insert(0, (manifest_member, manifest_bytes))
    unsafe = _write_outer_archive(tmp_path / "nested-unsafe.tar.gz", changed)

    with pytest.raises(BackupVerificationError, match="media.tar.gz.*traversal"):
        BackupRestore().verify(unsafe)


@pytest.mark.parametrize(
    "layout",
    [
        "file-root",
        "file-ancestor",
        "file-directory-name",
        "file-dot-directory-name",
    ],
)
def test_verify_rejects_nested_path_type_conflicts(
    valid_archive: Path,
    tmp_path: Path,
    layout: str,
) -> None:
    nested = io.BytesIO()
    with tarfile.open(fileobj=nested, mode="w:gz") as archive:
        if layout == "file-root":
            root = tarfile.TarInfo(".")
            root.size = 4
            archive.addfile(root, io.BytesIO(b"root"))
        else:
            root = tarfile.TarInfo(".")
            root.type = tarfile.DIRTYPE
            archive.addfile(root)
            parent_name = {
                "file-directory-name": "./a/",
                "file-dot-directory-name": "./a/.",
            }.get(layout, "./a")
            parent = tarfile.TarInfo(parent_name)
            parent.size = 6
            archive.addfile(parent, io.BytesIO(b"parent"))
            if layout == "file-ancestor":
                child = tarfile.TarInfo("./a/b")
                child.size = 5
                archive.addfile(child, io.BytesIO(b"child"))

    unsafe = _replace_nested_archive(
        valid_archive,
        tmp_path,
        member_name="media.tar.gz",
        content=nested.getvalue(),
    )

    with pytest.raises(BackupVerificationError, match="media.tar.gz"):
        BackupRestore().verify(unsafe)


def test_restore_requires_explicit_confirmation(valid_archive: Path) -> None:
    with pytest.raises(BackupRestoreError, match="--confirm-replace"):
        BackupRestore(runner=FakeRunner()).restore(valid_archive)

    with pytest.raises(SystemExit, match="--confirm-replace"):
        main(["restore", str(valid_archive)])


def test_restore_verifies_before_stopping_services(
    valid_archive: Path,
    tmp_path: Path,
) -> None:
    tampered = _mutate_manifest(
        valid_archive,
        tmp_path,
        lambda manifest: manifest.__setitem__("schema", "wrong"),
    )
    runner = FakeRunner()

    with pytest.raises(BackupVerificationError):
        BackupRestore(runner=runner).restore(tampered, confirm_replace=True)

    assert runner.commands == []


def test_restore_validates_database_dump_with_pg_restore_before_stopping(
    valid_archive: Path,
) -> None:
    runner = FakeRunner(fail_when=lambda command: "pg_restore" in command and "--list" in command)

    with pytest.raises(BackupRestoreError, match="injected command failure"):
        BackupRestore(runner=runner).restore(valid_archive, confirm_replace=True)

    validation_index = next(
        index for index, command in enumerate(runner.commands) if "pg_restore" in command and "--list" in command
    )
    assert validation_index == 0
    assert STOP_COMMAND not in runner.commands


def test_restore_stops_replaces_and_restarts_actual_split_services(
    valid_archive: Path,
) -> None:
    runner = FakeRunner()

    BackupRestore(runner=runner).restore(valid_archive, confirm_replace=True)

    assert STOP_COMMAND in runner.commands
    assert START_COMMAND in runner.commands
    assert [
        "docker",
        "compose",
        "stop",
        "api",
        "worker",
        "scheduler",
        "frontend",
    ] not in runner.commands

    stop_index = runner.commands.index(STOP_COMMAND)
    drop_index = next(
        i for i, command in enumerate(runner.commands) if any("DROP DATABASE" in argument for argument in command)
    )
    create_index = next(
        i for i, command in enumerate(runner.commands) if any("CREATE DATABASE" in argument for argument in command)
    )
    restore_index = next(
        i for i, command in enumerate(runner.commands) if "pg_restore" in command and "--exit-on-error" in command
    )
    media_index = next(i for i, command in enumerate(runner.commands) if "/data/media" in command)
    export_index = next(i for i, command in enumerate(runner.commands) if "/data/exports" in command)
    migrate_index = runner.commands.index(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "migrate",
        ]
    )
    start_index = runner.commands.index(START_COMMAND)
    assert stop_index < drop_index < create_index < restore_index
    assert restore_index < media_index < export_index < migrate_index < start_index

    database_calls = [call for call in runner.calls if "pg_restore" in call["command"]]
    assert len(database_calls) == 2
    assert all(call["input_bytes"] == b"PGDMP\x01database" for call in database_calls)
    volume_calls = [call for call in runner.calls if "input_bytes" in call and "pg_restore" not in call["command"]]
    for call in volume_calls:
        with tarfile.open(fileobj=io.BytesIO(call["input_bytes"]), mode="r:gz") as archive:  # type: ignore[arg-type]
            assert archive.getmembers()


def test_restore_failure_restops_services_and_prints_exact_recovery_command(
    valid_archive: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = FakeRunner(fail_when=lambda command: "pg_restore" in command and "--exit-on-error" in command)

    with pytest.raises(BackupRestoreError, match="injected command failure"):
        BackupRestore(runner=runner).restore(valid_archive, confirm_replace=True)

    assert runner.commands.count(STOP_COMMAND) == 2
    assert START_COMMAND not in runner.commands
    assert capsys.readouterr().err == (
        f"Restore failed; all runtime services remain stopped.\nRecovery command: {RECOVERY_COMMAND}\n"
    )


def test_restore_interrupt_restops_services_and_prints_recovery_command(
    valid_archive: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class InterruptRunner(FakeRunner):
        def run(self, command, *, output_path=None, input_path=None):
            result = super().run(
                command,
                output_path=output_path,
                input_path=input_path,
            )
            if list(command) == START_COMMAND:
                raise KeyboardInterrupt
            return result

    runner = InterruptRunner()

    with pytest.raises(KeyboardInterrupt):
        BackupRestore(runner=runner).restore(valid_archive, confirm_replace=True)

    assert runner.commands.count(STOP_COMMAND) == 2
    assert capsys.readouterr().err == (
        f"Restore failed; all runtime services remain stopped.\nRecovery command: {RECOVERY_COMMAND}\n"
    )


def test_restore_does_not_claim_services_are_stopped_when_stop_cannot_be_confirmed(
    valid_archive: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = FakeRunner(fail_when=lambda command: command[:3] == ["docker", "compose", "stop"])

    with pytest.raises(BackupRestoreError, match="injected command failure"):
        BackupRestore(runner=runner).restore(valid_archive, confirm_replace=True)

    stderr = capsys.readouterr().err
    assert "could not confirm stopped services" in stderr
    assert "runtime service stop state could not be confirmed" in stderr
    assert "all runtime services remain stopped" not in stderr
    assert f"Recovery command: {RECOVERY_COMMAND}" in stderr


def test_restore_falls_back_to_stopping_each_service_after_aggregate_stop_failure(
    valid_archive: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = FakeRunner(fail_when=lambda command: command == STOP_COMMAND)

    with pytest.raises(BackupRestoreError, match="injected command failure"):
        BackupRestore(runner=runner).restore(valid_archive, confirm_replace=True)

    for service in RUNTIME_SERVICES:
        assert ["docker", "compose", "stop", service] in runner.commands
    stderr = capsys.readouterr().err
    assert "could not confirm stopped services" in stderr
    assert "all runtime services remain stopped" in stderr
    assert "stop state could not be confirmed" not in stderr


def test_cli_help_lists_backup_verify_and_restore(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "backup" in output
    assert "verify" in output
    assert "restore" in output
    assert "--confirm-replace" in output
