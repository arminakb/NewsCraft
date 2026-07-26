from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/dependency_inventory.py"


def _module():
    spec = importlib.util.spec_from_file_location("dependency_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dependency_inventory_is_deterministic_and_contains_only_pinned_images() -> None:
    module = _module()
    first = module.build_inventory(ROOT)
    second = module.build_inventory(ROOT)

    assert first == second
    assert first["format"] == "newscraft-dependency-inventory-v1"
    assert first["python"]["count"] > 0
    assert first["node"]["count"] > 0
    assert len(first["python"]["sha256"]) == 64
    assert len(first["node"]["sha256"]) == 64
    assert first["images"]
    assert all("@sha256:" in image for image in first["images"])
    assert "secret" not in json.dumps(first).lower()
