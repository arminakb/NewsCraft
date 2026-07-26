#!/usr/bin/env python3
"""Label-verified cleanup for an existing disposable restore-drill project."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from backup_restore import BackupRestoreError
from restore_drill import (
    COMPOSE_FILES,
    _assert_disposable_project,
    _assert_project_name,
    _compose,
    _run,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely remove a label-verified NewsCraft restore drill")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--api-port", type=int, required=True)
    args = parser.parse_args(argv)
    _assert_project_name(args.project_name)
    repository = Path(__file__).resolve().parents[1]
    os.environ["COMPOSE_PROJECT_NAME"] = args.project_name
    os.environ["COMPOSE_FILE"] = os.pathsep.join(str(repository / name) for name in COMPOSE_FILES)
    os.environ["DRILL_API_PORT"] = str(args.api_port)
    _assert_disposable_project(args.project_name)
    _run(_compose("down", "-v", "--remove-orphans"))
    print(f"Disposable restore drill removed: {args.project_name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BackupRestoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
