from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
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


def _environment_secrets(environment: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        environment[key]
        for key in ("OPENAI_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "CODEX_HOME")
        if environment.get(key)
    )


@dataclass(slots=True)
class _ProcessState:
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    stdin: str
    started: float
    deadline: float
    max_output_bytes: int
    max_input_tokens: int
    max_output_tokens: int
    version_process: Any | None = None
    process: Any | None = None
    cli_version: str = "unknown"
    captured_bytes: int = 0
    stdout_chunks: list[bytes] = field(default_factory=list)
    stderr_chunks: list[bytes] = field(default_factory=list)

    def safe_metadata(self, value: Mapping[str, object]) -> dict[str, object]:
        safe = redact_secrets(dict(value), secrets=_environment_secrets(self.env))
        return safe if isinstance(safe, dict) else {}

    async def before_deadline(self, awaitable):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return await asyncio.wait_for(awaitable, timeout=remaining)

    @staticmethod
    async def stop_child(child: Any | None) -> None:
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

    async def stop_children(self) -> None:
        for child in (self.process, self.version_process):
            if child is not None and child.returncode is None:
                await self.stop_child(child)

    async def read_stream(self, stream: asyncio.StreamReader, chunks: list[bytes], *, check_usage: bool) -> None:
        while chunk := await stream.read(64 * 1024):
            self.captured_bytes += len(chunk)
            if self.captured_bytes > self.max_output_bytes:
                raise CodexExecutionError(
                    "codex output exceeded capture limit",
                    classification="needs_review",
                    code="codex_output_too_large",
                    metadata={"status": "output_too_large"},
                )
            chunks.append(chunk)
            if check_usage:
                self._validate_stream_usage(chunks)

    def _validate_stream_usage(self, chunks: list[bytes]) -> None:
        usage = _extract_usage(b"".join(chunks).decode("utf-8", errors="replace"))
        if usage and (usage["input_tokens"] > self.max_input_tokens or usage["output_tokens"] > self.max_output_tokens):
            raise CodexExecutionError(
                "codex token budget exceeded",
                classification="needs_review",
                code="codex_token_budget_exceeded",
                metadata={"status": "over_budget", "usage": usage},
            )

    async def execute(self) -> None:
        self.version_process = await self.before_deadline(
            asyncio.create_subprocess_exec(
                self.argv[0],
                "--version",
                cwd=self.cwd,
                env=self.env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        )
        version_stdout, _ = await self.before_deadline(self.version_process.communicate())
        self.cli_version = version_stdout[:4096].decode("utf-8", errors="replace").strip() or "unknown"
        self.process = await self.before_deadline(
            asyncio.create_subprocess_exec(
                *self.argv,
                cwd=self.cwd,
                env=self.env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self.process.stdin.write(self.stdin.encode("utf-8"))
        await self.before_deadline(self.process.stdin.drain())
        self.process.stdin.close()
        await self.before_deadline(
            asyncio.gather(
                self.read_stream(self.process.stdout, self.stdout_chunks, check_usage=True),
                self.read_stream(self.process.stderr, self.stderr_chunks, check_usage=False),
                self.process.wait(),
            )
        )

    def result(self) -> ProcessRunResult:
        assert self.process is not None
        stdout_bytes = b"".join(self.stdout_chunks)
        stderr_bytes = b"".join(self.stderr_chunks)
        return ProcessRunResult(
            exit_code=self.process.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            elapsed_ms=max(0, int((time.monotonic() - self.started) * 1000)),
            token_usage=_extract_usage(stdout_bytes.decode("utf-8", errors="replace")),
            codex_cli_version=self.cli_version,
        )


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
    state = _ProcessState(
        argv=argv,
        cwd=cwd,
        env=env,
        stdin=stdin,
        started=started,
        deadline=started + timeout_seconds,
        max_output_bytes=max_output_bytes,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )

    try:
        await state.execute()
    except TimeoutError:
        current = state.process or state.version_process
        await state.stop_child(current)
        raise CodexExecutionError(
            "codex timed out",
            classification="retryable",
            code="codex_timeout",
            metadata=state.safe_metadata(
                {
                    "codex_cli_version": state.cli_version,
                    "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
                    "exit_code": getattr(current, "returncode", None),
                    "status": "timeout",
                }
            ),
        ) from None
    except asyncio.CancelledError:
        await state.stop_child(state.process or state.version_process)
        raise
    except CodexExecutionError as exc:
        await state.stop_child(state.process or state.version_process)
        exc.add_metadata(
            **state.safe_metadata(
                {
                    "codex_cli_version": state.cli_version,
                    "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
                    "exit_code": getattr(state.process or state.version_process, "returncode", None),
                }
            )
        )
        raise
    finally:
        await state.stop_children()

    return state.result()


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
        _validate_codex_request(resolved_model, budget, response_schema)
        with tempfile.TemporaryDirectory(prefix="newscraft-codex-") as temporary:
            work_dir = Path(temporary).resolve()
            invocation = _prepare_codex_invocation(
                executable=self.executable,
                environment=self.environment,
                timeout_seconds=self.timeout_seconds or budget.max_elapsed_seconds,
                work_dir=work_dir,
                response_schema=response_schema,
                resolved_model=resolved_model,
                allow_web=allow_web,
            )
            result = await _invoke_process_runner(
                self.process_runner,
                invocation,
                prompt=prompt,
                response_schema=response_schema,
                budget=budget,
            )
            return _interpret_codex_result(
                result,
                invocation=invocation,
                response_schema=response_schema,
                budget=budget,
                resolved_model=resolved_model,
            )


@dataclass(frozen=True, slots=True)
class _CodexInvocation:
    work_dir: Path
    result_path: Path
    argv: list[str]
    environment: dict[str, str]
    event_secrets: tuple[str, ...]
    timeout_seconds: int


def _validate_codex_request(
    resolved_model: str,
    budget: ResearchBudget,
    response_schema: dict[str, Any],
) -> None:
    if not resolved_model:
        raise CodexExecutionError("codex model is required", classification="permanent", code="codex_model_missing")
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


def _codex_argv(
    executable: str, work_dir: Path, schema_path: Path, result_path: Path, model: str, allow_web: bool
) -> list[str]:
    disabled = (
        "shell_tool",
        "code_mode_host",
        "computer_use",
        "apps",
        "browser_use_external",
        "browser_use_full_cdp_access",
    )
    feature_args = [item for feature in disabled for item in ("--disable", feature)]
    feature_args += ["--enable", "browser_use"] if allow_web else ["--disable", "browser_use"]
    return [
        executable,
        "exec",
        "--ephemeral",
        "--json",
        "--model",
        model,
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


def _prepare_codex_invocation(
    *,
    executable: str,
    environment: Mapping[str, str],
    timeout_seconds: int,
    work_dir: Path,
    response_schema: dict[str, Any],
    resolved_model: str,
    allow_web: bool,
) -> _CodexInvocation:
    schema_path = (work_dir / "response-schema.json").resolve()
    result_path = (work_dir / "result.json").resolve()
    schema_path.write_text(json.dumps(response_schema, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    codex_environment = build_codex_environment(environment, work_dir=work_dir)
    return _CodexInvocation(
        work_dir=work_dir,
        result_path=result_path,
        argv=_codex_argv(executable, work_dir, schema_path, result_path, resolved_model, allow_web),
        environment=codex_environment,
        event_secrets=_environment_secrets(codex_environment),
        timeout_seconds=timeout_seconds,
    )


async def _stop_injected_runner(process_runner: ProcessRunner) -> None:
    for method_name, shield in (("terminate", False), ("wait", True)):
        method = getattr(process_runner, method_name, None)
        if callable(method):
            result = method()
            if isinstance(result, Awaitable):
                if shield:
                    await asyncio.shield(result)
                else:
                    await result


async def _invoke_process_runner(
    process_runner: ProcessRunner,
    invocation: _CodexInvocation,
    *,
    prompt: str,
    response_schema: dict[str, Any],
    budget: ResearchBudget,
) -> ProcessRunResult:
    try:
        return await asyncio.wait_for(
            process_runner(
                argv=invocation.argv,
                cwd=invocation.work_dir,
                env=invocation.environment,
                stdin=f"{prompt.rstrip()}\n",
                timeout_seconds=invocation.timeout_seconds,
                max_output_bytes=MAX_CAPTURE_BYTES,
                response_schema=response_schema,
                max_input_tokens=budget.max_input_tokens,
                max_output_tokens=budget.max_output_tokens,
            ),
            timeout=invocation.timeout_seconds,
        )
    except TimeoutError:
        await _stop_injected_runner(process_runner)
        raise CodexExecutionError(
            "codex timed out",
            classification="retryable",
            code="codex_timeout",
            metadata={"status": "timeout"},
        ) from None
    except asyncio.CancelledError:
        await _stop_injected_runner(process_runner)
        raise


def _process_metadata(result: ProcessRunResult, secrets: tuple[str, ...]) -> dict[str, object]:
    safe = redact_secrets(
        {
            "codex_cli_version": result.codex_cli_version,
            "elapsed_ms": result.elapsed_ms,
            "exit_code": result.exit_code,
        },
        secrets=secrets,
    )
    return safe if isinstance(safe, dict) else {}


def _validate_process_result(result: ProcessRunResult, metadata: dict[str, object]) -> None:
    if len(result.stdout.encode()) + len(result.stderr.encode()) > MAX_CAPTURE_BYTES:
        raise CodexExecutionError(
            "codex output exceeded capture limit",
            classification="needs_review",
            code="codex_output_too_large",
            metadata={**metadata, "status": "output_too_large"},
        )
    if result.exit_code != 0:
        raise CodexExecutionError(
            "codex execution failed",
            classification="retryable",
            code="codex_process_failed",
            metadata={**metadata, "status": "process_failed"},
        )


def _load_raw_result(result: ProcessRunResult, result_path: Path, metadata: dict[str, object]) -> str:
    raw_text = (
        result_path.read_text(encoding="utf-8")
        if result_path.exists()
        else json.dumps(result.structured_output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if result.structured_output is not None
        else ""
    )
    if len(raw_text.encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise CodexExecutionError(
            "codex result exceeded capture limit",
            classification="needs_review",
            code="codex_result_too_large",
            metadata={**metadata, "status": "result_too_large"},
        )
    return raw_text


def _validated_structured_output(
    result: ProcessRunResult,
    raw_text: str,
    response_schema: dict[str, Any],
    secrets: tuple[str, ...],
    metadata: dict[str, object],
) -> dict[str, Any]:
    try:
        structured_output = result.structured_output or json.loads(raw_text)
        Draft202012Validator(response_schema).validate(structured_output)
        safe_output = redact_secrets(structured_output, secrets=secrets)
        Draft202012Validator(response_schema).validate(safe_output)
    except json.JSONDecodeError, ValidationError:
        raise CodexExecutionError(
            "codex structured output is invalid",
            classification="needs_review",
            code="codex_output_invalid",
            metadata={**metadata, "status": "invalid_output"},
        ) from None
    if not isinstance(safe_output, dict):
        raise CodexExecutionError(
            "codex structured output is invalid",
            classification="needs_review",
            code="codex_output_invalid",
            metadata={**metadata, "status": "invalid_output"},
        )
    return safe_output


def _safe_raw_result(output: dict[str, Any], metadata: dict[str, object]) -> str:
    safe_raw_text = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(safe_raw_text.encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise CodexExecutionError(
            "codex result exceeded capture limit",
            classification="needs_review",
            code="codex_result_too_large",
            metadata={**metadata, "status": "result_too_large"},
        )
    return safe_raw_text


def _validated_usage(result: ProcessRunResult, budget: ResearchBudget, metadata: dict[str, object]) -> dict[str, int]:
    usage = result.token_usage or _extract_usage(result.stdout)
    if not usage or not {"input_tokens", "output_tokens"} <= usage.keys():
        raise CodexExecutionError(
            "codex token usage is missing",
            classification="needs_review",
            code="codex_usage_missing",
            metadata={**metadata, "status": "usage_missing", "usage": None},
        )
    if usage["input_tokens"] > budget.max_input_tokens or usage["output_tokens"] > budget.max_output_tokens:
        raise CodexExecutionError(
            "codex token budget exceeded",
            classification="needs_review",
            code="codex_token_budget_exceeded",
            metadata={**metadata, "status": "over_budget", "usage": usage},
        )
    return usage


def _interpret_codex_result(
    result: ProcessRunResult,
    *,
    invocation: _CodexInvocation,
    response_schema: dict[str, Any],
    budget: ResearchBudget,
    resolved_model: str,
) -> CodexExecutionResult:
    metadata = _process_metadata(result, invocation.event_secrets)
    _validate_process_result(result, metadata)
    raw_text = _load_raw_result(result, invocation.result_path, metadata)
    output = _validated_structured_output(result, raw_text, response_schema, invocation.event_secrets, metadata)
    safe_raw_text = _safe_raw_result(output, metadata)
    usage = _validated_usage(result, budget, metadata)
    safe_cli_version = str(metadata.get("codex_cli_version", "unknown"))
    events = _safe_events(result.stdout, secrets=invocation.event_secrets)
    events.append(
        {
            "type": "codex_process",
            "codex_cli_version": safe_cli_version,
            "exit_code": result.exit_code,
            "elapsed_ms": result.elapsed_ms,
            "token_usage": {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"]},
        }
    )
    safe_model = redact_secrets(resolved_model, secrets=invocation.event_secrets)
    return CodexExecutionResult(
        structured_output=output,
        raw_text=safe_raw_text,
        resolved_model=safe_model if isinstance(safe_model, str) else "[REDACTED]",
        usage={"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"]},
        codex_cli_version=safe_cli_version,
        exit_code=result.exit_code,
        elapsed_ms=result.elapsed_ms,
        sanitized_events=events,
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
