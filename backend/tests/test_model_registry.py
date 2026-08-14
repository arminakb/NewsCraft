"""Guard: importing ``app.db.model_registry`` must register every mapped class.

``alembic/env.py`` autogenerates migrations against ``Base.metadata``, which is
populated purely by the import block in ``app.db.model_registry``. A model
module that no import pulls in is therefore absent from the metadata and
``alembic revision --autogenerate`` would emit ``DROP TABLE`` for its tables.
These tests fail loudly the moment that happens.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"

_PROBE = """
import importlib
import json
import sys

from app.db.model_registry import Base

registered = sorted(Base.metadata.tables)
missing_modules = []
for name in sys.argv[1:]:
    was_imported = name in sys.modules
    module = importlib.import_module(name)
    defines_mapped_class = any(
        isinstance(value, type)
        and issubclass(value, Base)
        and value is not Base
        and value.__module__ == name
        for value in vars(module).values()
    )
    if defines_mapped_class and not was_imported:
        missing_modules.append(name)

print(
    json.dumps(
        {
            "registered": registered,
            "after_import": sorted(Base.metadata.tables),
            "missing_modules": missing_modules,
        }
    )
)
"""


def _model_modules() -> list[str]:
    modules: list[str] = []
    for path in sorted(APP_ROOT.rglob("models.py")):
        relative = path.relative_to(BACKEND_ROOT).with_suffix("")
        modules.append(".".join(relative.parts))
    return modules


def _probe(modules: list[str]) -> dict[str, list[str]]:
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, *modules],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_model_modules_are_discovered() -> None:
    modules = _model_modules()
    assert "app.db.models" in modules
    assert "app.stories.models" in modules
    assert "app.automations.definitions.models" in modules
    assert len(modules) > 10


def test_model_registry_imports_every_model_module() -> None:
    modules = _model_modules()
    result = _probe(modules)
    assert result["missing_modules"] == [], (
        "app/db/model_registry.py does not import these model modules, so their tables are "
        "absent from Base.metadata and alembic autogenerate would drop them: "
        f"{result['missing_modules']}"
    )


def test_model_registry_metadata_is_complete() -> None:
    modules = _model_modules()
    result = _probe(modules)
    extra = sorted(set(result["after_import"]) - set(result["registered"]))
    assert extra == [], (
        "importing the model modules directly registered tables that "
        "app.db.model_registry does not: " + ", ".join(extra)
    )
