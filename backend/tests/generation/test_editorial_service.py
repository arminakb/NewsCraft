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

    def begin(self):
        return _Tx()


def _lifecycle_prompt():
    from app.generation.default_prompts import telegram_prompt_checksum
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
        checksum_sha256=telegram_prompt_checksum(system, user, schema),
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


@pytest.mark.asyncio
async def test_release_three_telegram_continuation_normalizes_and_completes_after_upgrade(monkeypatch):
    from app.research.continuations import enqueue_bound_continuation, normalize_continuation

    story_id = uuid4()
    research_profile_id = uuid4()
    subscriber = "d" * 64
    prompt_id = uuid4()
    descriptor = {
        "job_type": "content_pack.generate",
        "payload": {
            "story_id": str(story_id),
            "brand_profile_id": str(uuid4()),
            "platform": "telegram",
            "generation_provider_profile_id": str(uuid4()),
            "canonical_prompt_template_version_id": str(uuid4()),
            "platform_prompt_template_version_id": str(prompt_id),
            "research_mode": "auto_if_incomplete",
            "research_provider_profile_id": str(research_profile_id),
            "canonical_prompt_checksum": "b" * 64,
            "platform_prompt_checksum": "c" * 64,
        },
        "idempotency_prefix": f"content-pack:{story_id}:{subscriber}",
        "subscriber_id": subscriber,
        "expected_story_id": str(story_id),
        "expected_provider_profile_id": str(research_profile_id),
    }

    normalized = normalize_continuation(descriptor)
    assert normalized["payload"]["platforms"] == ["telegram"]
    assert normalized["payload"]["platform_prompt_template_version_ids"] == {
        "telegram": str(prompt_id)
    }
    assert normalized["payload"]["platform_prompt_checksums"] == {"telegram": "c" * 64}
    assert "platform" not in normalized["payload"]
    assert "platform_prompt_template_version_id" not in normalized["payload"]
    assert "platform_prompt_checksum" not in normalized["payload"]

    calls = []

    class Jobs:
        def __init__(self, session):
            pass

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(job=SimpleNamespace(id=uuid4()), created=True)

    monkeypatch.setattr("app.research.continuations.JobRepository", Jobs)
    run = SimpleNamespace(
        id=uuid4(),
        story_id=story_id,
        provider_profile_id=research_profile_id,
    )
    result_revision = SimpleNamespace(id=uuid4(), story_id=story_id)
    await enqueue_bound_continuation(
        SimpleNamespace(),
        descriptor=descriptor,
        run=run,
        result_revision=result_revision,
    )

    assert calls[0]["payload"]["platforms"] == ["telegram"]
    assert calls[0]["payload"]["platform_prompt_template_version_ids"] == {
        "telegram": str(prompt_id)
    }
    assert calls[0]["payload"]["platform_prompt_checksums"] == {"telegram": "c" * 64}
    assert calls[0]["payload"]["completed_research_run_id"] == str(run.id)
    assert calls[0]["payload"]["research_result_story_revision_id"] == str(result_revision.id)


@pytest.mark.parametrize("mutation", ["non_telegram", "ambiguous", "extra"])
def test_release_three_continuation_translation_rejects_unsafe_legacy_shapes(mutation):
    from app.research.continuations import normalize_continuation

    story_id = uuid4()
    research_profile_id = uuid4()
    subscriber = "e" * 64
    payload = {
        "story_id": str(story_id),
        "brand_profile_id": str(uuid4()),
        "platform": "telegram",
        "generation_provider_profile_id": str(uuid4()),
        "canonical_prompt_template_version_id": str(uuid4()),
        "platform_prompt_template_version_id": str(uuid4()),
        "research_mode": "auto_if_incomplete",
        "research_provider_profile_id": str(research_profile_id),
        "canonical_prompt_checksum": "b" * 64,
        "platform_prompt_checksum": "c" * 64,
    }
    if mutation == "non_telegram":
        payload["platform"] = "instagram"
    elif mutation == "ambiguous":
        payload["platforms"] = ["telegram"]
    else:
        payload["provider_type"] = "fake"
    descriptor = {
        "job_type": "content_pack.generate",
        "payload": payload,
        "idempotency_prefix": f"content-pack:{story_id}:{subscriber}",
        "subscriber_id": subscriber,
        "expected_story_id": str(story_id),
        "expected_provider_profile_id": str(research_profile_id),
    }

    with pytest.raises(ValueError):
        normalize_continuation(descriptor)


def test_rendered_prompt_executes_the_immutable_operator_user_template():
    from types import SimpleNamespace

    from app.generation.handlers import render_prompt_messages

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


def test_instruction_changes_rendered_telegram_prompt_and_input_hash():
    from types import SimpleNamespace

    from app.generation.handlers import render_prompt_messages, stage_input_hash

    prompt = SimpleNamespace(
        system_template="Telegram exact",
        user_template="Story={canonical_story_json}; instruction={instruction}",
    )
    first = render_prompt_messages(prompt, {"canonical_story_json": "{}", "instruction": "Short"})
    second = render_prompt_messages(prompt, {"canonical_story_json": "{}", "instruction": "Formal"})
    assert first[1].content != second[1].content
    assert stage_input_hash({"message": first[1].content}) != stage_input_hash({"message": second[1].content})


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_generation_lifecycle_commits_running_attempt_before_provider_and_validates_before_success():
    from app.generation.handlers import _invoke
    from app.generation.models import AIProviderProfile
    from app.generation.providers.base import GenerationProviderResult
    from app.jobs.registry import JobContext

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
    run, attempt, validated = await _invoke(
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
async def test_generation_lifecycle_rechecks_prompt_after_durable_attempt_and_closes_read_transaction():
    from app.generation.handlers import _invoke
    from app.generation.models import AIProviderProfile
    from app.generation.providers.base import GenerationProviderResult
    from app.jobs.registry import JobContext

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
    await _invoke(
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
async def test_generation_validation_failure_is_durable_needs_review_not_false_success():
    from app.generation.handlers import _invoke
    from app.generation.models import AIProviderProfile
    from app.generation.providers.base import GenerationProviderResult
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext

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
        await _invoke(
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
    from app.generation.handlers import _invoke
    from app.generation.models import AIProviderProfile
    from app.jobs import errors as job_errors
    from app.jobs.registry import JobContext

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
        await _invoke(
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
        settings={},
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
    from app.generation.handlers import _invoke
    from app.generation.models import AIProviderProfile, GenerationAttempt, GenerationRun
    from app.jobs.registry import JobContext

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
    reused_run, reused_attempt, output = await _invoke(
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
    from app.generation import handlers
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext

    class Session:
        async def get(self, model, identifier):
            return None

        async def scalar(self, statement):
            return None

    class Resolver:
        async def resolve(self, profile, model):
            raise AssertionError("invalid precondition called provider resolver")

    handler = getattr(handlers, builder_name)(Resolver())
    with pytest.raises(PermanentJobError) as caught:
        await handler(
            SimpleNamespace(id=uuid4(), attempt_count=1, payload=payload),
            JobContext(session=Session(), providers=SimpleNamespace()),
        )
    assert caught.value.code == expected_code


@pytest.mark.asyncio
async def test_malformed_generation_payload_is_typed_permanent_before_provider():
    from app.generation.handlers import build_canonical_generation_handler
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext

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
    from app.generation.handlers import build_canonical_generation_handler
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext

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

    from app.generation.handlers import build_canonical_generation_handler
    from app.generation.models import PromptTemplate, PromptTemplateVersion
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext

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
        "app.generation.handlers._require_exact_active_canonical_prompt",
        recheck,
        raising=False,
    )
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

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
