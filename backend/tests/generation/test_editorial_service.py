from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _LifecycleSession:
    def __init__(self, *, existing=None, completed_attempt=None):
        self.existing = existing
        self.completed_attempt = completed_attempt
        self.run = None
        self.attempt = None
        self.scalar_calls = 0
        self.commits = 0
        self.rollbacks = 0

    async def get(self, model, identifier):
        return self.profile

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def scalar(self, statement):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return self.existing
        if self.existing is not None and self.scalar_calls == 2:
            return self.completed_attempt
        return self.run if self.scalar_calls % 2 == 0 else self.attempt

    async def scalars(self, statement):
        return []

    def add(self, value):
        from app.generation.models import GenerationAttempt, GenerationRun

        if isinstance(value, GenerationRun):
            self.run = value
        elif isinstance(value, GenerationAttempt):
            self.attempt = value

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, value):
        return None

    def begin(self):
        return _Tx()


def _lifecycle_prompt():
    from app.generation.default_prompts import prompt_checksum
    from app.generation.models import PromptTemplateVersion

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
        checksum_sha256=prompt_checksum(system, user, schema),
        is_active=False,
    )


def test_editorial_requests_require_profile_and_platforms_and_forbid_prompt_or_provider_literals():
    from app.generation.editorial_service import GeneratePackRequest

    request = GeneratePackRequest(
        brand_profile_id=uuid4(),
        platforms=["telegram"],
        generation_provider_profile_id=uuid4(),
    )
    assert request.research_mode == "off"
    with pytest.raises(ValidationError):
        GeneratePackRequest.model_validate({**request.model_dump(), "provider_type": "fake"})


def test_auto_research_content_pack_continuation_is_strictly_bound():
    from app.research.continuations import normalize_continuation

    story_id = uuid4()
    research_profile_id = uuid4()
    subscriber = "a" * 64
    request = {
        "story_id": str(story_id),
        "brand_profile_id": str(uuid4()),
        "platforms": ["telegram"],
        "generation_provider_profile_id": str(uuid4()),
        "canonical_prompt_template_version_id": str(uuid4()),
        "platform_prompt_template_version_ids": {"telegram": str(uuid4())},
        "research_mode": "auto_if_incomplete",
        "research_provider_profile_id": str(research_profile_id),
        "canonical_prompt_checksum": "b" * 64,
        "platform_prompt_checksums": {"telegram": "c" * 64},
    }
    normalized = normalize_continuation(
        {
            "job_type": "content_pack.generate",
            "payload": request,
            "idempotency_prefix": f"content-pack:{story_id}:{subscriber}",
            "subscriber_id": subscriber,
            "expected_story_id": str(story_id),
            "expected_provider_profile_id": str(research_profile_id),
        }
    )
    assert normalized["payload"] == request
    with pytest.raises(ValueError, match="provider identity"):
        normalize_continuation(
            {
                "job_type": "content_pack.generate",
                "payload": request,
                "idempotency_prefix": f"content-pack:{story_id}:{subscriber}",
                "subscriber_id": subscriber,
                "expected_story_id": str(story_id),
                "expected_provider_profile_id": str(uuid4()),
            }
        )


def test_rendered_prompt_executes_the_immutable_operator_user_template():
    from types import SimpleNamespace

    from tests.generation.handler_exports import render_prompt_messages

    prompt = SimpleNamespace(
        system_template="System exact",
        user_template="Evidence={evidence_json}; story={story_title}",
    )
    messages = render_prompt_messages(
        prompt,
        {"story_title": "Operator title", "evidence_json": '[{"id":1}]'},
    )
    assert messages[0].content == "System exact"
    assert messages[1].content == 'Evidence=[{"id":1}]; story=Operator title'


@pytest.mark.parametrize("template", ["{0}", "{value.missing}", "{value[0]}", "{value!r}"])
def test_rendered_prompt_rejects_unsupported_format_fields(template):
    from types import SimpleNamespace

    from tests.generation.handler_exports import render_prompt_messages

    prompt = SimpleNamespace(system_template="System", user_template=template)

    with pytest.raises(ValueError, match="cannot be rendered"):
        render_prompt_messages(prompt, {"value": "safe"})


def test_instruction_changes_rendered_telegram_prompt_and_input_hash():
    from types import SimpleNamespace

    from app.automations.telegram.handlers import sha256_canonical
    from tests.generation.handler_exports import render_prompt_messages

    prompt = SimpleNamespace(
        system_template="Telegram exact",
        user_template="Story={canonical_story_json}; instruction={instruction}",
    )
    first = render_prompt_messages(prompt, {"canonical_story_json": "{}", "instruction": "Short"})
    second = render_prompt_messages(prompt, {"canonical_story_json": "{}", "instruction": "Formal"})
    assert first[1].content != second[1].content
    assert sha256_canonical({"message": first[1].content}) != sha256_canonical({"message": second[1].content})


def test_qualified_generation_usage_uses_frozen_pricing_as_cost_floor():
    from tests.generation.handler_exports import normalize_provider_usage

    usage, cost = normalize_provider_usage(
        {"input_tokens": 1_000_000, "output_tokens": 500_000, "cost_usd": 1},
        SimpleNamespace(
            pricing_input_usd_per_million=Decimal("2"),
            pricing_output_usd_per_million=Decimal("4"),
        ),
    )

    assert cost == Decimal("4")
    assert usage["cost_usd"] == 4.0
    assert usage["cost_basis"] == "provider_or_profile_max"


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-1"])
def test_qualified_generation_usage_rejects_invalid_cost(invalid):
    from app.jobs.errors import NeedsReviewJobError
    from tests.generation.handler_exports import normalize_provider_usage

    with pytest.raises(NeedsReviewJobError, match="usage metadata"):
        normalize_provider_usage(
            {"input_tokens": 1, "output_tokens": 1, "cost_usd": invalid},
            SimpleNamespace(
                pricing_input_usd_per_million=Decimal("1"),
                pricing_output_usd_per_million=Decimal("1"),
                max_output_tokens=100,
            ),
        )


def test_qualified_generation_usage_rejects_output_token_overrun():
    from app.jobs.errors import NeedsReviewJobError
    from tests.generation.handler_exports import normalize_provider_usage

    with pytest.raises(NeedsReviewJobError, match="output-token budget"):
        normalize_provider_usage(
            {"input_tokens": 1, "output_tokens": 101, "cost_usd": 0},
            SimpleNamespace(
                pricing_input_usd_per_million=Decimal("1"),
                pricing_output_usd_per_million=Decimal("1"),
                max_output_tokens=100,
            ),
        )


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_generation_lifecycle_commits_running_attempt_before_provider_and_validates_before_success():
    from app.generation.models import AIProviderProfile
    from app.generation.providers.base import GenerationProviderResult
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import invoke

    session = _LifecycleSession()
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    session.profile = profile

    class Provider:
        async def generate(self, request):
            assert session.commits == 1
            assert session.run.status == session.attempt.status == "running"
            assert request.messages[1].content == "Value=executed"
            return GenerationProviderResult(
                provider="fake",
                requested_model="fake-v1",
                resolved_model="fake-v1",
                output={"ok": True},
                raw_text='{"ok":true}',
                usage={"output_tokens": 1},
                finish_reason="stop",
            )

    resolver = SimpleNamespace(
        resolve=lambda profile, model: _async_value(
            SimpleNamespace(provider=Provider(), provider_type="fake", model="fake-v1")
        )
    )
    run, attempt, validated = await invoke(
        JobContext(session=session, providers=SimpleNamespace()),
        profile_resolver=resolver,
        profile_id=profile.id,
        prompt=_lifecycle_prompt(),
        purpose="test",
        story_revision_id=None,
        input_payload={"value": "executed"},
        input_hash="a" * 64,
        workflow_job_id=uuid4(),
        workflow_attempt=1,
        validate_output=lambda output: {**output, "validated": True},
    )
    assert validated == {"ok": True, "validated": True}
    assert run.status == attempt.status == "succeeded"


@pytest.mark.asyncio
async def test_generation_lifecycle_stops_when_frozen_pack_cost_budget_is_exceeded():
    from app.generation.models import AIProviderProfile
    from app.generation.providers.base import GenerationProviderResult
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import invoke

    session = _LifecycleSession()
    profile = AIProviderProfile(
        id=uuid4(),
        name="Qualified",
        provider_type="openrouter",
        default_model="qualified-model",
        secret_ref="OPENROUTER_EDITOR_KEY",
        settings={},
        enabled=True,
    )
    session.profile = profile

    class Provider:
        async def generate(self, request):
            return GenerationProviderResult(
                provider="openrouter",
                requested_model="qualified-model",
                resolved_model="qualified-model",
                output={"ok": True},
                raw_text='{"ok":true}',
                usage={"input_tokens": 1, "output_tokens": 1, "cost_usd": 1.25},
                finish_reason="stop",
            )

    resolved = SimpleNamespace(
        provider=Provider(),
        provider_type="openrouter",
        model="qualified-model",
        max_attempts=3,
        max_elapsed_seconds=180,
        max_pack_cost_usd=Decimal("1.50"),
        pricing_input_usd_per_million=Decimal("1"),
        pricing_output_usd_per_million=Decimal("1"),
    )
    resolver = SimpleNamespace(resolve=lambda profile, model: _async_value(resolved))

    with pytest.raises(NeedsReviewJobError) as caught:
        await invoke(
            JobContext(session=session, providers=SimpleNamespace()),
            profile_resolver=resolver,
            profile_id=profile.id,
            prompt=_lifecycle_prompt(),
            purpose="test",
            story_revision_id=None,
            input_payload={"value": "executed"},
            input_hash="a" * 64,
            workflow_job_id=uuid4(),
            workflow_attempt=1,
            prior_pack_cost_usd=Decimal("0.50"),
            validate_output=lambda output: output,
        )

    assert caught.value.code == "generation_pack_cost_budget_exhausted"
    assert session.attempt.status == "failed"
    assert session.attempt.usage["cost_usd"] == 1.25


@pytest.mark.asyncio
async def test_generation_crash_after_provider_leaves_durable_running_attempt_before_persistence():
    from app.generation.models import AIProviderProfile
    from app.generation.providers.base import GenerationProviderResult
    from app.jobs.registry import JobContext
    from qualification.faults import InjectedFault, ScriptedFaultInjector
    from tests.generation.handler_exports import invoke

    session = _LifecycleSession()
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    session.profile = profile

    class Provider:
        async def generate(self, request):
            return GenerationProviderResult(
                provider="fake",
                requested_model="fake-v1",
                resolved_model="fake-v1",
                output={"ok": True},
                raw_text='{"ok":true}',
                usage={"output_tokens": 1},
                finish_reason="stop",
            )

    resolver = SimpleNamespace(
        resolve=lambda profile, model: _async_value(
            SimpleNamespace(provider=Provider(), provider_type="fake", model="fake-v1")
        )
    )

    injector = ScriptedFaultInjector({"generation.after_provider_before_persist": 1})
    with pytest.raises(InjectedFault):
        await invoke(
            JobContext(session=session, providers=SimpleNamespace()),
            profile_resolver=resolver,
            profile_id=profile.id,
            prompt=_lifecycle_prompt(),
            purpose="test",
            story_revision_id=None,
            input_payload={"value": "executed"},
            input_hash="a" * 64,
            workflow_job_id=uuid4(),
            workflow_attempt=1,
            validate_output=lambda output: output,
            fault_injector=injector,
        )

    assert injector.hits[0].point == "generation.after_provider_before_persist"
    assert injector.hits[0].context["generation_run_id"] == str(session.run.id)
    assert injector.hits[0].context["generation_attempt_id"] == str(session.attempt.id)
    assert session.commits == 1
    assert session.run.status == session.attempt.status == "running"
    assert session.run.output_payload == {}
    assert session.attempt.response_payload == {}


@pytest.mark.asyncio
async def test_generation_lifecycle_rechecks_prompt_after_durable_attempt_and_closes_read_transaction():
    from app.generation.models import AIProviderProfile
    from app.generation.providers.base import GenerationProviderResult
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import invoke

    session = _LifecycleSession()
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    session.profile = profile
    rechecked = False

    async def before_provider_call():
        nonlocal rechecked
        assert session.commits == 1
        rechecked = True

    class Provider:
        async def generate(self, request):
            assert rechecked is True
            assert session.commits == 2
            return GenerationProviderResult(
                provider="fake",
                requested_model="fake-v1",
                resolved_model="fake-v1",
                output={"ok": True},
                raw_text='{"ok":true}',
                usage={},
                finish_reason="stop",
            )

    resolver = SimpleNamespace(
        resolve=lambda profile_value, model: _async_value(
            SimpleNamespace(provider=Provider(), provider_type="fake", model="fake-v1")
        )
    )
    await invoke(
        JobContext(session=session, providers=SimpleNamespace()),
        profile_resolver=resolver,
        profile_id=profile.id,
        prompt=_lifecycle_prompt(),
        purpose="test",
        story_revision_id=None,
        input_payload={"value": "executed"},
        input_hash="a" * 64,
        workflow_job_id=uuid4(),
        workflow_attempt=1,
        validate_output=lambda output: output,
        before_provider_call=before_provider_call,
    )


@pytest.mark.asyncio
async def test_generation_revalidates_with_session_resolver_and_shared_identity_fallback():
    from app.generation.models import AIProviderProfile
    from app.generation.provider_identity import provider_identity_for_profile
    from app.generation.providers.base import GenerationProviderResult
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import invoke

    session = _LifecycleSession()
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    session.profile = profile
    calls = 0

    class Provider:
        async def generate(self, request):
            return GenerationProviderResult(
                provider="fake",
                requested_model="fake-v1",
                resolved_model="fake-v1",
                output={"ok": True},
                raw_text='{"ok":true}',
                usage={},
                finish_reason="stop",
            )

    class Resolver:
        async def resolve(self, profile_value, model):
            raise AssertionError("session-aware resolver must be used")

        async def resolve_with_session(self, profile_value, model, *, session):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                provider=Provider(),
                provider_type="fake",
                model="fake-v1",
                configuration_revision="",
                configuration_checksum="",
            )

    identity = provider_identity_for_profile(profile)
    run, attempt, _validated = await invoke(
        JobContext(session=session, providers=SimpleNamespace()),
        profile_resolver=Resolver(),
        profile_id=profile.id,
        prompt=_lifecycle_prompt(),
        purpose="test",
        story_revision_id=None,
        input_payload={"value": "executed"},
        input_hash="a" * 64,
        workflow_job_id=uuid4(),
        workflow_attempt=1,
        validate_output=lambda output: output,
        expected_provider_configuration_revision=identity.revision,
        expected_provider_configuration_checksum=identity.checksum,
    )

    assert calls == 2
    assert session.commits == 2
    assert run.status == attempt.status == "succeeded"


@pytest.mark.asyncio
async def test_generation_validation_failure_is_durable_needs_review_not_false_success():
    from app.generation.models import AIProviderProfile
    from app.generation.providers.base import GenerationProviderResult
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import invoke

    session = _LifecycleSession()
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    session.profile = profile

    class Provider:
        async def generate(self, request):
            return GenerationProviderResult(
                provider="fake",
                requested_model="fake-v1",
                resolved_model="fake-v1",
                output={"bad": True},
                raw_text="{}",
                usage={},
                finish_reason="stop",
            )

    resolver = SimpleNamespace(
        resolve=lambda profile, model: _async_value(
            SimpleNamespace(provider=Provider(), provider_type="fake", model="fake-v1")
        )
    )
    with pytest.raises(NeedsReviewJobError):
        await invoke(
            JobContext(session=session, providers=SimpleNamespace()),
            profile_resolver=resolver,
            profile_id=profile.id,
            prompt=_lifecycle_prompt(),
            purpose="test",
            story_revision_id=None,
            input_payload={"value": "executed"},
            input_hash="a" * 64,
            workflow_job_id=uuid4(),
            workflow_attempt=1,
            validate_output=lambda output: (_ for _ in ()).throw(ValueError("invalid")),
        )
    assert session.run.status == session.attempt.status == "failed"
    assert session.run.error_class == session.attempt.error_class == "needs_review"


@pytest.mark.parametrize(
    ("classification", "expected_error", "durable_class"),
    [
        ("retryable", "RetryableJobError", "retryable"),
        ("needs_review", "NeedsReviewJobError", "needs_review"),
        ("permanent", "PermanentJobError", "permanent"),
    ],
)
@pytest.mark.asyncio
async def test_codex_execution_classification_maps_exact_job_and_durable_attempt(
    classification, expected_error, durable_class
):
    from app.core.codex_exec import CodexExecutionError
    from app.generation.models import AIProviderProfile
    from app.jobs import errors as job_errors
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import invoke

    session = _LifecycleSession()
    profile = AIProviderProfile(
        id=uuid4(),
        name="Codex",
        provider_type="codex",
        default_model="gpt-5.4",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    session.profile = profile

    class Provider:
        async def generate(self, request):
            raise CodexExecutionError(
                "unsafe provider detail token=secret",
                classification=classification,
                code=f"codex_{classification}",
            )

    resolver = SimpleNamespace(
        resolve=lambda p, m: _async_value(SimpleNamespace(provider=Provider(), provider_type="codex", model="gpt-5.4"))
    )
    with pytest.raises(getattr(job_errors, expected_error)) as caught:
        await invoke(
            JobContext(session=session, providers=SimpleNamespace()),
            profile_resolver=resolver,
            profile_id=profile.id,
            prompt=_lifecycle_prompt(),
            purpose="test",
            story_revision_id=None,
            input_payload={"value": "executed"},
            input_hash="a" * 64,
            workflow_job_id=uuid4(),
            workflow_attempt=1,
            validate_output=lambda output: output,
        )
    assert caught.value.code == f"codex_{classification}"
    assert session.run.status == session.attempt.status == "failed"
    assert session.run.error_class == session.attempt.error_class == durable_class
    assert "secret" not in session.run.error_message


@pytest.mark.asyncio
async def test_request_time_profile_uses_canonical_availability_resolver():
    from app.generation.editorial_service import EditorialService, InvalidGenerationRequest
    from app.generation.models import AIProviderProfile

    profile = AIProviderProfile(
        id=uuid4(),
        name="Unavailable",
        provider_type="openrouter",
        default_model="model",
        secret_ref="OPENROUTER_API_KEY",
        settings={
            "pricing": {"input_usd_per_million": "1", "output_usd_per_million": "2"},
            "generation_policy": {"qualification_status": "qualified"},
        },
        enabled=True,
    )

    class Session:
        async def scalar(self, statement):
            return profile

    class Resolver:
        called = False

        async def validate_availability(self, selected, override):
            self.called = True
            assert selected is profile
            raise RuntimeError("secret unavailable")

    resolver = Resolver()
    with pytest.raises(InvalidGenerationRequest, match="unavailable"):
        await EditorialService(Session(), profile_resolver=resolver)._require_profile(profile.id)
    assert resolver.called is True


@pytest.mark.asyncio
async def test_completed_stage_reuses_durable_output_without_second_provider_call():
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.models import AIProviderProfile, GenerationAttempt, GenerationRun
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import invoke

    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    prompt = _lifecycle_prompt()
    job_id = uuid4()
    stage_hash = "a" * 64
    durable_hash = sha256_canonical(
        {
            "workflow_job_id": str(job_id),
            "stage_input_hash": stage_hash,
            "resolved_model": "fake-v1",
            "purpose": "test",
        }
    )
    run = GenerationRun(
        id=uuid4(),
        story_revision_id=None,
        provider_profile_id=profile.id,
        prompt_template_version_id=prompt.id,
        requested_model="fake-v1",
        status="succeeded",
        input_hash=durable_hash,
        request_payload={},
        output_payload={"ok": True},
    )
    attempt = GenerationAttempt(
        id=uuid4(),
        generation_run_id=run.id,
        attempt_number=1,
        provider="fake",
        requested_model="fake-v1",
        resolved_model="fake-v1",
        prompt_snapshot={},
        response_payload={"ok": True},
        usage={},
        validation_errors=[],
        status="succeeded",
        started_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    session = _LifecycleSession(existing=run, completed_attempt=attempt)
    session.profile = profile

    class Provider:
        async def generate(self, request):
            raise AssertionError("completed stage called provider twice")

    resolver = SimpleNamespace(
        resolve=lambda p, m: _async_value(SimpleNamespace(provider=Provider(), provider_type="fake", model="fake-v1"))
    )
    reused_run, reused_attempt, output = await invoke(
        JobContext(session=session, providers=SimpleNamespace()),
        profile_resolver=resolver,
        profile_id=profile.id,
        prompt=prompt,
        purpose="test",
        story_revision_id=None,
        input_payload={"value": "executed"},
        input_hash=stage_hash,
        workflow_job_id=job_id,
        workflow_attempt=2,
        validate_output=lambda value: value,
    )
    assert (reused_run.id, reused_attempt.id, output) == (run.id, attempt.id, {"ok": True})


@pytest.mark.parametrize(
    ("builder_name", "payload", "expected_code"),
    [
        (
            "build_canonical_generation_handler",
            {
                "story_id": str(uuid4()),
                "canonical_prompt_template_version_id": str(uuid4()),
                "generation_provider_profile_id": str(uuid4()),
            },
            "generation_story_inactive",
        ),
        (
            "build_pack_generation_handler",
            {
                "story_revision_id": str(uuid4()),
                "platform_prompt_template_version_id": str(uuid4()),
                "brand_profile_id": str(uuid4()),
                "generation_provider_profile_id": str(uuid4()),
            },
            "generation_story_revision_missing",
        ),
        (
            "build_regenerate_handler",
            {"variant_id": str(uuid4())},
            "generation_variant_missing",
        ),
    ],
)
@pytest.mark.asyncio
async def test_missing_handler_context_is_typed_permanent_and_never_calls_provider(
    builder_name, payload, expected_code
):
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext
    from tests.generation import handler_exports

    class Session:
        async def get(self, model, identifier):
            return None

        async def scalar(self, statement):
            return None

    class Resolver:
        async def resolve(self, profile, model):
            raise AssertionError("invalid precondition called provider resolver")

    handler = getattr(handler_exports, builder_name)(Resolver())
    with pytest.raises(PermanentJobError) as caught:
        await handler(
            SimpleNamespace(id=uuid4(), attempt_count=1, payload=payload),
            JobContext(session=Session(), providers=SimpleNamespace()),
        )
    assert caught.value.code == expected_code


@pytest.mark.asyncio
async def test_malformed_generation_payload_is_typed_permanent_before_provider():
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import build_canonical_generation_handler

    handler = build_canonical_generation_handler(SimpleNamespace())
    with pytest.raises(PermanentJobError) as caught:
        await handler(
            SimpleNamespace(id=uuid4(), attempt_count=1, payload={"story_id": "bad"}),
            JobContext(session=SimpleNamespace(), providers=SimpleNamespace()),
        )
    assert caught.value.code == "generation_job_payload_invalid"


@pytest.mark.asyncio
async def test_request_enqueue_does_not_mark_story_drafted_before_pack_artifact():
    from app.generation.editorial_service import EditorialService, GeneratePackRequest
    from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplateVersion
    from app.jobs.types import JobStatus
    from app.stories.models import Story

    prompts = [
        PromptTemplateVersion(
            id=uuid4(),
            prompt_template_id=uuid4(),
            version=1,
            system_template="s",
            user_template="u",
            output_schema_version="v",
            output_schema={},
            checksum_sha256="a" * 64,
            is_active=True,
        ),
        PromptTemplateVersion(
            id=uuid4(),
            prompt_template_id=uuid4(),
            version=1,
            system_template="s",
            user_template="u",
            output_schema_version="v",
            output_schema={},
            checksum_sha256="b" * 64,
            is_active=True,
        ),
    ]
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    story = Story(id=uuid4(), title="Story", status="inbox", primary_language="en")
    brand = BrandProfile(
        id=uuid4(),
        name="Brand",
        output_language="en",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=False,
    )

    class Session:
        def __init__(self):
            self.values = [*prompts, profile, story]

        async def scalars(self, statement):
            return [self.values.pop(0)]

        async def scalar(self, statement):
            return self.values.pop(0)

        async def get(self, model, identifier):
            return brand

        async def flush(self):
            return None

    class Jobs:
        async def enqueue_job(self, **kwargs):
            return SimpleNamespace(job=SimpleNamespace(id=uuid4(), status=JobStatus.QUEUED), created=True)

    request = GeneratePackRequest(
        brand_profile_id=brand.id,
        platforms=["telegram"],
        generation_provider_profile_id=profile.id,
    )
    await EditorialService(Session(), jobs=Jobs()).request_content_pack(story.id, request)
    assert story.status == "inbox"


@pytest.mark.asyncio
async def test_request_content_pack_binds_only_a_succeeded_same_story_research_result():
    from app.generation.editorial_service import EditorialService, GeneratePackRequest
    from app.generation.models import AIProviderProfile, BrandProfile
    from app.jobs.types import JobStatus
    from app.research.models import ResearchRun
    from app.stories.models import Story, StoryRevision

    story = Story(id=uuid4(), title="Story", status="inbox", primary_language="en")
    result_revision = StoryRevision(id=uuid4(), story_id=story.id, revision_number=2)
    run = ResearchRun(
        id=uuid4(),
        story_id=story.id,
        requested_mode="manual",
        status="succeeded",
        result_story_revision_id=result_revision.id,
    )
    prompts = [
        SimpleNamespace(id=uuid4(), checksum_sha256="a" * 64),
        SimpleNamespace(id=uuid4(), checksum_sha256="b" * 64),
    ]
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    brand = BrandProfile(
        id=uuid4(),
        name="Brand",
        output_language="en",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=False,
    )

    class Session:
        def __init__(self):
            self.values = [*prompts, profile, story]

        async def scalars(self, statement):
            return [self.values.pop(0)]

        async def scalar(self, statement):
            return self.values.pop(0)

        async def get(self, model, identifier):
            return {BrandProfile: brand, ResearchRun: run, StoryRevision: result_revision}[model]

        async def flush(self):
            return None

    class Jobs:
        kwargs = None

        async def enqueue_job(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(job=SimpleNamespace(id=uuid4(), status=JobStatus.QUEUED), created=True)

    jobs = Jobs()
    await EditorialService(Session(), jobs=jobs).request_content_pack(
        story.id,
        GeneratePackRequest(
            brand_profile_id=brand.id,
            platforms=["telegram"],
            generation_provider_profile_id=profile.id,
            research_run_id=run.id,
        ),
    )
    assert jobs.kwargs["payload"]["completed_research_run_id"] == str(run.id)
    assert jobs.kwargs["payload"]["research_result_story_revision_id"] == str(result_revision.id)
    assert "research_run_id" not in jobs.kwargs["payload"]


@pytest.mark.asyncio
async def test_request_content_pack_resolves_and_snapshots_default_editorial_profile():
    from app.generation.editorial_service import EditorialService, GeneratePackRequest
    from app.generation.models import AIProviderProfile, BrandProfile
    from app.jobs.types import JobStatus
    from app.stories.models import Story

    prompts = [
        SimpleNamespace(id=uuid4(), checksum_sha256="a" * 64),
        SimpleNamespace(id=uuid4(), checksum_sha256="b" * 64),
    ]
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    story = Story(id=uuid4(), title="Story", status="inbox", primary_language="en")
    default_brand = BrandProfile(
        id=uuid4(),
        name="Default newsroom",
        output_language="en",
        tone="analytical",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=True,
    )

    class Session:
        def __init__(self):
            self.values = [*prompts, profile, story, default_brand]

        async def scalars(self, statement):
            return [self.values.pop(0)]

        async def scalar(self, statement):
            return self.values.pop(0)

        async def get(self, model, identifier):
            raise AssertionError("an omitted profile must resolve through the default query")

        async def flush(self):
            return None

    class Jobs:
        kwargs = None

        async def enqueue_job(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                job=SimpleNamespace(id=uuid4(), status=JobStatus.QUEUED),
                created=True,
            )

    jobs = Jobs()
    await EditorialService(Session(), jobs=jobs).request_content_pack(
        story.id,
        GeneratePackRequest(
            platforms=["telegram"],
            generation_provider_profile_id=profile.id,
        ),
    )

    assert jobs.kwargs["payload"]["brand_profile_id"] == str(default_brand.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["failed", "cross_story"])
async def test_request_content_pack_rejects_failed_or_cross_story_research_run(failure):
    from app.generation.editorial_service import EditorialService, GeneratePackRequest, InvalidGenerationRequest
    from app.generation.models import AIProviderProfile, BrandProfile
    from app.research.models import ResearchRun
    from app.stories.models import Story, StoryRevision

    story = Story(id=uuid4(), title="Story", status="inbox", primary_language="en")
    run_story_id = uuid4() if failure == "cross_story" else story.id
    result_revision = StoryRevision(id=uuid4(), story_id=run_story_id, revision_number=2)
    run = ResearchRun(
        id=uuid4(),
        story_id=run_story_id,
        requested_mode="manual",
        status="failed" if failure == "failed" else "succeeded",
        result_story_revision_id=result_revision.id,
    )
    prompts = [
        SimpleNamespace(id=uuid4(), checksum_sha256="a" * 64),
        SimpleNamespace(id=uuid4(), checksum_sha256="b" * 64),
    ]
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    brand = BrandProfile(
        id=uuid4(),
        name="Brand",
        output_language="en",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={},
        is_default=False,
    )

    class Session:
        def __init__(self):
            self.values = [*prompts, profile, story]

        async def scalars(self, statement):
            return [self.values.pop(0)]

        async def scalar(self, statement):
            return self.values.pop(0)

        async def get(self, model, identifier):
            return {BrandProfile: brand, ResearchRun: run, StoryRevision: result_revision}[model]

        async def flush(self):
            return None

    with pytest.raises(InvalidGenerationRequest, match="succeeded result for this story"):
        await EditorialService(Session(), jobs=SimpleNamespace()).request_content_pack(
            story.id,
            GeneratePackRequest(
                brand_profile_id=brand.id,
                platforms=["telegram"],
                generation_provider_profile_id=profile.id,
                research_run_id=run.id,
            ),
        )


@pytest.mark.asyncio
async def test_superseded_after_enqueue_is_locked_and_rejected_before_provider_or_artifact():
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import build_canonical_generation_handler

    class Session:
        def __init__(self):
            self.added = []

        async def scalar(self, statement):
            return None

        async def get(self, model, identifier):
            return None

        def add(self, value):
            self.added.append(value)

    class Resolver:
        call_count = 0

        async def resolve(self, profile, model):
            self.call_count += 1
            raise AssertionError("superseded story called provider")

    session = Session()
    resolver = Resolver()
    handler = build_canonical_generation_handler(resolver)
    with pytest.raises(PermanentJobError) as caught:
        await handler(
            SimpleNamespace(
                id=uuid4(),
                attempt_count=1,
                payload={
                    "story_id": str(uuid4()),
                    "canonical_prompt_template_version_id": str(uuid4()),
                    "generation_provider_profile_id": str(uuid4()),
                },
            ),
            JobContext(session=session, providers=SimpleNamespace()),
        )
    assert caught.value.code == "generation_story_inactive"
    assert resolver.call_count == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_canonical_handler_rechecks_exact_active_prompt_immediately_before_provider(monkeypatch):
    import hashlib
    from datetime import UTC, datetime

    from app.generation.models import PromptTemplate, PromptTemplateVersion
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import build_canonical_generation_handler

    story_id, prompt_id, template_id, snapshot_id = uuid4(), uuid4(), uuid4(), uuid4()
    story = SimpleNamespace(id=story_id, title="Grounded", superseded_by_id=None)
    prompt = SimpleNamespace(
        id=prompt_id,
        prompt_template_id=template_id,
        checksum_sha256="a" * 64,
        system_template="System",
        user_template="Story={story_title}; evidence={evidence_json}",
        output_schema={},
    )
    template = SimpleNamespace(id=template_id, purpose_key="canonical_story")
    snapshot = SimpleNamespace(
        id=snapshot_id,
        story_id=story_id,
        evidence_key="evidence:one",
        content_item_id=None,
        title="Evidence",
        content_text="Evidence",
        content_sha256=hashlib.sha256(b"Evidence").hexdigest(),
        source_url="https://example.com/report",
        authors=[],
        published_at=None,
        captured_at=datetime.now(UTC),
    )

    class Session:
        async def scalar(self, statement):
            return story

        async def get(self, model, identifier):
            return {
                (PromptTemplateVersion, prompt_id): prompt,
                (PromptTemplate, template_id): template,
            }.get((model, identifier))

        async def scalars(self, statement):
            return [snapshot]

    provider_calls = 0

    async def recheck(session, expected_prompt_id, expected_checksum):
        assert expected_prompt_id == prompt_id
        assert expected_checksum == "a" * 64
        raise PermanentJobError(
            code="generation_canonical_prompt_configuration_invalid",
            message="Canonical prompt drifted",
        )

    async def invoke(context, **kwargs):
        nonlocal provider_calls
        await kwargs["before_provider_call"]()
        provider_calls += 1
        raise AssertionError("drifted canonical prompt reached provider")

    monkeypatch.setattr(
        "app.generation.canonical_generation._require_exact_active_canonical_prompt",
        recheck,
        raising=False,
    )
    monkeypatch.setattr("app.generation.canonical_generation.invoke", invoke)

    with pytest.raises(PermanentJobError) as caught:
        await build_canonical_generation_handler(SimpleNamespace())(
            SimpleNamespace(
                id=uuid4(),
                attempt_count=1,
                payload={
                    "story_id": str(story_id),
                    "canonical_prompt_template_version_id": str(prompt_id),
                    "canonical_prompt_checksum": "a" * 64,
                    "generation_provider_profile_id": str(uuid4()),
                },
            ),
            JobContext(session=Session(), providers=SimpleNamespace()),
        )

    assert caught.value.code == "generation_canonical_prompt_configuration_invalid"
    assert provider_calls == 0


@pytest.mark.asyncio
async def test_generation_rejects_provider_configuration_drift_before_provider_call():
    from app.generation.models import AIProviderProfile
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext
    from tests.generation.handler_exports import invoke

    session = _LifecycleSession()
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    session.profile = profile

    class Provider:
        async def generate(self, request):
            raise AssertionError("drifted provider must not be called")

    checksums = iter(("a" * 64, "b" * 64))

    async def resolve(profile_value, model):
        checksum = next(checksums)
        return SimpleNamespace(
            provider=Provider(),
            provider_type="fake",
            model="fake-v1",
            configuration_revision=checksum[:16],
            configuration_checksum=checksum,
        )

    with pytest.raises(PermanentJobError) as caught:
        await invoke(
            JobContext(session=session, providers=SimpleNamespace()),
            profile_resolver=SimpleNamespace(resolve=resolve),
            profile_id=profile.id,
            prompt=_lifecycle_prompt(),
            purpose="test",
            story_revision_id=None,
            input_payload={"value": "executed"},
            input_hash="a" * 64,
            workflow_job_id=uuid4(),
            workflow_attempt=1,
            validate_output=lambda output: output,
            expected_provider_configuration_revision="a" * 16,
            expected_provider_configuration_checksum="a" * 64,
        )

    assert caught.value.code == "generation_provider_configuration_changed"
    assert session.attempt.error_class == "permanent"
