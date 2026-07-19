from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_PATH = ROOT / ".github/workflows/ci.yml"
NIGHTLY_PATH = ROOT / ".github/workflows/nightly.yml"
BLOCKING_JOBS = {
    "backend-static",
    "backend-unit",
    "backend-postgres",
    "migrations",
    "frontend",
    "contracts",
    "compose-and-images",
    "security",
    "browser-mocked",
}
LIVE_SECRET_NAMES = {
    "OPENROUTER_API_KEY",
    "TELEGRAM_SOURCE_EDITOR_API_ID",
    "TELEGRAM_SOURCE_EDITOR_API_HASH",
    "TELEGRAM_SOURCE_EDITOR_SESSION",
    "TELEGRAM_DESTINATION_NEWS_TOKEN",
}


def _workflow(path: Path) -> dict[str, object]:
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _trigger(workflow: dict[str, object]) -> object:
    # PyYAML 1.1 treats the unquoted GitHub Actions key `on` as boolean true.
    return workflow.get("on", workflow.get(True))


def test_ci_has_explicit_required_release_gate_and_safe_permissions() -> None:
    workflow = _workflow(CI_PATH)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert BLOCKING_JOBS <= set(jobs)
    gate = jobs["release-gate"]
    assert set(gate["needs"]) == BLOCKING_JOBS
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert set(_trigger(workflow)) == {"pull_request", "push", "workflow_dispatch"}


def test_pull_request_jobs_never_reference_live_provider_secrets() -> None:
    text = CI_PATH.read_text(encoding="utf-8")
    assert "secrets." not in text
    for name in LIVE_SECRET_NAMES:
        assert f"{name}: ${{{{" not in text


def test_ci_uses_frozen_installs_test_database_guard_and_retained_artifacts() -> None:
    text = CI_PATH.read_text(encoding="utf-8")
    assert "uv sync --locked" in text
    assert "npm ci" in text
    assert "newscraft_test" in text
    assert "newscraft_migration_test" in text
    assert "retention-days: 30" in text
    assert "gitleaks/gitleaks-action" in text
    assert "npm audit --audit-level=high" in text
    assert "anchore/sbom-action" in text
    assert text.count("aquasecurity/trivy-action") == 2
    assert (ROOT / "frontend/next-env.d.ts").read_text(encoding="utf-8").splitlines()[2] == (
        'import "./.next/types/routes.d.ts";'
    )


def test_nightly_has_real_stack_restart_restore_and_large_list_drills() -> None:
    workflow = _workflow(NIGHTLY_PATH)
    jobs = workflow["jobs"]
    assert set(jobs) == {"no-mock-stack", "backup-restore-contract", "large-list-budget"}
    assert set(_trigger(workflow)) == {"schedule", "workflow_dispatch"}
    text = NIGHTLY_PATH.read_text(encoding="utf-8")
    assert "scripts/smoke.py" in text
    assert "kill worker-source-generation" in text
    assert "test_backup_restore_script.py" in text
    assert "story-inbox.test.tsx" in text
    assert "retention-days: 30" in text
