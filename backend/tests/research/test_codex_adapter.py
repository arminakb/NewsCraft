from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.codex_exec import (
    CodexExecutionError,
    CodexExecutionResult,
    CodexExecutor,
    ProcessRunResult,
    _default_process_runner,
    build_codex_environment,
)
from app.core.outbound_proxy import ProxyConfigurationError
from app.normalization.urls import normalize_url
from app.research.base import ResearchRequest
from app.research.codex_adapter import CodexResearchBackend, ResearchBackendError
from app.research.schemas import DiscoveredSourcePayload, ResearchBudget
from app.stories.evidence import EvidenceRecord, build_evidence_key


def _request() -> ResearchRequest:
    text = "Existing supplied evidence."
    digest = sha256(text.encode()).hexdigest()
    return ResearchRequest(
        run_id=uuid4(),
        story_id=uuid4(),
        provider_profile_id=uuid4(),
        requested_model="gpt-5.4",
        mode="manual",
        evidence=[
            EvidenceRecord(
                evidence_key=build_evidence_key(
                    content_item_id=None,
                    source_url="https://input.example/report",
                    content_sha256=digest,
                ),
                evidence_snapshot_id=uuid4(),
                content_item_id=None,
                title="Input",
                content_text=text,
                content_sha256=digest,
                source_url="https://input.example/report",
                authors=(),
                published_at=None,
                captured_at=datetime.now(UTC),
            )
        ],
        budget=ResearchBudget(
            max_model_calls=1,
            max_input_tokens=2_000,
            max_output_tokens=1_000,
        ),
    )


def _raw_output() -> dict:
    return {
        "sources": [{"url": "https://news.example/report", "title": "Report"}],
        "brief": {
            "summary": "Verified summary",
            "verified_facts": [
                {
                    "text": "A verified fact",
                    "citations": [
                        {
                            "source_url": "https://news.example/report",
                            "quote": "verified excerpt",
                        }
                    ],
                }
            ],
            "disagreements": [],
            "missing_information": [],
            "suggested_angles": ["Explain the report"],
        },
    }


class RecordingRunner:
    def __init__(self, output: dict | None = None, *, usage: dict | None = None):
        self.output = output or _raw_output()
        self.usage = usage or {"input_tokens": 100, "output_tokens": 50}
        self.calls = []
        self.stdout = '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":50}}\n'

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return ProcessRunResult(
            exit_code=0,
            stdout=self.stdout,
            stderr="",
            elapsed_ms=12,
            structured_output=self.output,
            token_usage=self.usage,
            codex_cli_version="codex-cli 1.0",
        )


class FakeFetcher:
    async def fetch(self, url: str) -> DiscoveredSourcePayload:
        text = "safe fetched body with verified excerpt"
        digest = sha256(text.encode()).hexdigest()
        return DiscoveredSourcePayload(
            evidence_key=build_evidence_key(content_item_id=None, source_url=url, content_sha256=digest),
            url=url,
            title="Safely fetched",
            publisher="Example",
            published_at=None,
            retrieved_at=datetime.now(UTC),
            content_text=text,
            content_sha256=digest,
            extraction_status="ok",
        )


class RedirectingFetcher(FakeFetcher):
    async def fetch(self, url: str) -> DiscoveredSourcePayload:
        return await super().fetch("https://news.example/final")


class ManualClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class CrossingClock:
    def __init__(self, *, cross_on_call, before, after):
        self.cross_on_call = cross_on_call
        self.before = before
        self.after = after
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.after if self.calls >= self.cross_on_call else self.before


class BoundaryClock:
    def __init__(self, boundary):
        self.boundary = boundary
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return 0.0 if self.calls == 1 else self.boundary


class AdvancingExecutor:
    def __init__(self, clock, advance):
        self.clock = clock
        self.advance = advance

    async def run(self, *args, **kwargs):
        self.clock.value += self.advance
        return CodexExecutionResult(
            structured_output=_raw_output(),
            raw_text="{}",
            resolved_model="gpt-5.4",
            usage={"input_tokens": 100, "output_tokens": 50},
            codex_cli_version="codex-cli 1.0",
            exit_code=0,
            elapsed_ms=int(self.advance * 1000),
            sanitized_events=[{"type": "codex_process", "elapsed_ms": int(self.advance * 1000)}],
        )


class AdvancingFetcher(FakeFetcher):
    def __init__(self, clock, advance):
        self.clock = clock
        self.advance = advance

    async def fetch(self, url):
        self.clock.value += self.advance
        return await super().fetch(url)


class DelayedExecutor(AdvancingExecutor):
    async def run(self, *args, **kwargs):
        await asyncio.sleep(self.advance)
        return CodexExecutionResult(
            structured_output=_raw_output(),
            raw_text="{}",
            resolved_model="gpt-5.4",
            usage={"input_tokens": 100, "output_tokens": 50},
            codex_cli_version="codex-cli 1.0",
            exit_code=0,
            elapsed_ms=int(self.advance * 1000),
            sanitized_events=[],
        )


class CancellableFetcher(FakeFetcher):
    def __init__(self):
        self.cancelled = False

    async def fetch(self, url):
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class FailingFetcher:
    async def fetch(self, url):
        from app.research.safe_fetch import SafeArticleFetchError

        raise SafeArticleFetchError("secret-body-fetch-detail")


class HangingRunner:
    def __init__(self):
        self.terminated = False

    async def __call__(self, **kwargs):
        await asyncio.Future()

    async def terminate(self):
        self.terminated = True


class FakeReader:
    def __init__(self, *, hang: bool = False, value: bytes = b""):
        self.hang = hang
        self.value = value
        self.read_once = False

    async def read(self, size=-1):
        if self.hang:
            await asyncio.Future()
        if self.read_once:
            return b""
        self.read_once = True
        return self.value


class FakeWriter:
    def __init__(self, *, hang: bool = False):
        self.hang = hang
        self.closed = False

    def write(self, value):
        self.value = value

    async def drain(self):
        if self.hang:
            await asyncio.Future()

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(
        self,
        *,
        version_hang=False,
        stdin_hang=False,
        exec_hang=False,
        stdout_value=b"",
    ):
        self.version_hang = version_hang
        self.stdin = FakeWriter(hang=stdin_hang)
        self.stdout = FakeReader(hang=exec_hang, value=stdout_value)
        self.stderr = FakeReader(hang=exec_hang)
        self.returncode = None
        self.killed = False
        self.waited = 0

    async def communicate(self):
        if self.version_hang:
            await asyncio.Future()
        self.returncode = 0
        return b"codex-cli 1.0\n", b""

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        self.waited += 1
        if self.returncode is None:
            await asyncio.Future()
        return self.returncode


def _runner_kwargs():
    return {
        "argv": ["codex", "exec"],
        "cwd": Path.cwd(),
        "env": {},
        "stdin": "prompt\n",
        "timeout_seconds": 0.01,
        "max_output_bytes": 1024,
        "response_schema": {"type": "object"},
        "max_input_tokens": 100,
        "max_output_tokens": 100,
    }


def _option_values(argv: list[str], option: str) -> list[str]:
    return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == option]


async def test_codex_uses_isolated_reproducible_command_and_schema():
    runner = RecordingRunner()
    request = _request()
    await CodexResearchBackend(
        executor=CodexExecutor(process_runner=runner, executable="codex"),
        fetcher=FakeFetcher(),
    ).research(request)

    call = runner.calls[0]
    argv = call["argv"]
    assert argv[:4] == ["codex", "exec", "--ephemeral", "--json"]
    assert _option_values(argv, "--model") == [request.requested_model]
    assert _option_values(argv, "-c") == ['shell_environment_policy.inherit="none"']
    assert _option_values(argv, "--enable") == ["browser_use"]
    assert set(_option_values(argv, "--disable")) == {
        "shell_tool",
        "code_mode_host",
        "computer_use",
        "apps",
        "browser_use_external",
        "browser_use_full_cdp_access",
    }
    assert Path(_option_values(argv, "--output-schema")[0]).is_absolute()
    assert Path(_option_values(argv, "-o")[0]).is_absolute()
    assert Path(_option_values(argv, "-C")[0]).is_absolute()
    assert call["stdin"] and call["stdin"].endswith("\n")
    assert "evidence_snapshot_id" not in call["response_schema"]


async def test_generation_executor_disables_browser_and_all_agentic_capabilities():
    runner = RecordingRunner(output={"answer": "locked"})
    await CodexExecutor(process_runner=runner, executable="codex").run(
        "Generate locked output",
        response_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        budget=ResearchBudget(max_model_calls=1),
        resolved_model="gpt-5.4",
        allow_web=False,
    )
    argv = runner.calls[0]["argv"]
    assert _option_values(argv, "--enable") == []
    assert set(_option_values(argv, "--disable")) == {
        "shell_tool",
        "code_mode_host",
        "computer_use",
        "apps",
        "browser_use",
        "browser_use_external",
        "browser_use_full_cdp_access",
    }


def test_codex_environment_uses_temporary_home_and_exact_auth_allowlist(tmp_path):
    env = build_codex_environment(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/operator",
            "CODEX_HOME": "/home/operator/.codex",
            "OPENAI_API_KEY": "codex-auth",
            "HTTP_PROXY": "http://proxy",
            "DATABASE_URL": "postgresql://secret",
            "TELEGRAM_DESTINATION_NEWS_TOKEN": "secret",
            "OPENROUTER_API_KEY": "secret",
        },
        work_dir=tmp_path,
    )
    assert env == {
        "PATH": "/usr/bin",
        "HOME": str(tmp_path),
        "CODEX_HOME": "/home/operator/.codex",
        "OPENAI_API_KEY": "codex-auth",
        "HTTP_PROXY": "http://proxy",
    }


def test_codex_environment_normalizes_lowercase_proxy_and_rejects_conflicts(tmp_path):
    env = build_codex_environment(
        {
            "PATH": "/usr/bin",
            "https_proxy": " socks5h://proxy.example:1080 ",
            "no_proxy": "localhost,.internal.example",
        },
        work_dir=tmp_path,
    )

    assert env["HTTPS_PROXY"] == "socks5h://proxy.example:1080"
    assert env["NO_PROXY"] == "localhost,.internal.example"
    assert "https_proxy" not in env
    with pytest.raises(ProxyConfigurationError, match="proxy_environment_conflict"):
        build_codex_environment(
            {
                "HTTP_PROXY": "http://one.example:8080",
                "http_proxy": "http://two.example:8080",
            },
            work_dir=tmp_path,
        )


async def test_codex_materializes_urls_and_rewrites_exact_quote_to_evidence_key():
    result = await CodexResearchBackend(
        executor=CodexExecutor(process_runner=RecordingRunner(), executable="codex"),
        fetcher=FakeFetcher(),
    ).research(_request())

    source = result.output.sources[0]
    citation = result.output.brief.verified_facts[0].citations[0]
    assert source.evidence_key == (f"url:{normalize_url(str(source.url))}:{source.content_sha256}")
    assert citation.evidence_key == source.evidence_key
    assert citation.locator == "chars:23-39"
    assert citation.excerpt_sha256 == sha256(b"verified excerpt").hexdigest()
    assert "evidence_snapshot_id" not in result.model_dump_json()
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 50


async def test_codex_research_success_reports_total_executor_and_fetch_elapsed():
    clock = ManualClock()
    request = _request().model_copy(
        update={"budget": _request().budget.model_copy(update={"max_elapsed_seconds": 1.0})}
    )
    result = await CodexResearchBackend(
        executor=AdvancingExecutor(clock, 0.01),
        fetcher=AdvancingFetcher(clock, 0.02),
        monotonic=clock,
    ).research(request)

    assert result.elapsed_ms == 30
    assert result.elapsed_ms > 10
    assert result.sanitized_events[-1] == {
        "type": "codex_research_total",
        "elapsed_ms": 30,
    }


async def test_codex_research_total_deadline_cancels_slow_fetch_after_executor_time():
    request = _request().model_copy(
        update={"budget": _request().budget.model_copy(update={"max_elapsed_seconds": 0.1})}
    )
    fetcher = CancellableFetcher()
    with pytest.raises(ResearchBackendError) as error:
        await CodexResearchBackend(
            executor=DelayedExecutor(ManualClock(), 0.06),
            fetcher=fetcher,
        ).research(request)

    assert error.value.classification == "needs_review"
    assert error.value.code == "codex_elapsed_budget_exceeded"
    assert error.value.metadata["status"] == "over_budget"
    assert error.value.metadata["elapsed_ms"] >= 50
    assert fetcher.cancelled is True


async def test_codex_research_deadline_covers_repeated_claim_quote_scans():
    output = _raw_output()
    output["brief"]["verified_facts"].append(
        {
            "text": "A second verified fact",
            "citations": [
                {
                    "source_url": "https://news.example/report",
                    "quote": "verified excerpt",
                }
            ],
        }
    )
    request = _request().model_copy(
        update={"budget": _request().budget.model_copy(update={"max_elapsed_seconds": 1.0})}
    )
    clock = CrossingClock(cross_on_call=6, before=0.0, after=1.01)

    with pytest.raises(ResearchBackendError) as error:
        await CodexResearchBackend(
            executor=CodexExecutor(process_runner=RecordingRunner(output=output), executable="codex"),
            fetcher=FakeFetcher(),
            monotonic=clock,
        ).research(request)

    assert error.value.code == "codex_elapsed_budget_exceeded"
    assert error.value.classification == "needs_review"
    assert error.value.metadata["elapsed_ms"] == 1010
    assert clock.calls >= 6


async def test_codex_research_succeeds_immediately_below_final_deadline():
    request = _request().model_copy(
        update={"budget": _request().budget.model_copy(update={"max_elapsed_seconds": 10.0})}
    )
    clock = BoundaryClock(9.9)

    result = await CodexResearchBackend(
        executor=CodexExecutor(process_runner=RecordingRunner(), executable="codex"),
        fetcher=FakeFetcher(),
        monotonic=clock,
    ).research(request)

    assert result.elapsed_ms == 9_900
    assert result.sanitized_events[-1]["elapsed_ms"] == 9_900


async def test_codex_research_rejects_deadline_crossed_during_result_construction(
    monkeypatch,
):
    import app.research.codex_adapter as module

    clock = ManualClock()
    request = _request().model_copy(
        update={"budget": _request().budget.model_copy(update={"max_elapsed_seconds": 1.0})}
    )
    real_result = module.ResearchResult

    def advancing_result(**kwargs):
        clock.value += 0.3
        return real_result(**kwargs)

    monkeypatch.setattr(module, "ResearchResult", advancing_result)
    with pytest.raises(ResearchBackendError) as error:
        await CodexResearchBackend(
            executor=AdvancingExecutor(clock, 0.4),
            fetcher=AdvancingFetcher(clock, 0.4),
            monotonic=clock,
        ).research(request)

    assert error.value.code == "codex_elapsed_budget_exceeded"
    assert error.value.metadata["elapsed_ms"] == 1_100


async def test_codex_research_elapsed_and_total_event_use_same_post_construction_read(
    monkeypatch,
):
    import app.research.codex_adapter as module

    clock = ManualClock()
    request = _request().model_copy(
        update={"budget": _request().budget.model_copy(update={"max_elapsed_seconds": 1.0})}
    )
    real_result = module.ResearchResult

    def advancing_result(**kwargs):
        clock.value += 0.1
        return real_result(**kwargs)

    monkeypatch.setattr(module, "ResearchResult", advancing_result)
    result = await CodexResearchBackend(
        executor=AdvancingExecutor(clock, 0.2),
        fetcher=AdvancingFetcher(clock, 0.2),
        monotonic=clock,
    ).research(request)

    assert result.elapsed_ms == 500
    assert result.sanitized_events[-1] == {
        "type": "codex_research_total",
        "elapsed_ms": 500,
    }


@pytest.mark.parametrize("failure", ["unknown_evidence", "fetch"])
async def test_codex_evidence_errors_include_only_sanitized_total_metadata(failure):
    output = _raw_output()
    fetcher = FakeFetcher()
    if failure == "unknown_evidence":
        output["brief"]["verified_facts"][0]["citations"][0] = {
            "evidence_key": "secret-body-unknown-key",
            "quote": "secret-body-quote",
        }
    else:
        fetcher = FailingFetcher()
    clock = ManualClock()
    clock.value = 0.25
    request = _request().model_copy(
        update={"budget": _request().budget.model_copy(update={"max_elapsed_seconds": 1.0})}
    )

    with pytest.raises(ResearchBackendError) as error:
        await CodexResearchBackend(
            executor=CodexExecutor(process_runner=RecordingRunner(output=output), executable="codex"),
            fetcher=fetcher,
            monotonic=clock,
        ).research(request)

    assert error.value.code == "codex_evidence_invalid"
    assert error.value.metadata == {
        "status": "evidence_invalid",
        "elapsed_ms": 0,
    }
    assert "secret-body" not in str(error.value.metadata)


async def test_codex_rejects_distinct_candidates_redirecting_to_same_final_source():
    output = _raw_output()
    output["sources"].append({"url": "https://other.example/redirect"})
    with pytest.raises(CodexExecutionError) as error:
        await CodexResearchBackend(
            executor=CodexExecutor(process_runner=RecordingRunner(output=output), executable="codex"),
            fetcher=RedirectingFetcher(),
        ).research(_request())
    assert error.value.classification == "needs_review"
    assert error.value.code == "codex_duplicate_materialized_source"


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": 2_001, "output_tokens": 1}])
async def test_codex_rejects_missing_or_over_budget_usage(usage):
    runner = RecordingRunner(usage={"input_tokens": 100, "output_tokens": 50})
    runner.usage = usage
    if not usage:
        runner.stdout = ""
    with pytest.raises(CodexExecutionError) as error:
        await CodexExecutor(process_runner=runner, executable="codex").run(
            "prompt",
            response_schema={"type": "object"},
            budget=_request().budget,
            resolved_model="gpt-5.4",
            allow_web=False,
        )
    assert error.value.classification == "needs_review"
    expected_status = "usage_missing" if not usage else "over_budget"
    assert error.value.metadata["status"] == expected_status
    assert error.value.metadata["codex_cli_version"] == "codex-cli 1.0"
    assert error.value.metadata["elapsed_ms"] == 12
    assert error.value.metadata["exit_code"] == 0
    if usage:
        assert error.value.metadata["usage"] == usage
    assert "stdout" not in error.value.metadata
    assert "stderr" not in error.value.metadata


async def test_codex_redacts_literal_auth_secret_from_safe_events_without_losing_usage():
    runner = RecordingRunner()
    runner.stdout = (
        '{"type":"turn.completed","status":"auth sk-proj-super-secret",'
        '"usage":{"input_tokens":100,"output_tokens":50}}\n'
    )
    result = await CodexExecutor(
        process_runner=runner,
        executable="codex",
        environment={"OPENAI_API_KEY": "sk-proj-super-secret"},
    ).run(
        "prompt",
        response_schema={"type": "object"},
        budget=_request().budget,
        resolved_model="gpt-5.4",
        allow_web=False,
    )
    assert "sk-proj-super-secret" not in str(result.sanitized_events)
    assert "[REDACTED]" in str(result.sanitized_events)
    assert result.usage == {"input_tokens": 100, "output_tokens": 50}


async def test_codex_redacts_auth_literal_used_as_cli_version_everywhere():
    secret_version = "sk-proj-version-secret"
    runner = RecordingRunner()

    async def secret_version_runner(**kwargs):
        result = await runner(**kwargs)
        return ProcessRunResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            elapsed_ms=result.elapsed_ms,
            structured_output=result.structured_output,
            token_usage=result.token_usage,
            codex_cli_version=secret_version,
        )

    result = await CodexExecutor(
        process_runner=secret_version_runner,
        executable="codex",
        environment={"OPENAI_API_KEY": secret_version},
    ).run(
        "prompt",
        response_schema={"type": "object"},
        budget=_request().budget,
        resolved_model="gpt-5.4",
        allow_web=False,
    )

    assert result.codex_cli_version == "[REDACTED]"
    assert secret_version not in str(result.sanitized_events)
    process_event = result.sanitized_events[-1]
    assert process_event["codex_cli_version"] == "[REDACTED]"


async def test_research_error_preserves_safe_execution_metadata():
    runner = RecordingRunner(usage={"input_tokens": 2_001, "output_tokens": 1})
    with pytest.raises(ResearchBackendError) as error:
        await CodexResearchBackend(
            executor=CodexExecutor(process_runner=runner, executable="codex"),
            fetcher=FakeFetcher(),
        ).research(_request())
    elapsed_ms = error.value.metadata.pop("elapsed_ms")
    assert elapsed_ms >= 0
    assert error.value.metadata == {
        "codex_cli_version": "codex-cli 1.0",
        "exit_code": 0,
        "status": "over_budget",
        "usage": {"input_tokens": 2_001, "output_tokens": 1},
    }


async def test_codex_timeout_terminates_runner_and_returns_retryable_error():
    runner = HangingRunner()
    with pytest.raises(CodexExecutionError, match="codex timed out") as error:
        await CodexExecutor(
            process_runner=runner,
            executable="codex",
            timeout_seconds=0.01,
        ).run(
            "prompt",
            response_schema={"type": "object"},
            budget=_request().budget,
            resolved_model="gpt-5.4",
            allow_web=False,
        )
    assert error.value.classification == "retryable"
    assert runner.terminated is True


@pytest.mark.parametrize("phase", ["version", "stdin", "exec"])
async def test_default_runner_total_timeout_kills_and_awaits_current_child(monkeypatch, phase):
    version = FakeProcess(version_hang=phase == "version")
    execute = FakeProcess(stdin_hang=phase == "stdin", exec_hang=phase == "exec")
    processes = iter([version, execute])

    async def create_process(*args, **kwargs):
        return next(processes)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    with pytest.raises(CodexExecutionError, match="codex timed out"):
        await _default_process_runner(**_runner_kwargs())
    current = version if phase == "version" else execute
    assert current.killed is True
    assert current.waited >= 1


async def test_default_runner_cancellation_kills_and_awaits_exec_child(monkeypatch):
    version = FakeProcess()
    execute = FakeProcess(exec_hang=True)
    processes = iter([version, execute])

    async def create_process(*args, **kwargs):
        return next(processes)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    task = asyncio.create_task(_default_process_runner(**{**_runner_kwargs(), "timeout_seconds": 10}))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert execute.killed is True
    assert execute.waited >= 1


async def test_default_runner_stream_overage_reports_safe_process_metadata(monkeypatch):
    version = FakeProcess()
    execute = FakeProcess(stdout_value=(b'{"type":"turn.completed","usage":{"input_tokens":101,"output_tokens":1}}\n'))
    processes = iter([version, execute])

    async def create_process(*args, **kwargs):
        return next(processes)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    with pytest.raises(CodexExecutionError) as error:
        await _default_process_runner(**_runner_kwargs())
    assert error.value.code == "codex_token_budget_exceeded"
    assert error.value.metadata["usage"] == {"input_tokens": 101, "output_tokens": 1}
    assert error.value.metadata["codex_cli_version"] == "codex-cli 1.0"
    assert error.value.metadata["exit_code"] == -9
    assert "stdout" not in error.value.metadata


async def test_codex_rejects_combined_stdout_stderr_over_one_mebibyte():
    runner = RecordingRunner()
    runner.stdout = "x" * (1024 * 1024)

    async def oversized(**kwargs):
        result = await runner(**kwargs)
        return ProcessRunResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr="x",
            elapsed_ms=result.elapsed_ms,
            structured_output=result.structured_output,
            token_usage=result.token_usage,
            codex_cli_version=result.codex_cli_version,
        )

    with pytest.raises(CodexExecutionError) as error:
        await CodexExecutor(process_runner=oversized, executable="codex").run(
            "prompt",
            response_schema={"type": "object"},
            budget=_request().budget,
            resolved_model="gpt-5.4",
            allow_web=False,
        )
    assert error.value.code == "codex_output_too_large"


def test_codex_research_adapter_has_no_database_dependency():
    import app.research.codex_adapter as module

    source = inspect.getsource(module)
    assert "sqlalchemy" not in source
    assert "AsyncSession" not in source
