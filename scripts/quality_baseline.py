#!/usr/bin/env python3
"""Report the refactor's reproducible production-size and static-analysis baseline."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
FRONTEND_SOURCE_DIRS = ("app", "components", "features", "lib")
GENERATED_FRONTEND_FILES = {Path("lib/api/generated.ts")}


@dataclass(frozen=True)
class CheckResult:
    name: str
    command: str
    available: bool
    returncode: int | None
    findings: int | None
    summary: str


def source_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix in suffixes)


def backend_files(root: Path = ROOT) -> list[Path]:
    return source_files(root / "backend/app", (".py",))


def frontend_files(root: Path = ROOT) -> list[Path]:
    frontend = root / "frontend"
    files: list[Path] = []
    for directory in FRONTEND_SOURCE_DIRS:
        for path in source_files(frontend / directory, (".ts", ".tsx")):
            if path.relative_to(frontend) not in GENERATED_FRONTEND_FILES:
                files.append(path)
    return sorted(files)


def line_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def size_metrics(files: Sequence[Path], thresholds: Sequence[int], root: Path = ROOT) -> dict[str, object]:
    sizes = [(path.relative_to(root).as_posix(), line_count(path)) for path in files]
    sizes.sort(key=lambda item: (-item[1], item[0]))
    return {
        "files": len(sizes),
        "lines": sum(size for _, size in sizes),
        "thresholds": {
            str(threshold): [{"path": path, "lines": size} for path, size in sizes if size >= threshold]
            for threshold in thresholds
        },
    }


def _run(command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str] | None:
    executable = Path(command[0])
    if (executable.is_absolute() or "/" in command[0]) and not executable.exists():
        return None
    try:
        return subprocess.run(command, cwd=cwd, capture_output=True, check=False, text=True)
    except FileNotFoundError:
        return None


def _ruff_check(name: str, selectors: str | None = None, root: Path = ROOT) -> CheckResult:
    executable = root / "backend/.venv/bin/ruff"
    command = [str(executable), "check", "app"]
    if selectors is None:
        command.append("tests")
    else:
        command.extend(("--select", selectors))
    command.extend(("--output-format", "json"))
    completed = _run(command, cwd=root / "backend")
    display = " ".join(command)
    if completed is None:
        return CheckResult(name, display, False, None, None, "backend/.venv/bin/ruff is unavailable")
    try:
        parsed = json.loads(completed.stdout or "[]")
        findings = len(parsed) if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        findings = None
    return CheckResult(
        name,
        display,
        True,
        completed.returncode,
        findings,
        _last_line(completed.stderr),
    )


def _ts_unused(root: Path = ROOT) -> CheckResult:
    executable = root / "frontend/node_modules/.bin/tsc"
    command = [
        str(executable),
        "--noEmit",
        "--incremental",
        "false",
        "--noUnusedLocals",
        "--noUnusedParameters",
    ]
    completed = _run(command, cwd=root / "frontend")
    display = " ".join(command)
    if completed is None:
        return CheckResult(
            "TypeScript unused code",
            display,
            False,
            None,
            None,
            "frontend/node_modules/.bin/tsc is unavailable",
        )
    findings = len(re.findall(r"\berror TS\d+:", completed.stdout + completed.stderr))
    return CheckResult(
        "TypeScript unused code",
        display,
        True,
        completed.returncode,
        findings,
        _last_line(completed.stdout),
    )


def _mypy(root: Path = ROOT) -> CheckResult:
    executable = root / "backend/.venv/bin/mypy"
    command = [
        str(executable),
        "app",
        "--no-incremental",
        "--no-pretty",
        "--show-error-codes",
    ]
    completed = _run(command, cwd=root / "backend")
    display = " ".join(command)
    if completed is None:
        return CheckResult(
            name="Full backend mypy",
            command=display,
            available=False,
            returncode=None,
            findings=None,
            summary="backend/.venv/bin/mypy is unavailable",
        )
    output = completed.stdout + completed.stderr
    match = re.search(r"Found (\d+) errors? in (\d+) files?", output)
    findings = int(match.group(1)) if match else (0 if completed.returncode == 0 else None)
    summary = match.group(0) if match else _last_line(output)
    return CheckResult("Full backend mypy", display, True, completed.returncode, findings, summary)


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def collect_baseline(*, run_checks: bool, root: Path = ROOT) -> dict[str, object]:
    baseline: dict[str, object] = {
        "format": "newscraft-quality-baseline-v1",
        "backend": size_metrics(backend_files(root), (500, 1000), root),
        "frontend": size_metrics(frontend_files(root), (300, 500), root),
    }
    if run_checks:
        checks = [
            _ruff_check("Normal Ruff", root=root),
            _ruff_check("Ruff complex functions", "C901", root=root),
            _ruff_check("Ruff excessive statements", "PLR0915", root=root),
            _ts_unused(root),
            _mypy(root),
        ]
        baseline["checks"] = [
            {
                "name": result.name,
                "command": result.command,
                "available": result.available,
                "returncode": result.returncode,
                "findings": result.findings,
                "summary": result.summary,
            }
            for result in checks
        ]
    return baseline


def render_markdown(baseline: dict[str, object]) -> str:
    backend = baseline["backend"]
    frontend = baseline["frontend"]
    assert isinstance(backend, dict)
    assert isinstance(frontend, dict)
    lines = [
        "# NewsCraft quality baseline",
        "",
        "| Measure | Result |",
        "| --- | ---: |",
        f"| Backend application | {backend['lines']:,} lines across {backend['files']} Python files |",
        f"| Handwritten frontend | {frontend['lines']:,} lines across {frontend['files']} TS/TSX files |",
    ]
    for label, metrics, thresholds in (
        ("Backend", backend, ("500", "1000")),
        ("Frontend", frontend, ("300", "500")),
    ):
        groups = metrics["thresholds"]
        assert isinstance(groups, dict)
        for threshold in thresholds:
            items = groups[threshold]
            lines.append(f"| {label} files at least {threshold} lines | {len(items)} |")
    checks = baseline.get("checks")
    if isinstance(checks, list):
        lines.extend(
            (
                "",
                "## Static analysis",
                "",
                "| Check | Findings | Exit |",
                "| --- | ---: | ---: |",
            )
        )
        for check in checks:
            assert isinstance(check, dict)
            findings = check["findings"] if check["findings"] is not None else "unavailable"
            returncode = check["returncode"] if check["returncode"] is not None else "n/a"
            lines.append(f"| {check['name']} | {findings} | {returncode} |")
        lines.extend(
            (
                "",
                "Complexity, strict-unused, and full-backend mypy findings are informational "
                "during the initial baseline.",
                "The command exits successfully after reporting them so existing debt does not "
                "become blocking accidentally.",
            )
        )
    lines.extend(("", "## Largest files", ""))
    for label, metrics in (("Backend", backend), ("Frontend", frontend)):
        groups = metrics["thresholds"]
        assert isinstance(groups, dict)
        lowest_threshold = "500" if label == "Backend" else "300"
        lines.append(f"### {label}")
        lines.append("")
        for item in groups[lowest_threshold]:
            lines.append(f"- `{item['path']}` — {item['lines']:,} lines")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help="Skip installed-tool static analysis",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    parser.add_argument("--output", type=Path, help="Write the report to this path instead of stdout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline = collect_baseline(run_checks=not args.metrics_only)
    output = json.dumps(baseline, indent=2, sort_keys=True) + "\n" if args.json else render_markdown(baseline)
    if args.output:
        destination = args.output if args.output.is_absolute() else ROOT / args.output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
