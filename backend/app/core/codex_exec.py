from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from app.core.outbound_proxy import OutboundProxyPolicy
from app.core.redaction import redact_secrets
from app.research.schemas import ResearchBudget

MAX_CAPTURE_BYTES = 1024 * 1024
_ALLOWED_ENVIRONMENT = (
    "PATH",
    "CODEX_HOME",
    "OPENAI_API_KEY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "LANG",
    "LC_ALL",
)


class CodexExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        classification: Literal["retryable", "needs_review", "permanent"],
        code: str,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self.classification = classification
        self.code = code
        safe = redact_secrets(dict(metadata or {}))
        self.metadata = safe if isinstance(safe, dict) else {}
        super().__init__(message)

    def add_metadata(self, **metadata: object) -> None:
        safe = redact_secrets({**self.metadata, **metadata})
        self.metadata = safe if isinstance(safe, dict) else {}


@dataclass(frozen=True, slots=True)
class ProcessRunResult:
    exit_code: int
    stdout: str
    stderr: str
    elapsed_ms: int
    structured_output: dict[str, Any] | None = None
    token_usage: dict[str, int] | None = None
    codex_cli_version: str = "unknown"


@dataclass(frozen=True, slots=True)
class CodexExecutionResult:
    structured_output: dict[str, Any]
    raw_text: str
    resolved_model: str
    usage: dict[str, int]
    codex_cli_version: str
    exit_code: int
    elapsed_ms: int
    sanitized_events: list[dict[str, object]]


type ProcessRunner = Callable[..., Awaitable[ProcessRunResult]]


def build_codex_environment(source: Mapping[str, str], *, work_dir: Path) -> dict[str, str]:
    proxy_names = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
    environment = {key: source[key] for key in _ALLOWED_ENVIRONMENT if key not in proxy_names and source.get(key)}
    environment.update(OutboundProxyPolicy.from_environment(source).canonical_environment())
    environment["HOME"] = str(work_dir)
    return environment


async def _default_process_runner(
    *,
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    stdin: str,
    timeout_seconds: int,
    max_output_bytes: int,
    response_schema: dict[str, Any],
    max_input_tokens: int,
    max_output_tokens: int,
) -> ProcessRunResult:
    del response_schema
    started = time.monotonic()
    deadline = started + timeout_seconds
    version_process: Any | None = None
    process: Any | None = None
    cli_version = "unknown"
    captured_bytes = 0
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    environment_secrets = tuple(
        env[key]
        for key in (
            "OPENAI_API_KEY",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "CODEX_HOME",
        )
        if env.get(key)
    )

    def safe_metadata(value: Mapping[str, object]) -> dict[str, object]:
        safe = redact_secrets(dict(value), secrets=environment_secrets)
        return safe if isinstance(safe, dict) else {}

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError
        return value

    async def before_deadline(awaitable):
        return await asyncio.wait_for(awaitable, timeout=remaining())

    async def stop_child(child) -> None:
        if child is None:
            return
        if child.returncode is None:
            child.kill()
        wait_task = asyncio.create_task(child.wait())
        while not wait_task.done():
            try:
                await asyncio.shield(wait_task)
            except asyncio.CancelledError:
                continue

    async def read_stream(
        stream: asyncio.StreamReader,
        chunks: list[bytes],
        *,
        check_usage: bool,
    ) -> None:
        nonlocal captured_bytes
        while chunk := await stream.read(64 * 1024):
            captured_bytes += len(chunk)
            if captured_bytes > max_output_bytes:
                raise CodexExecutionError(
                    "codex output exceeded capture limit",
                    classification="needs_review",
                    code="codex_output_too_large",
                    metadata={"status": "output_too_large"},
                )
            chunks.append(chunk)
            if check_usage:
                usage = _extract_usage(b"".join(chunks).decode("utf-8", errors="replace"))
                if usage and (usage["input_tokens"] > max_input_tokens or usage["output_tokens"] > max_output_tokens):
                    raise CodexExecutionError(
                        "codex token budget exceeded",
                        classification="needs_review",
                        code="codex_token_budget_exceeded",
                        metadata={"status": "over_budget", "usage": usage},
                    )

    try:
        version_process = await before_deadline(
            asyncio.create_subprocess_exec(
                argv[0],
                "--version",
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        )
        version_stdout, _ = await before_deadline(version_process.communicate())
        cli_version = version_stdout[:4096].decode("utf-8", errors="replace").strip() or "unknown"
        process = await before_deadline(
            asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(stdin.encode("utf-8"))
        await before_deadline(process.stdin.drain())
        process.stdin.close()
        await before_deadline(
            asyncio.gather(
                read_stream(process.stdout, stdout_chunks, check_usage=True),
                read_stream(process.stderr, stderr_chunks, check_usage=False),
                process.wait(),
            )
        )
    except TimeoutError:
        current = process or version_process
        await stop_child(current)
        raise CodexExecutionError(
            "codex timed out",
            classification="retryable",
            code="codex_timeout",
            metadata=safe_metadata(
                {
                    "codex_cli_version": cli_version,
                    "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
                    "exit_code": getattr(current, "returncode", None),
                    "status": "timeout",
                }
            ),
        ) from None
    except asyncio.CancelledError:
        await stop_child(process or version_process)
        raise
    except CodexExecutionError as exc:
        await stop_child(process or version_process)
        exc.add_metadata(
            **safe_metadata(
                {
                    "codex_cli_version": cli_version,
                    "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
                    "exit_code": getattr(process or version_process, "returncode", None),
                }
            )
        )
        raise
    finally:
        for child in (process, version_process):
            if child is not None and child.returncode is None:
                await stop_child(child)

    stdout_bytes = b"".join(stdout_chunks)
    stderr_bytes = b"".join(stderr_chunks)
    usage = _extract_usage(stdout_bytes.decode("utf-8", errors="replace"))
    return ProcessRunResult(
        exit_code=process.returncode or 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
        token_usage=usage,
        codex_cli_version=cli_version,
    )


class CodexExecutor:
    def __init__(
        self,
        *,
        process_runner: ProcessRunner = _default_process_runner,
        executable: str,
        timeout_seconds: int | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not executable:
            raise ValueError("codex executable is required")
        self.process_runner = process_runner
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.environment = dict(environment if environment is not None else os.environ)

    async def run(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        budget: ResearchBudget,
        *,
        resolved_model: str,
        allow_web: bool,
    ) -> CodexExecutionResult:
        if not resolved_model:
            raise CodexExecutionError(
                "codex model is required",
                classification="permanent",
                code="codex_model_missing",
            )
        if budget.max_model_calls != 1:
            raise CodexExecutionError(
                "codex permits exactly one model call",
                classification="permanent",
                code="codex_model_call_budget_invalid",
            )
        try:
            Draft202012Validator.check_schema(response_schema)
        except SchemaError:
            raise CodexExecutionError(
                "codex response schema is invalid",
                classification="permanent",
                code="codex_schema_invalid",
            ) from None

        with tempfile.TemporaryDirectory(prefix="newscraft-codex-") as temporary:
            work_dir = Path(temporary).resolve()
            schema_path = (work_dir / "response-schema.json").resolve()
            result_path = (work_dir / "result.json").resolve()
            schema_path.write_text(
                json.dumps(response_schema, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            disabled_features = [
                "shell_tool",
                "code_mode_host",
                "computer_use",
                "apps",
                "browser_use_external",
                "browser_use_full_cdp_access",
            ]
            feature_args = [item for feature in disabled_features for item in ("--disable", feature)]
            feature_args += ["--enable", "browser_use"] if allow_web else ["--disable", "browser_use"]
            argv = [
                self.executable,
                "exec",
                "--ephemeral",
                "--json",
                "--model",
                resolved_model,
                "--output-schema",
                str(schema_path),
                "--sandbox",
                "read-only",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--ignore-rules",
                "-c",
                'shell_environment_policy.inherit="none"',
                *feature_args,
                "-C",
                str(work_dir),
                "-o",
                str(result_path),
                "-",
            ]
            timeout_seconds = self.timeout_seconds or budget.max_elapsed_seconds
            codex_environment = build_codex_environment(self.environment, work_dir=work_dir)
            event_secrets = tuple(
                codex_environment[key]
                for key in (
                    "OPENAI_API_KEY",
                    "HTTP_PROXY",
                    "HTTPS_PROXY",
                    "ALL_PROXY",
                    "CODEX_HOME",
                )
                if codex_environment.get(key)
            )

            async def stop_injected_runner() -> None:
                terminate = getattr(self.process_runner, "terminate", None)
                if callable(terminate):
                    terminated = terminate()
                    if isinstance(terminated, Awaitable):
                        await terminated
                wait = getattr(self.process_runner, "wait", None)
                if callable(wait):
                    waited = wait()
                    if isinstance(waited, Awaitable):
                        await asyncio.shield(waited)

            try:
                result = await asyncio.wait_for(
                    self.process_runner(
                        argv=argv,
                        cwd=work_dir,
                        env=codex_environment,
                        stdin=f"{prompt.rstrip()}\n",
                        timeout_seconds=timeout_seconds,
                        max_output_bytes=MAX_CAPTURE_BYTES,
                        response_schema=response_schema,
                        max_input_tokens=budget.max_input_tokens,
                        max_output_tokens=budget.max_output_tokens,
                    ),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                await stop_injected_runner()
                raise CodexExecutionError(
                    "codex timed out",
                    classification="retryable",
                    code="codex_timeout",
                    metadata={"status": "timeout"},
                ) from None
            except asyncio.CancelledError:
                await stop_injected_runner()
                raise
            safe_process_metadata = redact_secrets(
                {
                    "codex_cli_version": result.codex_cli_version,
                    "elapsed_ms": result.elapsed_ms,
                    "exit_code": result.exit_code,
                },
                secrets=event_secrets,
            )
            process_metadata = safe_process_metadata if isinstance(safe_process_metadata, dict) else {}
            safe_cli_version = str(process_metadata.get("codex_cli_version", "unknown"))
            if len(result.stdout.encode()) + len(result.stderr.encode()) > MAX_CAPTURE_BYTES:
                raise CodexExecutionError(
                    "codex output exceeded capture limit",
                    classification="needs_review",
                    code="codex_output_too_large",
                    metadata={**process_metadata, "status": "output_too_large"},
                )
            if result.exit_code != 0:
                raise CodexExecutionError(
                    "codex execution failed",
                    classification="retryable",
                    code="codex_process_failed",
                    metadata={**process_metadata, "status": "process_failed"},
                )
            raw_text = (
                result_path.read_text(encoding="utf-8")
                if result_path.exists()
                else json.dumps(
                    result.structured_output,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if result.structured_output is not None
                else ""
            )
            if len(raw_text.encode("utf-8")) > MAX_CAPTURE_BYTES:
                raise CodexExecutionError(
                    "codex result exceeded capture limit",
                    classification="needs_review",
                    code="codex_result_too_large",
                    metadata={**process_metadata, "status": "result_too_large"},
                )
            try:
                structured_output = result.structured_output or json.loads(raw_text)
                Draft202012Validator(response_schema).validate(structured_output)
                safe_structured_output = redact_secrets(
                    structured_output,
                    secrets=event_secrets,
                )
                Draft202012Validator(response_schema).validate(safe_structured_output)
            except json.JSONDecodeError, ValidationError:
                raise CodexExecutionError(
                    "codex structured output is invalid",
                    classification="needs_review",
                    code="codex_output_invalid",
                    metadata={**process_metadata, "status": "invalid_output"},
                ) from None
            if not isinstance(safe_structured_output, dict):
                raise CodexExecutionError(
                    "codex structured output is invalid",
                    classification="needs_review",
                    code="codex_output_invalid",
                    metadata={**process_metadata, "status": "invalid_output"},
                )
            safe_raw_text = json.dumps(
                safe_structured_output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if len(safe_raw_text.encode("utf-8")) > MAX_CAPTURE_BYTES:
                raise CodexExecutionError(
                    "codex result exceeded capture limit",
                    classification="needs_review",
                    code="codex_result_too_large",
                    metadata={**process_metadata, "status": "result_too_large"},
                )
            usage = result.token_usage or _extract_usage(result.stdout)
            if not usage or not {"input_tokens", "output_tokens"} <= usage.keys():
                raise CodexExecutionError(
                    "codex token usage is missing",
                    classification="needs_review",
                    code="codex_usage_missing",
                    metadata={**process_metadata, "status": "usage_missing", "usage": None},
                )
            if usage["input_tokens"] > budget.max_input_tokens or usage["output_tokens"] > budget.max_output_tokens:
                raise CodexExecutionError(
                    "codex token budget exceeded",
                    classification="needs_review",
                    code="codex_token_budget_exceeded",
                    metadata={**process_metadata, "status": "over_budget", "usage": usage},
                )
            sanitized_events = _safe_events(result.stdout, secrets=event_secrets)
            sanitized_events.append(
                {
                    "type": "codex_process",
                    "codex_cli_version": safe_cli_version,
                    "exit_code": result.exit_code,
                    "elapsed_ms": result.elapsed_ms,
                    "token_usage": {
                        "input_tokens": usage["input_tokens"],
                        "output_tokens": usage["output_tokens"],
                    },
                }
            )
            safe_resolved_model = redact_secrets(
                resolved_model,
                secrets=event_secrets,
            )
            return CodexExecutionResult(
                structured_output=safe_structured_output,
                raw_text=safe_raw_text,
                resolved_model=(safe_resolved_model if isinstance(safe_resolved_model, str) else "[REDACTED]"),
                usage={
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                },
                codex_cli_version=safe_cli_version,
                exit_code=result.exit_code,
                elapsed_ms=result.elapsed_ms,
                sanitized_events=sanitized_events,
            )


def _safe_events(stdout: str, *, secrets: tuple[str, ...] = ()) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            redacted = redact_secrets(item, secrets=secrets)
            if isinstance(redacted, dict):
                safe = {key: redacted[key] for key in ("type", "event", "status", "code", "usage") if key in redacted}
                if safe:
                    events.append(safe)
    return events


def _extract_usage(stdout: str) -> dict[str, int] | None:
    total_input = 0
    total_output = 0
    found = False
    for event in _safe_events(stdout):
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            total_input += input_tokens
            total_output += output_tokens
            found = True
    return {"input_tokens": total_input, "output_tokens": total_output} if found else None


__all__ = [
    "CodexExecutionError",
    "CodexExecutionResult",
    "CodexExecutor",
    "MAX_CAPTURE_BYTES",
    "ProcessRunResult",
    "build_codex_environment",
]
