from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.capabilities import get_capability_status_service
from app.automations.models import AutomationRoute, TelegramSourceConfig
from app.db.models import Source
from app.db.session import get_session
from app.generation.default_prompts import (
    seed_default_telegram_configuration,
    seed_default_telegram_prompt,
)
from app.jobs.models import WorkflowJob
from app.main import app
from app.publishing.models import Destination
from tests.capability_fakes import AVAILABLE_CAPABILITIES


@dataclass(frozen=True, slots=True)
class RouteConfiguration:
    source_id: UUID
    destination_id: UUID
    brand_profile_id: UUID
    prompt_template_version_id: UUID
    provider_profile_id: UUID


async def test_all_route_mutations_materialize_committed_responses(
    session_factory: async_sessionmaker[AsyncSession],
):
    configuration = await _seed_route_configuration(session_factory)

    async with _api_client(session_factory) as client:
        created = await client.post(
            "/telegram/automations",
            json=_route_payload(configuration),
        )
        assert created.status_code == 201, created.text
        route_id = created.json()["id"]

        policy = await client.patch(
            f"/telegram/automations/{route_id}/research-policy",
            json={
                "research_mode": "manual",
                "research_provider_profile_id": str(configuration.provider_profile_id),
            },
        )
        activated = await client.post(f"/telegram/automations/{route_id}/activate")
        paused = await client.post(f"/telegram/automations/{route_id}/pause")
        resumed = await client.post(f"/telegram/automations/{route_id}/resume")
        dry_run = await client.post(
            f"/telegram/automations/{route_id}/dry-run",
            json={"source_message_id": 123},
        )
        backfill = await client.post(
            f"/telegram/automations/{route_id}/backfill",
            json={"count": 5},
        )

        responses = (created, policy, activated, paused, resumed, dry_run, backfill)
        assert [response.status_code for response in responses] == [201, 200, 202, 200, 200, 202, 202]
        for response in responses:
            body = response.json()
            route = body.get("route", body)
            assert route["id"] == route_id
            assert route["updated_at"]
            assert "secret_ref" not in response.text
            assert "PHASE_ONE_DESTINATION_CANARY" not in response.text

        replayed_activation = await client.post(f"/telegram/automations/{route_id}/activate")
        replayed_backfill = await client.post(
            f"/telegram/automations/{route_id}/backfill",
            json={"count": 5},
        )

    assert replayed_activation.status_code == 202, replayed_activation.text
    assert replayed_backfill.status_code == 202, replayed_backfill.text
    assert replayed_activation.json()["job"]["job_id"] == activated.json()["job"]["job_id"]
    assert replayed_backfill.json()["job"]["job_id"] == backfill.json()["job"]["job_id"]
    assert replayed_activation.json()["job"]["deduplicated"] is True
    assert replayed_backfill.json()["job"]["deduplicated"] is True

    async with session_factory() as session:
        route = await session.get(AutomationRoute, UUID(route_id))
        assert route is not None
        assert route.enabled is True
        assert route.paused_at is None
        assert route.research_mode == "manual"
        assert route.content_filters["research_provider_profile_id"] == str(configuration.provider_profile_id)
        assert await session.scalar(select(func.count()).select_from(WorkflowJob)) == 3


async def test_concurrent_activation_returns_one_consistent_route_job_pair(
    session_factory: async_sessionmaker[AsyncSession],
):
    configuration = await _seed_route_configuration(session_factory)

    async with _api_client(session_factory) as client:
        created = await client.post(
            "/telegram/automations",
            json=_route_payload(configuration),
        )
        assert created.status_code == 201, created.text
        route_id = created.json()["id"]

        first, second = await asyncio.gather(
            client.post(f"/telegram/automations/{route_id}/activate"),
            client.post(f"/telegram/automations/{route_id}/activate"),
        )

    assert first.status_code == second.status_code == 202
    first_body = first.json()
    second_body = second.json()
    assert first_body["job"]["job_id"] == second_body["job"]["job_id"]
    assert {first_body["job"]["deduplicated"], second_body["job"]["deduplicated"]} == {
        False,
        True,
    }
    assert (
        first_body["route"]["cursor_state"]["activation_requested_at"]
        == second_body["route"]["cursor_state"]["activation_requested_at"]
    )

    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(WorkflowJob).where(WorkflowJob.job_type == "telegram.route.initialize")
            )
            == 1
        )


async def _seed_route_configuration(
    session_factory: async_sessionmaker[AsyncSession],
) -> RouteConfiguration:
    async with session_factory() as session:
        defaults = await seed_default_telegram_configuration(
            session,
            openrouter_available=False,
        )
        prompt_version = await seed_default_telegram_prompt(session)
        source = Source(
            id=uuid4(),
            platform="telegram_public",
            name="Phase one source",
            telegram_username="phase_one_source",
            source_group="telegram",
            language_hint="fa",
        )
        session.add(source)
        await session.flush()
        source_config = TelegramSourceConfig(
            source_id=source.id,
            access_mode="public_html",
            channel_ref="phase_one_source",
        )
        destination = Destination(
            id=uuid4(),
            name="Phase one destination",
            platform="telegram",
            target_ref="@phase_one_destination",
            secret_ref="PHASE_ONE_DESTINATION_CANARY",
            enabled=True,
            health_status="healthy",
            administrator_status="administrator",
            settings={},
        )
        session.add_all((source_config, destination))
        await session.commit()
        return RouteConfiguration(
            source_id=source.id,
            destination_id=destination.id,
            brand_profile_id=defaults.brand.id,
            prompt_template_version_id=prompt_version.id,
            provider_profile_id=defaults.provider("fake").id,
        )


def _route_payload(configuration: RouteConfiguration) -> dict[str, str | dict[str, str]]:
    return {
        "name": "Phase one route",
        "source_id": str(configuration.source_id),
        "destination_id": str(configuration.destination_id),
        "brand_profile_id": str(configuration.brand_profile_id),
        "prompt_template_version_id": str(configuration.prompt_template_version_id),
        "prompt_policy": "pinned",
        "ai_provider_profile_id": str(configuration.provider_profile_id),
        "access_mode": "public_html",
        "content_filters": {"model": "fake-v1"},
    }


@asynccontextmanager
async def _api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_capability_status_service] = lambda: AVAILABLE_CAPABILITIES
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
