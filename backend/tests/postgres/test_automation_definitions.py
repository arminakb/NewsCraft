from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.automations.definitions.models import Automation, AutomationTemplate, AutomationVersion
from app.automations.definitions.resources import count_automation_definitions_referencing
from app.automations.definitions.templates import seed_automation_templates
from app.db.session import get_session
from app.generation.models import AIProviderProfile
from app.jobs.models import RuntimeHeartbeat, WorkflowEvent
from app.llm_providers.models import LLMProvider
from app.llm_providers.schemas import LLMProviderSettings
from app.main import app
from app.security.models import EncryptedSecret


def _available_provider_heartbeat(provider_id: UUID) -> RuntimeHeartbeat:
    """Worker observation marking the provider's generation/research available."""

    observations = [
        {
            "resource_type": "provider",
            "resource_id": str(provider_id),
            "capability": capability,
            "state": "available",
            "failure_code": "available",
        }
        for capability in ("generation", "research")
    ]
    return RuntimeHeartbeat(
        component_id="worker-test-generation",
        component_type="worker",
        capabilities=["generation", "source"],
        observed_at=datetime.now(UTC),
        runtime_metadata={"external_capabilities": observations},
    )


def _graph(
    story_revision_id: UUID | None = None,
    *,
    provider_profile_id: UUID | None = None,
) -> dict[str, object]:
    prompt_id = uuid4()
    return {
        "schema_version": 1,
        "entry_node_id": "trigger-1",
        "nodes": [
            {
                "id": "trigger-1",
                "type": "manual",
                "config": {"story_revision_id": str(story_revision_id or uuid4())},
            },
            {
                "id": "generate-1",
                "type": "generate_content_pack",
                "config": {
                    "editorial_profile_id": str(uuid4()),
                    "provider_profile_id": str(provider_profile_id or uuid4()),
                    "prompt_version_ids": [str(prompt_id)],
                    "prompt_checksums": {str(prompt_id): "a" * 64},
                    "platforms": ["telegram"],
                },
            },
            {"id": "draft-1", "type": "save_drafts", "config": {}},
        ],
        "edges": [
            {
                "source_node_id": "trigger-1",
                "source_port": "story",
                "target_node_id": "generate-1",
                "target_port": "story",
            },
            {
                "source_node_id": "generate-1",
                "source_port": "drafts",
                "target_node_id": "draft-1",
                "target_port": "drafts",
            },
        ],
        "output_node_ids": ["draft-1"],
        "metadata": {"layout": {}},
    }


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


async def test_create_version_restore_conflict_archive_and_events_are_durable(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with _client(session_factory) as client:
        created = await client.post(
            "/automations",
            headers={"Idempotency-Key": "create-workflow-1"},
            json={"name": "Morning desk", "description": "Review first", "graph": _graph()},
        )
        assert created.status_code == 201, created.text
        automation_id = created.json()["id"]
        assert created.json()["revision"] == 1
        assert created.json()["lifecycle"] == "inactive"
        assert created.json()["draft_version"]["version"] == 1

        listed = await client.get("/automations")
        assert listed.status_code == 200, listed.text
        preview = listed.json()["items"][0]["preview"]
        assert preview["version"] == 1
        assert preview["version_state"] == "draft"
        assert [stage["node_type"] for stage in preview["stages"]] == [
            "manual",
            "generate_content_pack",
            "save_drafts",
        ]
        assert preview["output_platforms"] == ["draft"]
        assert preview["run_count"] == 0
        assert "config" not in listed.text
        assert "prompt_checksums" not in listed.text

        replay = await client.post(
            "/automations",
            headers={"Idempotency-Key": "create-workflow-1"},
            json={
                "name": "Morning desk",
                "description": "Review first",
                "graph": created.json()["draft_version"]["graph"],
            },
        )
        assert replay.status_code == 200 or replay.status_code == 201
        assert replay.json()["id"] == automation_id

        unsupported_graph = _graph()
        unsupported_graph["nodes"][1]["type"] = "http_request"  # type: ignore[index]
        unsupported = await client.post(
            "/automations",
            headers={"Idempotency-Key": "unsupported-workflow-1"},
            json={"name": "Unsafe draft", "graph": unsupported_graph},
        )
        assert unsupported.status_code == 422
        assert unsupported.json()["detail"]["code"] == "node_type_unsupported"

        invalid_config_graph = _graph()
        invalid_config_graph["nodes"][1]["config"]["platforms"] = []  # type: ignore[index]
        invalid_config = await client.post(
            f"/automations/{automation_id}/versions",
            headers={"Idempotency-Key": "invalid-config-workflow-2"},
            json={"expected_revision": 1, "graph": invalid_config_graph, "creation_reason": "invalid config probe"},
        )
        assert invalid_config.status_code == 422
        assert invalid_config.json()["detail"] == {
            "code": "node_config_invalid",
            "message": "Generate content package: configuration.platforms must contain at least 1 item.",
            "node_id": "generate-1",
            "node_type": "generate_content_pack",
            "field_path": "config.platforms",
        }

        saved = await client.post(
            f"/automations/{automation_id}/versions",
            headers={"Idempotency-Key": "save-workflow-2"},
            json={"expected_revision": 1, "graph": _graph(), "creation_reason": "add next draft"},
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["version"] == 2

        reloaded = await client.get(f"/automations/{automation_id}")
        assert reloaded.status_code == 200, reloaded.text
        assert reloaded.json()["draft_version"]["version"] == 2
        assert reloaded.json()["draft_version"]["graph"] == saved.json()["graph"]

        stale = await client.patch(
            f"/automations/{automation_id}",
            json={"expected_revision": 1, "name": "Stale overwrite"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "automation_version_conflict"

        restored = await client.post(
            f"/automations/{automation_id}/versions/1/restore-as-draft",
            headers={"Idempotency-Key": "restore-workflow-1"},
            json={"expected_revision": 2, "creation_reason": "restore known graph"},
        )
        assert restored.status_code == 201, restored.text
        assert restored.json()["version"] == 3
        assert restored.json()["graph_hash"] == created.json()["draft_version"]["graph_hash"]

        versions = await client.get(f"/automations/{automation_id}/versions?limit=2")
        assert versions.status_code == 200
        assert [item["version"] for item in versions.json()["items"]] == [3, 2]
        assert versions.json()["next_cursor"] == "2"

        archived = await client.post(
            f"/automations/{automation_id}/archive",
            json={"expected_revision": 3},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["lifecycle"] == "archived"
        assert archived.json()["archived_at"] is not None

    async with session_factory() as session:
        automation = await session.get(Automation, UUID(automation_id))
        assert automation is not None
        assert automation.lifecycle == "archived"
        assert await session.scalar(
            select(func.count()).select_from(AutomationVersion).where(AutomationVersion.automation_id == automation.id)
        ) == 3
        event_types = set(
            await session.scalars(
                select(WorkflowEvent.event_type).where(
                    WorkflowEvent.event_data["automation_id"].as_string() == automation_id
                )
            )
        )
        assert {"automation.created", "automation.version_created", "automation.archived"}.issubset(event_types)

        provider_id = UUID(created.json()["draft_version"]["graph"]["nodes"][1]["config"]["provider_profile_id"])
        assert await count_automation_definitions_referencing(session, provider_id) == 1


async def test_template_seeding_is_idempotent_and_copies_to_inactive_draft(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        first = await seed_automation_templates(session)
        await session.commit()
    async with session_factory() as session:
        second = await seed_automation_templates(session)
        await session.commit()
        count = await session.scalar(select(func.count()).select_from(AutomationTemplate))

    assert len(first) == 2
    assert second == []
    assert count == 2

    async with _client(session_factory) as client:
        templates = await client.get("/automation-templates")
        assert templates.status_code == 200
        assert {item["seed_key"] for item in templates.json()} == {
            "blank-workflow",
            "research-first-draft",
        }
        blank_template = next(item for item in templates.json() if item["seed_key"] == "blank-workflow")
        assert blank_template["graph_seed"]["nodes"] == []
        assert blank_template["graph_seed"]["edges"] == []
        assert blank_template["graph_seed"]["output_node_ids"] == []
        copied = await client.post(
            "/automation-templates/blank-workflow/create",
            headers={"Idempotency-Key": "template-copy-1"},
            json={"name": "Editable draft"},
        )

    assert copied.status_code == 201, copied.text
    assert copied.json()["name"] == "Editable draft"
    assert copied.json()["lifecycle"] == "inactive"
    assert copied.json()["active_version_id"] is None
    assert copied.json()["draft_version"] is not None
    assert copied.json()["draft_version"]["graph"]["nodes"] == []
    assert copied.json()["draft_version"]["graph"]["edges"] == []
    assert copied.json()["draft_version"]["graph"]["output_node_ids"] == []
    for forbidden in ("secret_ref", "authorization", "api_key", "bot_token"):
        assert forbidden not in copied.text


async def test_empty_workflow_stays_empty_in_list_and_saved_versions(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        await seed_automation_templates(session)
        await session.commit()

    async with _client(session_factory) as client:
        created = await client.post(
            "/automation-templates/blank-workflow/create",
            headers={"Idempotency-Key": "empty-workflow-create"},
            json={"name": "Empty workflow"},
        )
        assert created.status_code == 201, created.text
        automation_id = created.json()["id"]
        graph = created.json()["draft_version"]["graph"]
        assert graph["nodes"] == []
        assert graph["edges"] == []
        assert graph["entry_node_id"] == ""
        assert graph["output_node_ids"] == []

        listed = await client.get("/automations")
        assert listed.status_code == 200, listed.text
        preview = listed.json()["items"][0]["preview"]
        assert preview["stages"] == []

        saved = await client.post(
            f"/automations/{automation_id}/versions",
            headers={"Idempotency-Key": "empty-workflow-save"},
            json={"expected_revision": 1, "graph": graph},
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["graph"]["nodes"] == []
        assert saved.json()["graph"]["edges"] == []


async def test_direct_empty_workflow_creation_persists_empty_graph_and_blocks_activation(
    session_factory: async_sessionmaker[AsyncSession],
):
    empty_graph = {
        "schema_version": 1,
        "entry_node_id": "",
        "nodes": [],
        "edges": [],
        "output_node_ids": [],
        "metadata": {"layout": {}},
    }

    async with _client(session_factory) as client:
        created = await client.post(
            "/automations",
            headers={"Idempotency-Key": "direct-empty-workflow-create"},
            json={"name": "Direct empty workflow", "graph": empty_graph},
        )
        assert created.status_code == 201, created.text
        automation_id = created.json()["id"]
        assert created.json()["draft_version"]["graph"] == empty_graph

        activation = await client.post(
            f"/automations/{automation_id}/activate",
            headers={"Idempotency-Key": "direct-empty-workflow-activate"},
            json={"expected_revision": 1},
        )
        assert activation.status_code == 409
        assert activation.json()["detail"]["code"] == "automation_activation_invalid"


async def test_validation_keeps_unavailable_saved_resources_visible_and_blocks_activation(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with _client(session_factory) as client:
        created = await client.post(
            "/automations",
            headers={"Idempotency-Key": "missing-resource-workflow"},
            json={"name": "Broken but editable", "graph": _graph()},
        )
        assert created.status_code == 201, created.text
        automation_id = created.json()["id"]

        validation = await client.post(f"/automations/{automation_id}/versions/1/validate")
        assert validation.status_code == 200, validation.text
        assert validation.json()["valid"] is False
        assert "automation_resource_unavailable" in {item["code"] for item in validation.json()["findings"]}

        activated = await client.post(
            f"/automations/{automation_id}/activate",
            headers={"Idempotency-Key": "activate-missing-resource"},
            json={"expected_revision": 1},
        )
        assert activated.status_code == 409
        assert activated.json()["detail"]["code"] == "automation_activation_invalid"

        provider_id = created.json()["draft_version"]["graph"]["nodes"][1]["config"]["provider_profile_id"]
        catalog = await client.post(
            "/automation-resource-catalog",
            json={
                "automation_id": automation_id,
                "resources": [{"kind": "provider", "id": provider_id}],
            },
        )

        assert catalog.status_code == 200, catalog.text
        provider = next(item for item in catalog.json()["resources"] if item["id"] == provider_id)
        assert provider == {
            "id": provider_id,
            "kind": "provider",
            "display_name": "Unavailable provider",
            "state": "unavailable",
            "reason_code": "resource_missing",
            "capabilities": [],
            "referenced_by_active_version": False,
            "manage_href": "/settings?section=llm-providers",
        }


async def test_operator_backed_provider_resource_is_ready_for_workflows(
    session_factory: async_sessionmaker[AsyncSession],
):
    provider_id = uuid4()
    async with session_factory() as session:
        secret = EncryptedSecret(
            id=uuid4(),
            purpose="llm_provider_api_key",
            owner_type="llm_provider",
            owner_id=provider_id,
            ciphertext=b"0" * 32,
            nonce=b"0" * 12,
            key_version="v0",
        )
        session.add(secret)
        await session.flush()
        session.add(
            LLMProvider(
                id=provider_id,
                name="Operator OpenRouter",
                protocol="openai_compatible",
                base_url="https://openrouter.ai/api/v1",
                default_model="openai/gpt-5-mini",
                enabled=True,
                secret_id=secret.id,
                settings=LLMProviderSettings().model_dump(mode="json"),
                health_status="healthy",
                generation_capability="ready",
                research_capability="ready",
                last_successful_test_at=datetime.now(UTC),
            )
        )
        session.add(
            AIProviderProfile(
                id=provider_id,
                name="Operator OpenRouter",
                provider_type="openrouter",
                default_model="openai/gpt-5-mini",
                secret_ref=None,
                settings={
                    "pricing": {"input_usd_per_million": "0", "output_usd_per_million": "0"},
                    "generation_policy": {"qualification_status": "qualified"},
                },
                enabled=True,
            )
        )
        session.add(_available_provider_heartbeat(provider_id))
        await session.commit()

    async with _client(session_factory) as client:
        created = await client.post(
            "/automations",
            headers={"Idempotency-Key": "operator-provider-workflow"},
            json={"name": "Uses operator provider", "graph": _graph(provider_profile_id=provider_id)},
        )
        assert created.status_code == 201, created.text
        automation_id = created.json()["id"]

        validation = await client.post(f"/automations/{automation_id}/versions/1/validate")
        assert validation.status_code == 200, validation.text

        catalog = await client.post(
            "/automation-resource-catalog",
            json={
                "automation_id": automation_id,
                "resources": [{"kind": "provider", "id": str(provider_id)}],
            },
        )

    assert catalog.status_code == 200, catalog.text
    provider = next(item for item in catalog.json()["resources"] if item["id"] == str(provider_id))
    assert provider["display_name"] == "Operator OpenRouter"
    assert provider["state"] == "ready"
    assert provider["capabilities"] == ["generation", "research"]

    findings = validation.json()["findings"]
    provider_findings = [item for item in findings if "provider_profile_id" in (item.get("field_path") or "")]
    assert provider_findings == [], json.dumps(findings, default=str)
    assert validation.json()["valid"] is False  # story revision + prompts are still missing


async def test_prompt_reactivation_does_not_block_new_draft_activation(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Upgrading a prompt must not deadlock workflows pinned to the superseded version."""

    provider_id = uuid4()
    brand_id = uuid4()
    story_revision_id = uuid4()
    template_id = uuid4()
    v1_id, v2_id = uuid4(), uuid4()

    async with session_factory() as session:
        from app.generation.models import BrandProfile, PromptTemplate, PromptTemplateVersion
        from app.stories.models import Story, StoryRevision

        story_id = uuid4()
        session.add(
            Story(
                id=story_id,
                title="Prompt deadlock story",
                status="inbox",
                primary_language="en",
                superseded_by_id=None,
            )
        )
        session.add(
            BrandProfile(
                id=brand_id,
                name="Prompt Deadlock Newsroom",
                output_language="en",
                tone="neutral",
                editorial_rules=[],
                attribution_rules={},
                default_hashtags=[],
                platform_preferences={},
                is_default=True,
            )
        )
        session.add(
            StoryRevision(
                id=story_revision_id,
                story_id=story_id,
                revision_number=1,
                narrative="Current",
                facts=[],
                disagreements=[],
                angles=[],
                citations=[],
                created_by="test",
            )
        )
        secret = EncryptedSecret(
            id=uuid4(),
            purpose="llm_provider_api_key",
            owner_type="llm_provider",
            owner_id=provider_id,
            ciphertext=b"0" * 32,
            nonce=b"0" * 12,
            key_version="v0",
        )
        session.add(secret)
        await session.flush()
        session.add(
            LLMProvider(
                id=provider_id,
                name="Deadlock Probe Provider",
                protocol="openai_compatible",
                base_url="https://openrouter.ai/api/v1",
                default_model="openai/gpt-5-mini",
                enabled=True,
                secret_id=secret.id,
                settings=LLMProviderSettings().model_dump(mode="json"),
                health_status="healthy",
                generation_capability="ready",
                research_capability="ready",
                last_successful_test_at=datetime.now(UTC),
            )
        )
        session.add(
            AIProviderProfile(
                id=provider_id,
                name="Deadlock Probe Provider",
                provider_type="openrouter",
                default_model="openai/gpt-5-mini",
                secret_ref=None,
                settings={
                    "pricing": {"input_usd_per_million": "0", "output_usd_per_million": "0"},
                    "generation_policy": {"qualification_status": "qualified"},
                },
                enabled=True,
            )
        )
        session.add(_available_provider_heartbeat(provider_id))
        session.add(
            PromptTemplate(
                id=template_id,
                purpose_key=f"deadlock_probe_{template_id.hex[:8]}",
                name="Deadlock Probe Prompt",
            )
        )
        for version_id, number in ((v1_id, 1), (v2_id, 2)):
            session.add(
                PromptTemplateVersion(
                    id=version_id,
                    prompt_template_id=template_id,
                    version=number,
                    system_template="System",
                    user_template="User",
                    output_schema_version="1",
                    checksum_sha256=uuid4().hex + uuid4().hex[:32],
                    is_active=False,
                    activation_reason="test",
                )
            )
        await session.flush()
        v1 = await session.get(PromptTemplateVersion, v1_id)
        v1.is_active = True
        v1.activated_at = datetime.now(UTC)
        v1.activated_by_type = "operator"
        v1.activated_by_id = "test"
        await session.commit()

    def _graph_for(prompt_version_id: UUID, checksum: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "entry_node_id": "trigger-1",
            "nodes": [
                {
                    "id": "trigger-1",
                    "type": "manual",
                    "config": {"story_revision_id": str(story_revision_id)},
                },
                {
                    "id": "generate-1",
                    "type": "generate_content_pack",
                    "config": {
                        "editorial_profile_id": str(brand_id),
                        "provider_profile_id": str(provider_id),
                        "prompt_version_ids": [str(prompt_version_id)],
                        "prompt_checksums": {str(prompt_version_id): checksum},
                        "platforms": ["telegram"],
                    },
                },
                {"id": "draft-1", "type": "save_drafts", "config": {}},
            ],
            "edges": [
                {
                    "source_node_id": "trigger-1",
                    "source_port": "story",
                    "target_node_id": "generate-1",
                    "target_port": "story",
                },
                {
                    "source_node_id": "generate-1",
                    "source_port": "drafts",
                    "target_node_id": "draft-1",
                    "target_port": "drafts",
                },
            ],
            "output_node_ids": ["draft-1"],
        }

    async with _client(session_factory) as client:
        created = await client.post(
            "/automations",
            headers={"Idempotency-Key": "prompt-deadlock-create"},
            json={"name": "Prompt upgrade survivor", "graph": _graph_for(v1_id, "a" * 64)},
        )
        assert created.status_code == 201, created.text
        automation_id = created.json()["id"]

        # Point the draft at the real V1 checksum so the first activation passes.
        versions = (await client.get(f"/prompt-templates/{template_id}/versions")).json()
        items = versions if isinstance(versions, list) else versions["items"]
        stored_v1 = next(item for item in items if item["id"] == str(v1_id))
        current_revision = (await client.get(f"/automations/{automation_id}")).json()["revision"]
        saved = await client.post(
            f"/automations/{automation_id}/versions",
            headers={"Idempotency-Key": "prompt-deadlock-fix-v1"},
            json={
                "expected_revision": current_revision,
                "creation_reason": "pin real checksum",
                "graph": _graph_for(v1_id, stored_v1["checksum_sha256"]),
            },
        )
        assert saved.status_code == 201, saved.text
        revision = (await client.get(f"/automations/{automation_id}")).json()["revision"]
        activated = await client.post(
            f"/automations/{automation_id}/activate",
            headers={"Idempotency-Key": "prompt-deadlock-activate-v1"},
            json={"expected_revision": revision},
        )
        assert activated.status_code == 200, activated.text

        # Activate prompt V2: this deactivates V1, which the ACTIVE automation
        # version still references.
        activate_v2 = await client.post(
            f"/prompt-template-versions/{v2_id}/activate",
            json={"reason": "upgrade prompt to second version"},
        )
        assert activate_v2.status_code == 200, activate_v2.text

        versions = (await client.get(f"/prompt-templates/{template_id}/versions")).json()
        items = versions if isinstance(versions, list) else versions["items"]
        stored_v2 = next(item for item in items if item["id"] == str(v2_id))
        current_revision = (await client.get(f"/automations/{automation_id}")).json()["revision"]
        repinned = await client.post(
            f"/automations/{automation_id}/versions",
            headers={"Idempotency-Key": "prompt-deadlock-pin-v2"},
            json={
                "expected_revision": current_revision,
                "creation_reason": "repin to upgraded prompt",
                "graph": _graph_for(v2_id, stored_v2["checksum_sha256"]),
            },
        )
        assert repinned.status_code == 201, repinned.text

        validation = await client.post(f"/automations/{automation_id}/versions/3/validate")
        assert validation.status_code == 200, validation.text
        blocking = [
            item
            for item in validation.json()["findings"]
            if item["code"] == "automation_resource_unavailable"
        ]
        assert blocking == [], json.dumps(validation.json()["findings"], default=str)
        assert validation.json()["valid"] is True

        reactivated = await client.post(
            f"/automations/{automation_id}/activate",
            headers={"Idempotency-Key": "prompt-deadlock-activate-v2"},
            json={"expected_revision": (await client.get(f"/automations/{automation_id}")).json()["revision"]},
        )
        assert reactivated.status_code == 200, reactivated.text
