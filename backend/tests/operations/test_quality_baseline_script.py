from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/quality_baseline.py"


def _module():
    spec = importlib.util.spec_from_file_location("quality_baseline", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_quality_baseline_counts_only_handwritten_production_files(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_text("one\ntwo\n", encoding="utf-8")
    (tmp_path / "backend/tests").mkdir()
    (tmp_path / "backend/tests/test_main.py").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "frontend/app").mkdir(parents=True)
    (tmp_path / "frontend/app/page.tsx").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (tmp_path / "frontend/lib/api").mkdir(parents=True)
    (tmp_path / "frontend/lib/api/generated.ts").write_text("generated\n", encoding="utf-8")
    (tmp_path / "frontend/tests").mkdir()
    (tmp_path / "frontend/tests/page.test.tsx").write_text("ignored\n", encoding="utf-8")

    baseline = module.collect_baseline(run_checks=False, root=tmp_path)

    assert baseline["format"] == "newscraft-quality-baseline-v1"
    assert baseline["backend"]["files"] == 1
    assert baseline["backend"]["lines"] == 2
    assert baseline["frontend"]["files"] == 1
    assert baseline["frontend"]["lines"] == 3
    assert "checks" not in baseline


def test_quality_baseline_collects_the_current_repository() -> None:
    module = _module()

    baseline = module.collect_baseline(run_checks=False)

    assert baseline["backend"]["files"] > 0
    assert baseline["backend"]["lines"] > 0
    assert set(baseline["backend"]["thresholds"]) == {"500", "1000"}
    assert baseline["frontend"]["files"] > 0
    assert baseline["frontend"]["lines"] > 0
    assert set(baseline["frontend"]["thresholds"]) == {"300", "500"}


def test_quality_gate_rejects_missing_tools_and_budget_regressions() -> None:
    module = _module()
    checks = [
        {
            "name": name,
            "available": True,
            "findings": budget,
        }
        for name, budget in module.CHECK_FINDING_BUDGETS.items()
    ]

    assert module.quality_gate_failures({"checks": checks}) == []

    checks[0]["available"] = False
    checks[1]["findings"] += 1
    assert module.quality_gate_failures({"checks": checks}) == [
        "Normal Ruff: tool is unavailable",
        "Ruff complex functions: 54 findings exceeds budget 53",
    ]
