from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from app.core.codex_exec import CodexExecutor, ProcessRunResult
from app.generation.provider_settings import default_codex_provider_settings
from app.generation.providers.base import GenerationProviderRequest, ProviderMessage
from app.generation.providers.codex import CodexGenerationProvider


class FakeExecutor:
    structured_output = {"body": "Generated", "parse_mode": "HTML", "buttons": []}
    version = "codex-cli 1.0"

    async def run(self, prompt, response_schema, budget, *, resolved_model, allow_web):
        self.prompt = prompt
        self.response_schema = response_schema
        self.budget = budget
        self.resolved_model = resolved_model
        self.allow_web = allow_web
        return SimpleNamespace(
            structured_output=self.structured_output,
            raw_text='{"body":"Generated","buttons":[],"parse_mode":"HTML"}',
            resolved_model=resolved_model,
            usage={"input_tokens": 25, "output_tokens": 10},
            codex_cli_version=self.version,
            exit_code=0,
            elapsed_ms=15,
            sanitized_events=[{"type": "turn.completed"}],
        )


def _request() -> GenerationProviderRequest:
    return GenerationProviderRequest(
        run_id=uuid4(),
        purpose="telegram_rewrite",
        requested_model=None,
        messages=(
            ProviderMessage(role="system", content="Locked policy"),
            ProviderMessage(role="user", content="Untrusted story"),
        ),
        response_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["body", "parse_mode", "buttons"],
            "properties": {
                "body": {"type": "string"},
                "parse_mode": {"const": "HTML"},
                "buttons": {"type": "array"},
            },
        },
        metadata={"provider_profile_id": str(uuid4())},
    )


async def test_codex_generation_uses_requested_schema_locked_input_and_provider_contract():
    executor = FakeExecutor()
    profile_id = uuid4()
    profile = SimpleNamespace(
        id=profile_id,
        provider_type="codex",
        default_model="gpt-5.4",
        secret_ref=None,
        enabled=True,
        settings=default_codex_provider_settings().model_dump(mode="json"),
    )
    request = replace(_request(), metadata={"provider_profile_id": str(profile_id)})

    result = await CodexGenerationProvider(executor=executor, profile=profile).generate(request)

    assert executor.response_schema == request.response_schema
    assert executor.allow_web is False
    assert executor.resolved_model == "gpt-5.4"
    assert executor.budget.max_model_calls == 1
    assert executor.budget.max_output_tokens == 12_000
    assert "Locked policy" in executor.prompt
    assert "Untrusted story" in executor.prompt
    assert result.provider == "codex"
    assert result.output == executor.structured_output
    assert result.usage["codex_cli_version"] == executor.version
    assert result.usage["provider_profile_id"] == str(profile_id)


async def test_codex_generation_usage_never_leaks_auth_literal_as_cli_version():
    secret_version = "sk-proj-provider-version"
    profile_id = uuid4()
    profile = SimpleNamespace(
        id=profile_id,
        provider_type="codex",
        default_model="gpt-5.4",
        secret_ref=None,
        enabled=True,
        settings=default_codex_provider_settings().model_dump(mode="json"),
    )

    async def runner(**kwargs):
        return ProcessRunResult(
            exit_code=0,
            stdout=('{"type":"turn.completed","usage":{"input_tokens":25,"output_tokens":10}}\n'),
            stderr="",
            elapsed_ms=5,
            structured_output={
                "body": "Generated",
                "parse_mode": "HTML",
                "buttons": [],
            },
            token_usage={"input_tokens": 25, "output_tokens": 10},
            codex_cli_version=secret_version,
        )

    provider = CodexGenerationProvider(
        executor=CodexExecutor(
            process_runner=runner,
            executable="codex",
            environment={"OPENAI_API_KEY": secret_version},
        ),
        profile=profile,
    )
    result = await provider.generate(replace(_request(), metadata={"provider_profile_id": str(profile_id)}))

    assert result.usage["codex_cli_version"] == "[REDACTED]"
    assert secret_version not in str(result.usage)
