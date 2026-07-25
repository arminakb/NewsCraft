from __future__ import annotations

import hashlib
import hmac
import io
import json
import stat
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import restore_drill  # noqa: E402
from backup_restore import BackupRestoreError  # noqa: E402


@pytest.mark.parametrize(
    "project_name",
    ["newscraft", "default", "newscraft-restore-drill", "newscraft-restore-drill-../../primary"],
)
def test_drill_rejects_non_disposable_project_names(project_name: str) -> None:
    with pytest.raises(BackupRestoreError, match="project name"):
        restore_drill._assert_project_name(project_name)


def test_drill_accepts_only_a_strict_disposable_project_name() -> None:
    restore_drill._assert_project_name("newscraft-restore-drill-20260719-a")


def test_cleanup_refuses_a_container_without_the_exact_compose_project_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command, *, output_path=None):
        del output_path
        if command == ["docker", "compose", "ps", "-q"]:
            return "container-1"
        return "newscraft"

    monkeypatch.setattr(restore_drill, "_run", fake_run)

    with pytest.raises(BackupRestoreError, match="refusing cleanup"):
        restore_drill._assert_disposable_project("newscraft-restore-drill-20260719-a")


def test_report_is_private_and_hmac_signed(tmp_path: Path) -> None:
    report_path = tmp_path / "drill.json"
    key = b"k" * 32
    restore_drill._write_signed_report({"status": "passed"}, report_path, key)

    payload = report_path.read_bytes()
    signature = report_path.with_suffix(".json.hmac-sha256").read_text(encoding="ascii").strip()
    assert hmac.compare_digest(signature, hmac.new(key, payload, hashlib.sha256).hexdigest())
    assert json.loads(payload) == {"status": "passed"}
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(report_path.with_suffix(".json.hmac-sha256").stat().st_mode) == 0o600


def test_canary_scan_counts_nested_file_content_without_printing_it(tmp_path: Path) -> None:
    canary = b"private-canary-value"
    archive_path = tmp_path / "content.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        member = tarfile.TarInfo("./payload.txt")
        member.size = len(canary) * 2
        archive.addfile(member, io.BytesIO(canary * 2))

    assert restore_drill._canary_count_in_tar(archive_path, canary) == 2


def test_drill_override_removes_primary_ports_and_live_authority() -> None:
    override = (ROOT / "docker-compose.restore-drill.yml").read_text(encoding="utf-8")
    assert "ports: !reset []" in override
    assert "GENERATION_PROVIDER: fake" in override
    assert "TELEGRAM_PUBLISH_MODE: dry-run" in override
    for secret_name in (
        "OPENROUTER_API_KEY",
        "TELEGRAM_SOURCE_EDITOR_API_ID",
        "TELEGRAM_SOURCE_EDITOR_API_HASH",
        "TELEGRAM_SOURCE_EDITOR_SESSION",
        "TELEGRAM_DESTINATION_NEWS_TOKEN",
    ):
        assert f'{secret_name}: ""' in override
