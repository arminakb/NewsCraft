#!/usr/bin/env python3
"""Export NewsCraft's deterministic public OpenAPI contract without lifespan startup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.main import app

CONTRACT_SCHEMA = "newscraft-openapi-v1"


def build_openapi() -> dict[str, Any]:
    schema = app.openapi()
    schema["x-newscraft-contract"] = {
        "schema": CONTRACT_SCHEMA,
        "source": "backend/app/main.py",
    }
    return schema


def render_openapi() -> str:
    return json.dumps(build_openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_openapi(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
