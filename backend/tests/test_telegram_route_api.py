from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.telegram_automations import (
    _materialize_route_out,
    activate_route,
    automation_options,
    backfill_route,
    create_route,
    dry_run_route,
    pause_route,
    resume_route,
    update_prompt_policy,
)
from app.api.telegram_schemas import (
    TelegramPromptPolicyInput,
    TelegramRouteBackfillIn,
    TelegramRouteCreate,
    TelegramRouteOut,
)
from app.automations.models import AutomationRoute, TelegramSourceConfig
from app.db.models import Source
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplate, PromptTemplateVersion
from app.generation.provider_settings import default_codex_provider_settings
from app.jobs.errors import JobCapabilityUnavailable
from app.jobs.repository import EnqueueJobResult
from app.jobs.types import JobStatus
from app.llm_providers.models import LLMProvider
from app.publishing.models import Destination
from tests.capability_fakes import AVAILABLE_CAPABILITIES, StaticCapabilityStatusService


def valid_route_payload() -> dict:
    return {
        "name": "Rewrite source to newsroom",
        "source_id": uuid4(),
        "destination_id": uuid4(),
        "brand_profile_id": uuid4(),
        "prompt_template_version_id": uuid4(),
        "prompt_policy": "pinned",
        "ai_provider_profile_id": uuid4(),
        "access_mode": "public_html",
        "content_filters": {"model": "openai/gpt-5-mini"},
    }


def test_route_defaults_to_new_only_review_preserve_and_research_off():
    value = TelegramRouteCreate.model_validate(valid_route_payload())

    assert value.research_mode == "off"
    assert value.media_policy == "preserve"
    assert value.publishing_policy == "review_required"
    assert value.poll_interval_seconds == 300
    assert value.confirm_auto_publish is False
    assert value.prompt_policy == "pinned"


def test_new_route_requires_explicit_prompt_policy():
    payload = valid_route_payload()
    payload.pop("prompt_policy")

    with pytest.raises(ValidationError):
        TelegramRouteCreate.model_validate(payload)


def test_route_output_exposes_poll_and_resource_timestamps():
    now = datetime.now(UTC)
    route = saved_route()
    route.last_polled_at = now - timedelta(minutes=5)
    route.next_poll_at = now + timedelta(minutes=5)
    route.created_at = now - timedelta(days=1)
    route.updated_at = now

    output = TelegramRouteOut.model_validate(route)

    assert output.last_polled_at == route.last_polled_at
    assert output.next_poll_at == route.next_poll_at
    assert output.created_at == route.created_at
    assert output.updated_at == route.updated_at


async def test_route_materializer_refreshes_every_public_scalar_before_copying():
    route = saved_route()
    session = RouteSession(route)

    output = await _materialize_route_out(session, route)

    assert output == TelegramRouteOut.model_validate(route)
    assert session.calls == [
        "flush",
        ("refresh", tuple(TelegramRouteOut.model_fields)),
    ]


def test_auto_publish_requires_explicit_confirmation():
    payload = {**valid_route_payload(), "publishing_policy": "auto_publish"}

    with pytest.raises(ValidationError, match="confirm_auto_publish"):
        TelegramRouteCreate.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"count": 5, "since": "2026-07-10T00:00:00Z"},
        {"count": 0},
        {"count": 101},
        {"since": (datetime.now(UTC) - timedelta(days=31)).isoformat()},
        {"since": datetime.now().isoformat()},
    ],
)
def test_backfill_requires_one_safe_bound(payload):
    with pytest.raises(ValidationError):
        TelegramRouteBackfillIn.model_validate(payload)


def test_route_rejects_unknown_content_filter_and_non_off_research():
    with pytest.raises(ValidationError):
        TelegramRouteCreate.model_validate({**valid_route_payload(), "content_filters": {"unknown": True}})
    with pytest.raises(ValidationError):
        TelegramRouteCreate.model_validate({**valid_route_payload(), "research_mode": "deep"})


async def test_activation_enqueues_initialization_without_backfill_or_network():
    route = saved_route()
    session = RouteSession(route)
    jobs = FakeJobs()

    result = await activate_route(route.id, session, jobs, AVAILABLE_CAPABILITIES)

    assert result.route.enabled is True
    assert route.cursor_state["status"] == "initializing"
    assert route.cursor_state["activation_message_id"] is None
    assert route.cursor_state["last_message_id"] is None
    assert route.backfill_limit is None
    assert route.backfill_since is None
    assert jobs.enqueued[0]["job_type"] == "telegram.route.initialize"


@pytest.mark.parametrize("status", ["unavailable", "unknown", "stale"])
async def test_activation_rejects_non_current_worker_capability_status(status):
    route = saved_route()
    session = RouteSession(route)
    jobs = FakeJobs()

    with pytest.raises(JobCapabilityUnavailable):
        await activate_route(
            route.id,
            session,
            jobs,
            StaticCapabilityStatusService(status),
        )

    assert route.enabled is False
    assert jobs.enqueued == []


async def test_replayed_activation_locks_route_and_reuses_initialization_identity_without_reset():
    route = saved_route()
    route.enabled = True
    route.cursor_state = {
        "status": "initializing",
        "activation_requested_at": "2026-07-12T09:00:00+00:00",
        "activation_boundary_at": "2026-07-12T09:00:01+00:00",
        "activation_message_id": 900,
        "last_message_id": 901,
        "recent_fingerprints": {"901": "hash"},
    }
    original_state = route.cursor_state
    session = RouteSession(route)
    jobs = FakeJobs()

    first = await activate_route(route.id, session, jobs, AVAILABLE_CAPABILITIES)
    second = await activate_route(route.id, session, jobs, AVAILABLE_CAPABILITIES)

    assert session.route_lock_count == 2
    assert route.cursor_state is original_state
    assert route.cursor_state["activation_boundary_at"] == "2026-07-12T09:00:01+00:00"
    assert route.cursor_state["last_message_id"] == 901
    assert jobs.enqueued[0]["idempotency_key"] == jobs.enqueued[1]["idempotency_key"]
    assert first.job.job_id == second.job.job_id


async def test_backfill_and_dry_run_enqueue_without_mutating_live_cursor():
    route = saved_route()
    route.publishing_policy = "auto_publish"
    session = RouteSession(route)
    jobs = FakeJobs()
    original_cursor = dict(route.cursor_state)

    backfill = await backfill_route(
        route.id,
        TelegramRouteBackfillIn.model_validate({"count": 20}),
        session,
        jobs,
        AVAILABLE_CAPABILITIES,
    )
    dry_run = await dry_run_route(
        route.id,
        SimpleNamespace(source_message_id=912),
        session,
        jobs,
        AVAILABLE_CAPABILITIES,
    )

    assert route.cursor_state == original_cursor
    assert route.backfill_limit is None
    assert route.backfill_since is None
    assert jobs.enqueued[0]["job_type"] == "telegram.route.backfill"
    assert jobs.enqueued[0]["payload"]["count"] == 20
    assert jobs.enqueued[1]["job_type"] == "telegram.route.dry_run"
    assert jobs.enqueued[1]["payload"]["force_review"] is True
    assert backfill.route.id == route.id
    assert dry_run.route.id == route.id


async def test_pause_and_resume_change_only_paused_at():
    route = saved_route()
    session = RouteSession(route)
    original_cursor = dict(route.cursor_state)

    paused = await pause_route(route.id, session)
    assert paused.paused_at is not None
    resumed = await resume_route(route.id, session, AVAILABLE_CAPABILITIES)

    assert resumed.paused_at is None
    assert route.cursor_state == original_cursor
    assert route.enabled is False


async def test_route_response_is_a_snapshot_before_commit_invalidates_the_orm_object():
    route = saved_route()
    original_name = route.name
    original_updated_at = route.updated_at
    session = InvalidatingCommitSession(route)

    response = await pause_route(route.id, session)

    assert response.name == original_name
    assert response.updated_at == original_updated_at
    assert route.name == "invalidated after commit"
    assert route.updated_at is None


async def test_commit_failure_never_returns_a_materialized_success_response():
    route = saved_route()
    session = FailingCommitSession(route)

    with pytest.raises(RuntimeError, match="commit failed"):
        await pause_route(route.id, session)

    assert session.calls[-1] == "commit"


async def test_route_create_validates_references_and_options_omit_all_secret_references():
    source = Source(
        id=uuid4(),
        platform="telegram_public",
        name="Source",
        source_group="telegram",
        language_hint="fa",
    )
    source_config = TelegramSourceConfig(
        source_id=source.id,
        access_mode="public_html",
        channel_ref="source_channel",
    )
    destination = Destination(
        id=uuid4(),
        name="Destination",
        platform="telegram",
        target_ref="@destination",
        secret_ref="TELEGRAM_DESTINATION_TOKEN",
        enabled=True,
        health_status="healthy",
        administrator_status="administrator",
        settings={},
    )
    brand = BrandProfile(
        id=uuid4(),
        name="Brand",
        output_language="fa",
        tone="neutral",
    )
    prompt = PromptTemplate(id=uuid4(), purpose_key="telegram_rewrite", name="Rewrite")
    version = PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=prompt.id,
        version=1,
        system_template="system",
        user_template="user",
        output_schema_version="telegram_rewrite.v1",
        checksum_sha256="a" * 64,
        is_active=True,
    )
    provider = AIProviderProfile(
        id=uuid4(),
        name="OpenRouter",
        provider_type="openrouter",
        default_model="openai/gpt-5-mini",
        secret_ref="OPENROUTER_EDITOR_KEY",
        settings={
            "pricing": {
                "input_usd_per_million": "0",
                "output_usd_per_million": "0",
            },
            "generation_policy": {"qualification_status": "qualified"},
        },
        enabled=True,
    )
    orphan = Source(
        id=uuid4(),
        platform="telegram_public",
        name="Orphan without transport config",
        source_group="telegram",
    )
    session = ConfigurationSession([source, source_config, orphan, destination, brand, prompt, version, provider])
    payload = {
        **valid_route_payload(),
        "source_id": source.id,
        "destination_id": destination.id,
        "brand_profile_id": brand.id,
        "prompt_template_version_id": version.id,
        "ai_provider_profile_id": provider.id,
    }

    route = await create_route(TelegramRouteCreate.model_validate(payload), session)
    replayed = await create_route(TelegramRouteCreate.model_validate(payload), session)
    options = await automation_options(session, AVAILABLE_CAPABILITIES)

    assert replayed == route
    assert route.cursor_state == {"status": "not_initialized"}
    assert route.enabled is False
    assert options.sources[0]["id"] == source.id
    assert options.sources[0]["capability_state"].status == "available"
    assert options.ai_provider_profiles[0]["configured"] is True
    assert "secret_ref" not in str(options)
    assert "OPENROUTER_EDITOR_KEY" not in str(options)
    assert "TELEGRAM_DESTINATION_TOKEN" not in str(options)
    assert session.source_lock_count == 2

    with pytest.raises(HTTPException) as conflict:
        await create_route(
            TelegramRouteCreate.model_validate({**payload, "media_policy": "omit"}),
            session,
        )
    assert conflict.value.status_code == 409
    assert session.source_lock_count == 3


async def test_prompt_policy_switch_requires_confirmation_and_tracks_active_or_pinned_version():
    route = saved_route()
    template = PromptTemplate(
        id=uuid4(),
        purpose_key="telegram_rewrite",
        name="Rewrite",
    )
    pinned = PromptTemplateVersion(
        id=route.prompt_template_version_id,
        prompt_template_id=template.id,
        version=1,
        system_template="system one",
        user_template="user one",
        output_schema_version="telegram_rewrite.v1",
        output_schema={},
        checksum_sha256="a" * 64,
        is_active=False,
    )
    active = PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=template.id,
        version=2,
        system_template="system two",
        user_template="user two",
        output_schema_version="telegram_rewrite.v1",
        output_schema={},
        checksum_sha256="b" * 64,
        is_active=True,
    )
    session = ConfigurationSession([route, template, pinned, active])

    with pytest.raises(ValidationError, match="confirm_change"):
        TelegramPromptPolicyInput.model_validate({"prompt_policy": "follow_active", "confirm_change": False})

    followed = await update_prompt_policy(
        route.id,
        TelegramPromptPolicyInput(
            prompt_policy="follow_active",
            confirm_change=True,
        ),
        session,
    )
    assert followed.prompt_policy == "follow_active"
    assert followed.prompt_template_version_id == active.id

    repinned = await update_prompt_policy(
        route.id,
        TelegramPromptPolicyInput(
            prompt_policy="pinned",
            prompt_template_version_id=pinned.id,
            confirm_change=True,
        ),
        session,
    )
    assert repinned.prompt_policy == "pinned"
    assert repinned.prompt_template_version_id == pinned.id


def codex_route_configuration():
    source = Source(id=uuid4(), platform="telegram_public", name="Source", source_group="telegram")
    config = TelegramSourceConfig(source_id=source.id, access_mode="public_html", channel_ref="source_channel")
    destination = Destination(
        id=uuid4(),
        name="Destination",
        platform="telegram",
        target_ref="@destination",
        secret_ref="TELEGRAM_DESTINATION_TOKEN",
        enabled=True,
        health_status="healthy",
        administrator_status="administrator",
        settings={},
    )
    brand = BrandProfile(id=uuid4(), name="Brand", output_language="fa", tone="neutral")
    prompt = PromptTemplate(id=uuid4(), purpose_key="telegram_rewrite", name="Rewrite")
    version = PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=prompt.id,
        version=1,
        system_template="system",
        user_template="user",
        output_schema_version="telegram_rewrite.v1",
        checksum_sha256="a" * 64,
        is_active=True,
    )
    provider = AIProviderProfile(
        id=uuid4(),
        name="Codex CLI",
        provider_type="codex",
        default_model="gpt-5.4",
        secret_ref=None,
        settings=default_codex_provider_settings().model_dump(mode="json"),
        enabled=True,
    )
    session = ConfigurationSession([source, config, destination, brand, prompt, version, provider])
    payload = TelegramRouteCreate.model_validate(
        {
            **valid_route_payload(),
            "source_id": source.id,
            "destination_id": destination.id,
            "brand_profile_id": brand.id,
            "prompt_template_version_id": version.id,
            "ai_provider_profile_id": provider.id,
            "content_filters": {},
        }
    )
    return session, payload, provider


async def test_codex_is_safe_telegram_option_and_route_when_worker_reports_available():
    session, payload, provider = codex_route_configuration()

    options = await automation_options(session, AVAILABLE_CAPABILITIES)
    route = await create_route(payload, session)

    assert route.ai_provider_profile_id == provider.id
    assert options.ai_provider_profiles == [
        {
            "id": provider.id,
            "name": "Codex CLI",
            "provider_type": "codex",
            "default_model": "gpt-5.4",
            "configured": True,
            "capabilities": {"generation": True, "research": True},
            "capability_states": {
                "generation": await AVAILABLE_CAPABILITIES.get("provider", provider.id, "generation"),
                "research": await AVAILABLE_CAPABILITIES.get("provider", provider.id, "research"),
            },
        }
    ]
    assert "/private/bin" not in str(options)


def operator_route_configuration():
    """Route fixtures whose provider is an operator-managed llm_providers row.

    Mirrors production: the Settings UI writes ``llm_providers`` and the service
    projects a same-ID ``AIProviderProfile`` shadow with ``secret_ref=None``.
    """

    session, payload, provider = codex_route_configuration()
    provider.provider_type = "openrouter"
    provider.default_model = "openai/gpt-5-mini"
    provider.settings = {
        "pricing": {"input_usd_per_million": "0", "output_usd_per_million": "0"},
        "generation_policy": {"qualification_status": "qualified"},
    }
    generic = LLMProvider(
        id=provider.id,
        name=provider.name,
        protocol="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        default_model=provider.default_model,
        enabled=True,
        secret_id=uuid4(),
        settings={},
        health_status="healthy",
        generation_capability="ready",
        research_capability="ready",
        last_successful_test_at=datetime.now(UTC),
    )
    session.values.append(generic)
    return session, payload, provider, generic


async def test_operator_provider_is_listed_and_usable_for_routes():
    session, payload, provider, generic = operator_route_configuration()

    options = await automation_options(session, AVAILABLE_CAPABILITIES)
    route = await create_route(payload, session)

    assert route.ai_provider_profile_id == provider.id
    assert options.ai_provider_profiles == [
        {
            "id": provider.id,
            "name": "Codex CLI",
            "provider_type": "openrouter",
            "default_model": "openai/gpt-5-mini",
            "configured": True,
            "capabilities": {"generation": True, "research": True},
            "capability_states": {
                "generation": await AVAILABLE_CAPABILITIES.get("provider", provider.id, "generation"),
                "research": await AVAILABLE_CAPABILITIES.get("provider", provider.id, "research"),
            },
        }
    ]
    assert "secret_id" not in str(options)


async def test_operator_provider_without_shadow_or_failing_test_stays_hidden():
    session, payload, provider, generic = operator_route_configuration()
    session.values.remove(generic)

    orphaned = await automation_options(session, AVAILABLE_CAPABILITIES)
    assert orphaned.ai_provider_profiles == []
    with pytest.raises(HTTPException, match="configuration is invalid") as error:
        await create_route(payload, session)
    assert error.value.status_code == 422

    session.values.append(generic)
    generic.enabled = False
    stale = await automation_options(session, AVAILABLE_CAPABILITIES)
    assert stale.ai_provider_profiles == []
    with pytest.raises(HTTPException, match="configuration is invalid"):
        await create_route(payload, session)


@pytest.mark.parametrize(
    "mutation",
    [
        {"enabled": False},
        {"settings": {"unexpected": True}},
        {"secret_ref": "OPENAI_API_KEY"},
    ],
)
async def test_telegram_route_rejects_invalid_codex_shape(mutation):
    session, payload, provider = codex_route_configuration()
    for key, value in mutation.items():
        setattr(provider, key, value)

    options = await automation_options(session, AVAILABLE_CAPABILITIES)
    assert options.ai_provider_profiles == []
    with pytest.raises(HTTPException, match="configuration is invalid") as error:
        await create_route(payload, session)
    assert error.value.status_code == 422


async def test_valid_codex_configuration_remains_editable_when_worker_is_unavailable():
    session, payload, provider = codex_route_configuration()
    unavailable = StaticCapabilityStatusService("unavailable")

    options = await automation_options(session, unavailable)
    route = await create_route(payload, session)

    assert route.ai_provider_profile_id == provider.id
    assert options.ai_provider_profiles[0]["configured"] is False
    assert options.ai_provider_profiles[0]["capability_states"]["generation"].status == "unavailable"


@pytest.mark.parametrize(
    "provider_type,mutation,configured_secrets",
    [
        ("fake", {"secret_ref": "OPENROUTER_API_KEY"}, {"OPENROUTER_API_KEY"}),
        ("fake", {"settings": {"unexpected": True}}, set()),
        ("openrouter", {"default_model": None}, {"OPENROUTER_API_KEY"}),
        ("openrouter", {"settings": {"unexpected": True}}, {"OPENROUTER_API_KEY"}),
        ("openrouter", {"secret_ref": None}, set()),
    ],
)
async def test_telegram_rejects_drifted_fake_and_openrouter_profiles(provider_type, mutation, configured_secrets):
    session, payload, provider = codex_route_configuration()
    provider.provider_type = provider_type
    provider.default_model = "fake-v1" if provider_type == "fake" else "model-a"
    provider.secret_ref = None if provider_type == "fake" else "OPENROUTER_API_KEY"
    provider.settings = {}
    for key, value in mutation.items():
        setattr(provider, key, value)
    assert isinstance(configured_secrets, set)

    options = await automation_options(session, AVAILABLE_CAPABILITIES)
    assert options.ai_provider_profiles == []
    with pytest.raises(HTTPException, match="configuration is invalid") as error:
        await create_route(payload, session)
    assert error.value.status_code == 422


async def test_auto_route_uses_route_level_confirmation_without_destination_permission():
    source = Source(id=uuid4(), platform="telegram_public", name="Source", source_group="telegram")
    config = TelegramSourceConfig(source_id=source.id, access_mode="public_html", channel_ref="source_channel")
    destination = Destination(
        id=uuid4(),
        name="Destination",
        platform="telegram",
        target_ref="@destination",
        secret_ref="DESTINATION_TOKEN",
        enabled=True,
        health_status="healthy",
        administrator_status="administrator",
        settings={},
    )
    brand = BrandProfile(id=uuid4(), name="Brand", output_language="fa", tone="neutral")
    prompt = PromptTemplate(id=uuid4(), purpose_key="telegram_rewrite", name="Rewrite")
    version = PromptTemplateVersion(
        id=uuid4(),
        prompt_template_id=prompt.id,
        version=1,
        system_template="system",
        user_template="user",
        output_schema_version="telegram_rewrite.v1",
        checksum_sha256="a" * 64,
        is_active=True,
    )
    provider = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        settings={},
        enabled=True,
    )
    session = ConfigurationSession([source, config, destination, brand, prompt, version, provider])
    payload = {
        **valid_route_payload(),
        "source_id": source.id,
        "destination_id": destination.id,
        "brand_profile_id": brand.id,
        "prompt_template_version_id": version.id,
        "ai_provider_profile_id": provider.id,
        "publishing_policy": "auto_publish",
        "confirm_auto_publish": True,
    }

    route = await create_route(TelegramRouteCreate.model_validate(payload), session)
    assert route.publishing_policy == "auto_publish"


def saved_route() -> AutomationRoute:
    now = datetime.now(UTC)
    return AutomationRoute(
        id=uuid4(),
        name="Route",
        source_id=uuid4(),
        destination_id=uuid4(),
        brand_profile_id=uuid4(),
        prompt_template_version_id=uuid4(),
        prompt_policy="pinned",
        ai_provider_profile_id=uuid4(),
        access_mode="public_html",
        research_mode="off",
        content_filters={},
        media_policy="preserve",
        attribution_policy="preserve",
        custom_footer=None,
        publishing_policy="review_required",
        poll_interval_seconds=300,
        quiet_hours={},
        retry_policy={},
        cursor_state={"status": "not_initialized", "recent_fingerprints": {"10": "hash"}},
        enabled=False,
        paused_at=None,
        backfill_limit=None,
        backfill_since=None,
        created_at=now,
        updated_at=now,
    )


class RouteSession:
    def __init__(self, route):
        self.route = route
        self.route_lock_count = 0
        self.calls = []

    async def get(self, model, identifier):
        return self.route if model is AutomationRoute and self.route.id == identifier else None

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is AutomationRoute:
            if statement._for_update_arg is not None:
                self.route_lock_count += 1
            return self.route
        return None

    async def flush(self):
        self.calls.append("flush")
        return None

    async def refresh(self, instance, *, attribute_names):
        assert instance is self.route
        self.calls.append(("refresh", tuple(attribute_names)))

    async def commit(self):
        self.calls.append("commit")
        return None


class InvalidatingCommitSession(RouteSession):
    async def commit(self):
        await super().commit()
        self.route.name = "invalidated after commit"
        self.route.updated_at = None


class FailingCommitSession(RouteSession):
    async def commit(self):
        self.calls.append("commit")
        raise RuntimeError("commit failed")


class FakeJobs:
    def __init__(self):
        self.enqueued = []
        self.by_key = {}

    async def enqueue_job(self, **kwargs):
        self.enqueued.append(kwargs)
        existing = self.by_key.get(kwargs["idempotency_key"])
        if existing is not None:
            return EnqueueJobResult(job=existing, created=False)
        job = SimpleNamespace(id=uuid4(), status=JobStatus.QUEUED)
        self.by_key[kwargs["idempotency_key"]] = job
        return EnqueueJobResult(
            job=job,
            created=True,
        )


class ConfigurationSession:
    def __init__(self, values):
        self.values = list(values)
        self.source_lock_count = 0

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        self.values.append(value)

    async def flush(self):
        return None

    async def refresh(self, instance, *, attribute_names):
        now = datetime.now(UTC)
        if getattr(instance, "created_at", None) is None:
            instance.created_at = now
        if getattr(instance, "updated_at", None) is None:
            instance.updated_at = now

    async def commit(self):
        return None

    async def get(self, model, identifier):
        return next(
            (
                value
                for value in self.values
                if isinstance(value, model)
                and (getattr(value, "id", None) == identifier or getattr(value, "source_id", None) == identifier)
            ),
            None,
        )

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is Source and statement._for_update_arg is not None:
            self.source_lock_count += 1
        return next((value for value in self.values if isinstance(value, entity)), None)

    async def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return [value for value in self.values if isinstance(value, entity)]
