from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.telegram_automations import (
    activate_route,
    automation_options,
    backfill_route,
    create_route,
    dry_run_route,
    pause_route,
    resume_route,
)
from app.api.telegram_schemas import TelegramRouteBackfillIn, TelegramRouteCreate, TelegramRouteOut
from app.automations.models import AutomationRoute, TelegramSourceConfig
from app.db.models import Source
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplate, PromptTemplateVersion
from app.jobs.repository import EnqueueJobResult
from app.jobs.types import JobStatus
from app.publishing.models import Destination


def valid_route_payload() -> dict:
    return {
        "name": "Rewrite source to newsroom",
        "source_id": uuid4(),
        "destination_id": uuid4(),
        "brand_profile_id": uuid4(),
        "prompt_template_version_id": uuid4(),
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
        TelegramRouteCreate.model_validate(
            {**valid_route_payload(), "content_filters": {"unknown": True}}
        )
    with pytest.raises(ValidationError):
        TelegramRouteCreate.model_validate({**valid_route_payload(), "research_mode": "deep"})


async def test_activation_enqueues_initialization_without_backfill_or_network():
    route = saved_route()
    session = RouteSession(route)
    jobs = FakeJobs()

    result = await activate_route(route.id, session, jobs)

    assert result.route.enabled is True
    assert route.cursor_state["status"] == "initializing"
    assert route.cursor_state["activation_message_id"] is None
    assert route.cursor_state["last_message_id"] is None
    assert route.backfill_limit is None
    assert route.backfill_since is None
    assert jobs.enqueued[0]["job_type"] == "telegram.route.initialize"


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

    first = await activate_route(route.id, session, jobs)
    second = await activate_route(route.id, session, jobs)

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
    )
    dry_run = await dry_run_route(
        route.id,
        SimpleNamespace(source_message_id=912),
        session,
        jobs,
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
    resumed = await resume_route(route.id, session)

    assert resumed.paused_at is None
    assert route.cursor_state == original_cursor
    assert route.enabled is False


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
        settings={"allow_auto_publish": False},
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
        settings={},
        enabled=True,
    )
    orphan = Source(
        id=uuid4(),
        platform="telegram_public",
        name="Orphan without transport config",
        source_group="telegram",
    )
    session = ConfigurationSession(
        [source, source_config, orphan, destination, brand, prompt, version, provider]
    )
    secrets = SimpleNamespace(configured=lambda reference: reference == "OPENROUTER_EDITOR_KEY")
    payload = {
        **valid_route_payload(),
        "source_id": source.id,
        "destination_id": destination.id,
        "brand_profile_id": brand.id,
        "prompt_template_version_id": version.id,
        "ai_provider_profile_id": provider.id,
    }

    route = await create_route(TelegramRouteCreate.model_validate(payload), session, secrets)
    replayed = await create_route(TelegramRouteCreate.model_validate(payload), session, secrets)
    options = await automation_options(session, secrets)

    assert replayed is route
    assert route.cursor_state == {"status": "not_initialized"}
    assert route.enabled is False
    assert options.sources == [{"id": source.id, "name": "Source", "access_mode": "public_html"}]
    assert options.ai_provider_profiles[0]["configured"] is True
    assert "secret_ref" not in str(options)
    assert "OPENROUTER_EDITOR_KEY" not in str(options)
    assert "TELEGRAM_DESTINATION_TOKEN" not in str(options)
    assert session.source_lock_count == 2

    with pytest.raises(HTTPException) as conflict:
        await create_route(
            TelegramRouteCreate.model_validate({**payload, "media_policy": "omit"}),
            session,
            secrets,
        )
    assert conflict.value.status_code == 409
    assert session.source_lock_count == 3


async def test_auto_route_is_rejected_when_destination_disallows_auto_publish():
    source = Source(id=uuid4(), platform="telegram_public", name="Source", source_group="telegram")
    config = TelegramSourceConfig(
        source_id=source.id, access_mode="public_html", channel_ref="source_channel"
    )
    destination = Destination(
        id=uuid4(),
        name="Destination",
        platform="telegram",
        target_ref="@destination",
        secret_ref="DESTINATION_TOKEN",
        enabled=True,
        health_status="healthy",
        settings={"allow_auto_publish": False},
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

    with pytest.raises(Exception, match="does not allow auto publishing"):
        await create_route(
            TelegramRouteCreate.model_validate(payload),
            session,
            SimpleNamespace(configured=lambda reference: False),
        )


def saved_route() -> AutomationRoute:
    now = datetime.now(UTC)
    return AutomationRoute(
        id=uuid4(),
        name="Route",
        source_id=uuid4(),
        destination_id=uuid4(),
        brand_profile_id=uuid4(),
        prompt_template_version_id=uuid4(),
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
        return None

    async def commit(self):
        return None


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
