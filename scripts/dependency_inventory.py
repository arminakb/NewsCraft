#!/usr/bin/env python3
"""Emit a deterministic, secret-free inventory of locked dependencies and image inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IMAGE_PATTERN = re.compile(r"(?:python|node|postgres|ghcr\.io/astral-sh/uv):[^\s\"']+@sha256:[0-9a-f]{64}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_inventory(root: Path = ROOT) -> dict[str, Any]:
    uv_lock_path = root / "backend/uv.lock"
    npm_lock_path = root / "frontend/package-lock.json"
    uv_lock = tomllib.loads(uv_lock_path.read_text(encoding="utf-8"))
    npm_lock = json.loads(npm_lock_path.read_text(encoding="utf-8"))

    python_packages = sorted(
        (
            {"name": package["name"], "version": package["version"]}
            for package in uv_lock["package"]
            if "version" in package
        ),
        key=lambda package: (package["name"], package["version"]),
    )
    node_packages = sorted(
        (
            {"path": path, "version": package["version"]}
            for path, package in npm_lock["packages"].items()
            if path and "version" in package and not package.get("link")
        ),
        key=lambda package: (package["path"], package["version"]),
    )

    image_text = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in (
            "backend/Dockerfile",
            "frontend/Dockerfile",
            "operations/backup.Dockerfile",
            "docker-compose.yml",
        )
    )
    images = sorted(set(IMAGE_PATTERN.findall(image_text)))

    python_payload = json.dumps(python_packages, sort_keys=True, separators=(",", ":")).encode()
    node_payload = json.dumps(node_packages, sort_keys=True, separators=(",", ":")).encode()
    return {
        "format": "newscraft-dependency-inventory-v1",
        "inputs": {
            "backend/pyproject.toml": sha256(root / "backend/pyproject.toml"),
            "backend/uv.lock": sha256(uv_lock_path),
            "frontend/package.json": sha256(root / "frontend/package.json"),
            "frontend/package-lock.json": sha256(npm_lock_path),
            "operations/backup.Dockerfile": sha256(root / "operations/backup.Dockerfile"),
        },
        "python": {
            "count": len(python_packages),
            "sha256": hashlib.sha256(python_payload).hexdigest(),
            "packages": python_packages,
        },
        "node": {
            "count": len(node_packages),
            "sha256": hashlib.sha256(node_payload).hexdigest(),
            "packages": node_packages,
        },
        "images": images,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(build_inventory(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
