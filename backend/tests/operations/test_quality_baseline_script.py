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


def test_quality_baseline_matches_the_committed_plan_definition() -> None:
    module = _module()

    baseline = module.collect_baseline(run_checks=False)

    assert baseline["backend"]["files"] == 218
    assert baseline["backend"]["lines"] == 51_060
    assert baseline["frontend"]["files"] == 115
    assert baseline["frontend"]["lines"] == 16_858
