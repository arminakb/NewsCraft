from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.telegram_automations import list_route_dispatches
from app.automations.models import AutomationRoute
from app.generation.default_prompts import telegram_prompt_checksum
from app.generation.handlers import _invoke
from app.generation.models import AIProviderProfile, GenerationAttempt, GenerationRun, PromptTemplateVersion
from app.generation.providers.base import GenerationProviderResult
from app.ingestion.repository import IngestionRepository
from app.ingestion.workflow import _record_source_failure
from app.jobs.errors import RetryableJobError
from app.jobs.registry import JobContext


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _GenerationSession:
    def __init__(self, profile: AIProviderProfile) -> None:
        self.profile = profile
        self.run: GenerationRun | None = None
        self.attempt: GenerationAttempt | None = None
        self.scalar_calls = 0

    async def get(self, _model, _identifier):
        return self.profile

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def scalar(self, _statement):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return None
        return self.run if self.scalar_calls % 2 == 0 else self.attempt

    async def scalars(self, _statement):
        return []

    def add(self, value):
        if isinstance(value, GenerationRun):
            self.run = value
        elif isinstance(value, GenerationAttempt):
            self.attempt = value

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    def begin(self):
        return _Transaction()


def _prompt() -> PromptTemplateVersion:
    schema = {"type": "object"}
    system = "System"
    user = "Value={value}"
    return PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=uuid4(),
        version=1,
        system_template=system,
        user_template=user,
        output_schema_version="test.v1",
        output_schema=schema,
        checksum_sha256=telegram_prompt_checksum(system, user, schema),
        is_active=False,
    )


def _profile() -> AIProviderProfile:
    return AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )


async def _resolved(provider, *, model="fake-v1"):
    return SimpleNamespace(provider=provider, provider_type="fake", model=model)


@pytest.mark.asyncio
async def test_generation_error_columns_redact_nested_and_inline_canaries_without_changing_caller_error():
    profile = _profile()
    session = _GenerationSession(profile)

    class Provider:
        async def generate(self, _request):
            raise RetryableJobError(
                code="provider_api_key=canonical-code-canary",
                message='upstream {"authorization":"Bearer canonical-message-canary"}',
            )

    resolver = SimpleNamespace(resolve=lambda _profile, _model: _resolved(Provider()))
    with pytest.raises(RetryableJobError) as caught:
        await _invoke(
            JobContext(session=session, providers=SimpleNamespace()),
            profile_resolver=resolver,
            profile_id=profile.id,
            prompt=_prompt(),
            purpose="canonical_story",
            story_revision_id=None,
            input_payload={"value": "executed"},
            input_hash="a" * 64,
            workflow_job_id=uuid4(),
            workflow_attempt=1,
            validate_output=lambda output: output,
        )

    assert "canonical-code-canary" in caught.value.code
    assert "canonical-message-canary" in caught.value.message
    assert session.run is not None and session.attempt is not None
    for durable in (session.run, session.attempt):
        assert "canonical-code-canary" not in durable.error_code
        assert "canonical-message-canary" not in durable.error_message
        assert "[REDACTED]" in durable.error_code
        assert "[REDACTED]" in durable.error_message


@pytest.mark.asyncio
async def test_classified_provider_error_code_is_redacted_before_normalization():
    profile = _profile()
    session = _GenerationSession(profile)

    class ClassifiedProviderError(RuntimeError):
        classification = "retryable"
        code = "provider_api_key=normalization-canary"

    class Provider:
        async def generate(self, _request):
            raise ClassifiedProviderError("provider unavailable")

    resolver = SimpleNamespace(resolve=lambda _profile, _model: _resolved(Provider()))
    with pytest.raises(RetryableJobError) as caught:
        await _invoke(
            JobContext(session=session, providers=SimpleNamespace()),
            profile_resolver=resolver,
            profile_id=profile.id,
            prompt=_prompt(),
            purpose="canonical_story",
            story_revision_id=None,
            input_payload={"value": "executed"},
            input_hash="a" * 64,
            workflow_job_id=uuid4(),
            workflow_attempt=1,
            validate_output=lambda output: output,
        )

    assert caught.value.code == "generation_provider_failed"
    assert session.run is not None and session.attempt is not None
    for durable in (session.run, session.attempt):
        assert durable.error_code == "generation_provider_failed"
        assert "normalization-canary" not in durable.error_code


@pytest.mark.asyncio
async def test_generation_request_response_and_usage_are_sanitized_before_durable_write():
    profile = _profile()
    session = _GenerationSession(profile)

    class Provider:
        async def generate(self, _request):
            return GenerationProviderResult(
                provider="fake",
                requested_model="api_key=canonical-model-canary",
                resolved_model="api_key=canonical-model-canary",
                output={
                    "ok": True,
                    "metadata": {"authorization": "Bearer canonical-output-canary"},
                },
                raw_text="{}",
                usage={"output_tokens": 1, "token": "canonical-usage-canary"},
                finish_reason="stop",
            )

    resolver = SimpleNamespace(
        resolve=lambda _profile, _model: _resolved(
            Provider(),
            model="api_key=canonical-model-canary",
        )
    )
    run, attempt, validated = await _invoke(
        JobContext(session=session, providers=SimpleNamespace()),
        profile_resolver=resolver,
        profile_id=profile.id,
        prompt=_prompt(),
        purpose="canonical_story",
        story_revision_id=None,
        input_payload={
            "value": "executed",
            "nested": {"api_key": "canonical-input-canary"},
        },
        input_hash="a" * 64,
        workflow_job_id=uuid4(),
        workflow_attempt=1,
        validate_output=lambda output: output,
    )

    assert validated["metadata"]["authorization"] == "Bearer canonical-output-canary"
    assert "canonical-input-canary" not in str(run.request_payload)
    assert "canonical-output-canary" not in str(run.output_payload)
    assert "canonical-output-canary" not in str(attempt.response_payload)
    assert "canonical-usage-canary" not in str(attempt.usage)
    assert "canonical-model-canary" not in str(run.requested_model)
    assert "canonical-model-canary" not in str(attempt.requested_model)
    assert "canonical-model-canary" not in str(attempt.resolved_model)
    assert run.request_payload["input"]["nested"]["api_key"] == "[REDACTED]"
    assert run.output_payload["metadata"]["authorization"] == "[REDACTED]"
    assert attempt.usage["token"] == "[REDACTED]"


class _CaptureSession:
    def __init__(self) -> None:
        self.added = []
        self.statement = None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def execute(self, statement):
        self.statement = statement


@pytest.mark.asyncio
async def test_ingestion_raw_payload_sanitizes_transport_metadata_and_auth_error_body():
    session = _CaptureSession()
    body = '{"authorization":"Bearer ingestion-body-canary"}'
    payload = await IngestionRepository(session).save_raw_payload(
        run_id=uuid4(),
        source_id=uuid4(),
        payload_kind="feed_xml",
        request_url=(
            "https://request-user:request-password@example.com/feed?api_key=ingestion-request-canary&topic=news"
        ),
        final_url=("https://final-user:final-password@example.com/feed?token=ingestion-final-canary"),
        http_status=401,
        headers={
            "Authorization": "Bearer ingestion-header-canary",
            "Set-Cookie": "session=ingestion-cookie-canary",
            "x-safe": "preserved",
        },
        content_type="application/json",
        raw_text=body,
        parser_warnings=['warning {"api_key":"ingestion-warning-canary"}'],
    )

    persisted = str(
        {
            "request_url": payload.request_url,
            "final_url": payload.final_url,
            "headers": payload.headers,
            "raw_text": payload.raw_text,
            "parser_warnings": payload.parser_warnings,
        }
    )
    for canary in (
        "request-password",
        "ingestion-request-canary",
        "final-password",
        "ingestion-final-canary",
        "ingestion-header-canary",
        "ingestion-cookie-canary",
        "ingestion-body-canary",
        "ingestion-warning-canary",
    ):
        assert canary not in persisted
    assert payload.headers["x-safe"] == "preserved"
    assert "[REDACTED]" in persisted
    assert payload.body_sha256 == sha256(payload.raw_text.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_ingestion_success_body_preserves_editorial_text_even_when_it_mentions_secret_keys():
    session = _CaptureSession()
    editorial_body = "Reporting text that literally discusses api_key=editorial-example."
    payload = await IngestionRepository(session).save_raw_payload(
        run_id=uuid4(),
        source_id=uuid4(),
        payload_kind="feed_xml",
        request_url="https://example.com/feed",
        final_url="https://example.com/feed",
        http_status=200,
        headers={"content-type": "application/xml"},
        content_type="application/xml",
        raw_text=editorial_body,
        parser_warnings=[],
    )

    assert payload.raw_text == editorial_body


@pytest.mark.asyncio
async def test_ingestion_finish_run_sanitizes_nested_stats_and_error_before_update():
    session = _CaptureSession()
    await IngestionRepository(session).finish_run(
        uuid4(),
        status="failed",
        stats={
            "failed": 1,
            "errors": [
                {"authorization": "Bearer ingestion-stats-canary"},
                {"detail": "api_key=ingestion-detail-canary"},
            ],
        },
        error='failure {"password":"ingestion-error-canary"}',
    )

    values = session.statement.compile().params
    persisted = str({"stats": values["stats"], "error": values["error"]})
    assert "ingestion-stats-canary" not in persisted
    assert "ingestion-detail-canary" not in persisted
    assert "ingestion-error-canary" not in persisted
    assert "[REDACTED]" in persisted


def test_source_failure_sanitizes_exception_type_and_message_before_model_write():
    source = SimpleNamespace(
        active=True,
        disabled_reason=None,
        failure_count=0,
        last_fetch_at=None,
        last_failure_at=None,
        last_http_status=None,
        last_error_type=None,
        last_error_message=None,
        health_status="healthy",
    )
    _record_source_failure(
        source,
        RuntimeError('source {"authorization":"Bearer source-message-canary"}'),
        error_type="source_api_key=source-type-canary",
    )

    assert "source-message-canary" not in source.last_error_message
    assert "source-type-canary" not in source.last_error_type
    assert "[REDACTED]" in source.last_error_message
    assert "[REDACTED]" in source.last_error_type


@pytest.mark.asyncio
async def test_legacy_telegram_dispatch_errors_are_resanitized_at_list_boundary():
    route_id = uuid4()
    story_id = uuid4()
    story_revision_id = uuid4()
    dispatch = SimpleNamespace(
        id=uuid4(),
        route_id=route_id,
        source_item_id=uuid4(),
        story_revision_id=story_revision_id,
        source_key="source:1",
        source_fingerprint="f" * 64,
        source_message_ids=[1],
        dispatch_kind="live",
        status="failed",
        generation_run_id=uuid4(),
        variant_revision_id=None,
        publish_job_id=None,
        error_code="legacy_api_key=dispatch-code-canary",
        error_message='legacy {"authorization":"Bearer dispatch-message-canary"}',
        created_at=None,
        updated_at=None,
    )

    class Session:
        async def get(self, model, identifier):
            if model is AutomationRoute:
                return SimpleNamespace(id=route_id)
            return SimpleNamespace(id=story_revision_id, story_id=story_id)

        async def scalars(self, _statement):
            return [dispatch]

    output = await list_route_dispatches(route_id, Session())

    assert len(output) == 1
    assert "dispatch-code-canary" not in output[0]["error_code"]
    assert "dispatch-message-canary" not in output[0]["error_message"]
    assert "[REDACTED]" in output[0]["error_code"]
    assert "[REDACTED]" in output[0]["error_message"]
