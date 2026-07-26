from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
DIGEST_PIN = re.compile(r"@sha256:[0-9a-f]{64}$")


def _locked_requirement(entry: dict[str, object]) -> str:
    extras = entry.get("extras", [])
    extra_text = f"[{','.join(extras)}]" if extras else ""
    return str(Requirement(f"{entry['name']}{extra_text}{entry.get('specifier', '')}"))


def test_backend_has_one_current_lock_and_explicit_dev_group() -> None:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((BACKEND / "uv.lock").read_text(encoding="utf-8"))

    assert project["project"]["requires-python"] == ">=3.14,<3.15"
    assert project["tool"]["uv"]["required-version"] == "==0.11.29"
    assert set(project["dependency-groups"]) == {"dev"}
    assert {"mypy", "packaging", "pip-audit", "pytest", "pytest-asyncio", "pytest-cov", "ruff"} <= {
        requirement.split("<", 1)[0].split(">", 1)[0].split("=", 1)[0]
        for requirement in project["dependency-groups"]["dev"]
    }
    assert lock["requires-python"] == "==3.14.*"
    assert any(package["name"] == "newscraft-backend" for package in lock["package"])


def test_backend_lock_metadata_matches_intent_and_detects_a_deliberate_mismatch() -> None:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((BACKEND / "uv.lock").read_text(encoding="utf-8"))
    root = next(package for package in lock["package"] if package["name"] == "newscraft-backend")

    runtime_intent = {str(Requirement(requirement)) for requirement in project["project"]["dependencies"]}
    dev_intent = {str(Requirement(requirement)) for requirement in project["dependency-groups"]["dev"]}
    locked_runtime = {_locked_requirement(requirement) for requirement in root["metadata"]["requires-dist"]}
    locked_dev = {_locked_requirement(requirement) for requirement in root["metadata"]["requires-dev"]["dev"]}

    assert runtime_intent == locked_runtime
    assert dev_intent == locked_dev
    assert runtime_intent | {"deliberate-lock-mismatch>=1"} != locked_runtime


def test_frontend_direct_dependencies_are_exact_and_match_lock_root() -> None:
    manifest = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    locked_root = lock["packages"][""]

    for section in ("dependencies", "devDependencies"):
        assert manifest[section] == locked_root[section]
        assert all(EXACT_VERSION.fullmatch(version) for version in manifest[section].values())

    assert manifest["packageManager"] == "npm@11.17.0"
    assert manifest["engines"] == {"node": "26.4.0", "npm": "11.17.0"}


def test_production_images_are_patch_and_digest_pinned() -> None:
    backend_dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    frontend_dockerfile = (FRONTEND / "Dockerfile").read_text(encoding="utf-8")
    backup_dockerfile = (ROOT / "operations/backup.Dockerfile").read_text(encoding="utf-8")
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

    backend_images = re.findall(r"^ARG \w+_IMAGE=((?:python|ghcr\.io/astral-sh/uv):[^\s]+)$", backend_dockerfile, re.M)
    frontend_images = re.findall(r"^ARG \w+_IMAGE=(node:[^\s]+)$", frontend_dockerfile, re.M)
    postgres_images = [compose["services"][name]["image"] for name in ("postgres", "postgres-test")]
    backup_images = re.findall(r"^ARG \w+_IMAGE=(postgres:[^\s]+)$", backup_dockerfile, re.M)

    assert backend_images and all(DIGEST_PIN.search(image) for image in backend_images)
    assert frontend_images and all(DIGEST_PIN.search(image) for image in frontend_images)
    assert all(DIGEST_PIN.search(image) for image in postgres_images)
    assert backup_images and all(DIGEST_PIN.search(image) for image in backup_images)
    assert "age=1.1.1-1+b3" in backup_dockerfile


def test_backend_runtime_is_frozen_non_editable_and_excludes_dev_tools() -> None:
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")

    assert "uv sync --locked --no-dev --no-install-project" in dockerfile
    assert "uv sync --locked --no-dev --no-editable --reinstall-package newscraft-backend" in dockerfile
    assert "USER newscraft" in dockerfile
    assert "pip install" not in dockerfile
    assert ".[dev]" not in dockerfile


def test_frontend_image_uses_frozen_install_and_non_root_runtime() -> None:
    dockerfile = (FRONTEND / "Dockerfile").read_text(encoding="utf-8")

    assert "RUN npm ci" in dockerfile
    assert "npm install" not in dockerfile
    assert "USER node" in dockerfile


def test_repository_toolchain_versions_are_explicit() -> None:
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.14.6"
    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == "26.4.0"
