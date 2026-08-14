from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.content_packs import (
    _request_out,
    _research_request_out,
    _revision_out,
    list_content_pack_requests,
)
from app.api.content_packs import (
    edit_variant as edit_variant_route,
)
from app.api.content_packs import (
    router as content_pack_router,
)
from app.db.session import get_session
from app.generation.editorial_service import (
    EditVariantRequest,
    GeneratePackRequest,
    InvalidGenerationRequest,
    RegenerateVariantRequest,
    RevisionConflict,
)
from app.generation.platform_schemas import ManualPlatformEditRequest
from app.generation.telegram_schema import TelegramRewriteOutput
from app.main import app


def test_content_pack_resource_routes_are_registered_with_exact_methods():
    routes = {(path, method.upper()) for path, operation in app.openapi()["paths"].items() for method in operation}
    expected = {
        ("/stories/{story_id}", "GET"),
        ("/stories/{story_id}/evidence", "GET"),
        ("/stories/{story_id}/revisions", "GET"),
        ("/stories/{story_id}/content-packs", "POST"),
        ("/content-packs", "GET"),
        ("/content-pack-requests", "GET"),
        ("/content-packs/{pack_id}", "GET"),
        ("/platform-variants/{variant_id}/revisions", "GET"),
        ("/platform-variants/{variant_id}/revisions", "POST"),
        ("/platform-variant-revisions/{revision_id}", "GET"),
        ("/platform-variant-revisions/{revision_id}/rendered-html", "GET"),
        ("/platform-variants/{variant_id}/regenerate", "POST"),
        ("/platform-variant-revisions/{revision_id}/approve", "POST"),
        ("/platform-variant-revisions/{revision_id}/reject", "POST"),
    }
    assert expected <= routes
    edit_operation = app.openapi()["paths"]["/platform-variants/{variant_id}/revisions"]["post"]
    assert "201" in edit_operation["responses"]


@pytest.mark.asyncio
async def test_content_pack_list_enforces_response_model_at_the_real_listener(monkeypatch):
    import app.api.content_packs as content_pack_api

    class Session:
        async def scalars(self, _statement):
            return []

    async def uncontracted_projection(_session, _rows):
        return [{"unexpected": True}]

    monkeypatch.setattr(content_pack_api, "_packs_out", uncontracted_projection)
    api = FastAPI()
    api.include_router(content_pack_router)

    async def override_session():
        yield Session()

    api.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=api, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/content-packs")

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_content_pack_request_list_bulk_loads_unassociated_pack_summaries():
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    story_id = uuid4()
    story_revision = SimpleNamespace(id=uuid4(), story_id=story_id)
    pack = SimpleNamespace(
        id=uuid4(),
        story_revision_id=story_revision.id,
        brand_profile_id=uuid4(),
        status="draft",
        created_at=now,
        updated_at=now,
    )
    variant = SimpleNamespace(id=uuid4(), content_pack_id=pack.id, platform="telegram")
    job = SimpleNamespace(
        id=uuid4(),
        job_type="content_pack.generate",
        status="queued",
        payload={"story_id": str(story_id), "brand_profile_id": str(pack.brand_profile_id), "platforms": ["telegram"]},
        result={},
        error_message=None,
        created_at=now,
        updated_at=now,
    )

    class BulkSession:
        def __init__(self):
            self.results = iter(([job], [pack], [story_revision], [variant]))
            self.query_count = 0

        async def scalars(self, _statement):
            self.query_count += 1
            return next(self.results)

    session = BulkSession()
    rows = await list_content_pack_requests(session)

    assert session.query_count == 4
    assert rows[-1]["story_id"] == story_id
    assert rows[-1]["pack"]["variants"] == [{"id": variant.id, "platform": "telegram"}]


def test_blog_rendered_html_is_read_only_sanitized_and_bound_to_revision_identity():
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.models import PlatformVariant, PlatformVariantRevision

    revision_id = uuid4()
    variant_id = uuid4()
    citation = {
        "evidence_key": "evidence:one",
        "evidence_snapshot_id": str(uuid4()),
        "source_url": "https://example.com/report",
        "locator": "chars:0-8",
        "excerpt_sha256": "a" * 64,
    }
    body = (
        "# Grounded report\n\n[Source](https://example.com/report)\n\n<script>alert(1)</script>\n\n" + "grounded " * 30
    )
    content = {
        "title": "Grounded report",
        "slug": "grounded-report",
        "excerpt": "A grounded report excerpt.",
        "body_markdown": body,
        "headings": ["Grounded report"],
        "citations": [citation],
        "tags": ["news"],
        "seo_description": "A grounded description for a deterministic NewsCraft export package.",
        "hero_media": None,
        "canonical_sources": ["https://example.com/report"],
        "manual_checklist": ["Verify source links"],
    }
    evidence_map = []
    content_hash = sha256_canonical({"content": content, "evidence_map": evidence_map})
    revision = SimpleNamespace(
        id=revision_id,
        platform_variant_id=variant_id,
        content_hash=content_hash,
        content=content,
        evidence_map=evidence_map,
    )
    variant = SimpleNamespace(id=variant_id, platform="blog")

    class Session:
        def __init__(self):
            self.reads = []

        async def get(self, model, identifier):
            self.reads.append((model, identifier))
            return {
                (PlatformVariantRevision, revision_id): revision,
                (PlatformVariant, variant_id): variant,
            }.get((model, identifier))

    session = Session()
    test_app = FastAPI()
    test_app.include_router(content_pack_router)

    async def override_session():
        yield session

    test_app.dependency_overrides[get_session] = override_session
    with TestClient(test_app) as client:
        response = client.get(f"/platform-variant-revisions/{revision_id}/rendered-html")

    assert response.status_code == 200
    assert response.json() == {
        "revision_id": str(revision_id),
        "content_hash": content_hash,
        "platform": "blog",
        "html": response.json()["html"],
    }
    html = response.json()["html"]
    assert "<h1>Grounded report</h1>" in html
    assert 'href="https://example.com/report"' in html
    assert "<script" not in html
    assert session.reads == [
        (PlatformVariantRevision, revision_id),
        (PlatformVariant, variant_id),
    ]


def test_content_pack_request_uses_plural_platforms_and_safe_prompt_resolution():
    assert "platforms" in GeneratePackRequest.model_fields
    assert "platform" not in GeneratePackRequest.model_fields
    assert "canonical_prompt_template_version_id" not in GeneratePackRequest.model_fields
    assert "platform_prompt_template_version_id" not in GeneratePackRequest.model_fields
    assert "platform_prompt_template_version_id" not in RegenerateVariantRequest.model_fields
    with pytest.raises(ValueError):
        GeneratePackRequest.model_validate(
            {
                "platform": "telegram",
                "generation_provider_profile_id": str(uuid4()),
            }
        )


@pytest.mark.asyncio
async def test_release_four_revision_projection_keeps_gate_rows_and_adds_typed_validation_issues():
    from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
    from app.stories.models import StoryRevision

    pack = SimpleNamespace(id=uuid4(), story_revision_id=uuid4())
    variant = SimpleNamespace(id=uuid4(), content_pack_id=pack.id, platform="x")
    story_revision = SimpleNamespace(id=pack.story_revision_id, story_id=uuid4())
    revision = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content={
            "mode": "single",
            "posts": [
                {
                    "order": 1,
                    "text": "Grounded post",
                    "media": [],
                    "citations": [
                        {
                            "evidence_key": "evidence:one",
                            "evidence_snapshot_id": str(uuid4()),
                            "source_url": "https://example.com/report",
                            "locator": "chars:0-8",
                            "excerpt_sha256": "a" * 64,
                        }
                    ],
                }
            ],
            "link_strategy": "last_post",
            "manual_checklist": ["Verify copy"],
        },
        content_hash="b" * 64,
        evidence_map=[],
        validation_results=[{"gate": "x_platform_recheck_required", "ok": True, "reason": "Recheck in X"}],
        approval_state="pending_review",
        created_by="generation",
        created_at=datetime.now(UTC),
    )

    class Session:
        async def get(self, model, identifier):
            return {
                (PlatformVariant, variant.id): variant,
                (ContentPack, pack.id): pack,
                (StoryRevision, story_revision.id): story_revision,
            }.get((model, identifier))

    output = await _revision_out(Session(), revision)

    assert output["platform"] == "x"
    assert output["manual_checklist"] == ["Verify copy"]
    assert output["validation_results"] == revision.validation_results
    assert output["validation_issues"][0]["code"] == "x_platform_recheck_required"
    assert output["validation_issues"][0]["severity"] == "warning"
    assert output["prompt_version"] is None


@pytest.mark.asyncio
async def test_revision_projection_redacts_legacy_validation_results_and_derived_issues():
    from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
    from app.stories.models import StoryRevision

    pack = SimpleNamespace(id=uuid4(), story_revision_id=uuid4())
    variant = SimpleNamespace(id=uuid4(), content_pack_id=pack.id, platform="x")
    story_revision = SimpleNamespace(id=pack.story_revision_id, story_id=uuid4(), citations=[])
    revision = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content={"mode": "invalid"},
        content_hash="b" * 64,
        evidence_map=[],
        validation_results=[
            {
                "gate": "provider_failed",
                "ok": False,
                "reason": "authorization: Bearer revision-validation-canary",
            }
        ],
        approval_state="pending_review",
        created_by="generation",
        created_at=datetime.now(UTC),
    )

    class Session:
        async def get(self, model, identifier):
            return {
                (PlatformVariant, variant.id): variant,
                (ContentPack, pack.id): pack,
                (StoryRevision, story_revision.id): story_revision,
            }.get((model, identifier))

    output = await _revision_out(Session(), revision)

    assert "revision-validation-canary" not in str(output)
    assert output["validation_results"][0]["reason"] == "authorization:[REDACTED]"
    assert output["validation_issues"][0]["message"] == "authorization:[REDACTED]"


@pytest.mark.asyncio
async def test_telegram_revision_projection_keeps_checklist_adjacent_to_exact_nine_key_content():
    from app.generation.models import (
        ContentPack,
        GenerationAttempt,
        GenerationRun,
        PlatformVariant,
        PlatformVariantRevision,
    )
    from app.stories.models import StoryRevision

    pack = SimpleNamespace(id=uuid4(), story_revision_id=uuid4())
    variant = SimpleNamespace(id=uuid4(), content_pack_id=pack.id, platform="telegram")
    story_revision = SimpleNamespace(id=pack.story_revision_id, story_id=uuid4())
    attempt = SimpleNamespace(
        id=uuid4(),
        generation_run_id=uuid4(),
        resolved_model="api_key=model-output-canary",
    )
    content = {
        "body": "Grounded",
        "parse_mode": "HTML",
        "buttons": [],
        "source_item_id": None,
        "source_url": None,
        "media_policy": "omit",
        "media_asset_ids": [],
        "direction": "rtl",
        "dry_run": False,
    }
    revision = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=attempt.id,
        revision_number=1,
        content=content,
        content_hash="b" * 64,
        evidence_map=[],
        validation_results=[{"gate": "telegram_schema", "ok": True, "reason": None}],
        approval_state="pending_review",
        created_by="generation",
        created_at=datetime.now(UTC),
    )

    class Session:
        async def get(self, model, identifier):
            return {
                (PlatformVariant, variant.id): variant,
                (ContentPack, pack.id): pack,
                (StoryRevision, story_revision.id): story_revision,
                (GenerationAttempt, attempt.id): attempt,
                (GenerationRun, attempt.generation_run_id): None,
            }.get((model, identifier))

    output = await _revision_out(Session(), revision)

    assert output["platform"] == "telegram"
    assert output["manual_checklist"] == []
    assert output["content"] == content
    assert len(output["content"]) == 9
    assert output["resolved_model"] == "api_key=[REDACTED]"
    assert "model-output-canary" not in str(output)


@pytest.mark.asyncio
async def test_revision_projection_exposes_safe_deduplicated_evidence_source_media():
    from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
    from app.stories.models import StoryRevision

    story_id, snapshot_id, content_item_id, asset_id = uuid4(), uuid4(), uuid4(), uuid4()
    citation = {
        "evidence_key": "evidence:one",
        "evidence_snapshot_id": str(snapshot_id),
        "source_url": "https://example.com/report",
        "locator": "chars:0-8",
        "excerpt_sha256": "a" * 64,
    }
    pack = SimpleNamespace(id=uuid4(), story_revision_id=uuid4())
    variant = SimpleNamespace(id=uuid4(), content_pack_id=pack.id, platform="x")
    story_revision = SimpleNamespace(
        id=pack.story_revision_id,
        story_id=story_id,
        citations=[citation],
    )
    snapshot = SimpleNamespace(
        id=snapshot_id,
        story_id=story_id,
        content_item_id=content_item_id,
    )
    link = SimpleNamespace(
        content_item_id=content_item_id,
        media_asset_id=asset_id,
        role="hero",
        sort_order=1,
    )
    duplicate = SimpleNamespace(
        content_item_id=content_item_id,
        media_asset_id=asset_id,
        role="inline",
        sort_order=2,
    )
    asset = SimpleNamespace(
        id=asset_id,
        original_url="https://secret.example/media.jpg",
        storage_path="/data/media/grounded.jpg",
        kind="image",
        mime_type="image/jpeg",
        width=1200,
        height=800,
        duration_seconds=None,
        byte_length=1234,
        checksum_sha256="b" * 64,
        fetch_status="downloaded",
    )
    revision = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content={
            "mode": "single",
            "posts": [{"order": 1, "text": "Grounded", "media": [], "citations": [citation]}],
            "link_strategy": "last_post",
            "manual_checklist": ["Verify copy"],
        },
        content_hash="b" * 64,
        evidence_map=[citation],
        validation_results=[],
        approval_state="pending_review",
        created_by="generation",
        created_at=datetime.now(UTC),
    )

    class Session:
        def __init__(self):
            self.scalar_calls = 0

        async def get(self, model, identifier):
            return {
                (PlatformVariant, variant.id): variant,
                (ContentPack, pack.id): pack,
                (StoryRevision, story_revision.id): story_revision,
            }.get((model, identifier))

        async def scalars(self, statement):
            self.scalar_calls += 1
            return {1: [snapshot], 2: [link, duplicate], 3: [asset]}[self.scalar_calls]

    output = await _revision_out(Session(), revision)

    assert output["source_media"] == [
        {
            "id": str(asset_id),
            "kind": "image",
            "mime_type": "image/jpeg",
            "width": 1200,
            "height": 800,
            "duration_seconds": None,
            "byte_length": 1234,
            "checksum_sha256": "b" * 64,
            "fetch_status": "downloaded",
            "available": True,
            "role": "hero",
            "order": 1,
        }
    ]
    assert all("original_url" not in item and "storage_path" not in item for item in output["source_media"])


def _manual_route_request():
    citation = {
        "evidence_key": "evidence:one",
        "evidence_snapshot_id": str(uuid4()),
        "source_url": "https://example.com/report",
        "locator": "chars:0-8",
        "excerpt_sha256": "a" * 64,
    }
    return ManualPlatformEditRequest.model_validate(
        {
            "base_revision_id": str(uuid4()),
            "base_content_hash": "b" * 64,
            "payload": {
                "platform": "instagram",
                "content": {
                    "hook": "Grounded",
                    "caption": "Grounded caption",
                    "cta": "Read more",
                    "hashtags": [],
                    "alt_text": "Summary card",
                    "carousel": [],
                    "citations": [citation],
                    "manual_checklist": ["Verify copy"],
                },
            },
            "evidence_map": [citation],
            "edit_note": "Operator edit",
        }
    )


@pytest.mark.parametrize("message", ["base revision is stale", "platform conflicts with target variant"])
@pytest.mark.asyncio
async def test_edit_route_maps_stale_and_platform_conflicts_to_http_409(monkeypatch, message):
    class Service:
        def __init__(self, session):
            pass

        async def edit_manual_platform_variant(self, variant_id, body):
            raise RevisionConflict(message)

    monkeypatch.setattr("app.api.content_packs.EditorialService", Service)

    with pytest.raises(HTTPException) as caught:
        await edit_variant_route(uuid4(), _manual_route_request(), SimpleNamespace())

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "stale_revision",
        "message": message,
    }


@pytest.mark.asyncio
async def test_edit_route_maps_fabricated_evidence_to_typed_http_422(monkeypatch):
    class Service:
        def __init__(self, session):
            pass

        async def edit_manual_platform_variant(self, variant_id, body):
            raise InvalidGenerationRequest("citation integrity failed", code="citation_integrity")

    monkeypatch.setattr("app.api.content_packs.EditorialService", Service)

    with pytest.raises(HTTPException) as caught:
        await edit_variant_route(uuid4(), _manual_route_request(), SimpleNamespace())

    assert caught.value.status_code == 422
    assert caught.value.detail == {
        "code": "validation_failed",
        "message": "citation integrity failed",
        "reason_code": "citation_integrity",
    }


@pytest.mark.asyncio
async def test_telegram_edit_route_maps_reverse_platform_conflict_to_http_409(monkeypatch):
    class Service:
        def __init__(self, session):
            pass

        async def edit_variant(self, variant_id, body):
            raise RevisionConflict("platform conflicts with Telegram edit")

    monkeypatch.setattr("app.api.content_packs.EditorialService", Service)
    request = EditVariantRequest(
        base_revision_id=uuid4(),
        base_content_hash="b" * 64,
        content=TelegramRewriteOutput(body="Grounded", parse_mode="HTML", buttons=[]),
        media_asset_ids=[],
        edit_note="Operator edit",
    )

    with pytest.raises(HTTPException) as caught:
        await edit_variant_route(uuid4(), request, SimpleNamespace())

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "stale_revision",
        "message": "platform conflicts with Telegram edit",
    }


@pytest.mark.asyncio
async def test_edit_route_dispatches_union_and_commits_only_successful_201_children(monkeypatch):
    calls = []
    created = SimpleNamespace(id=uuid4())

    class Service:
        def __init__(self, session):
            pass

        async def edit_manual_platform_variant(self, variant_id, body):
            calls.append(("manual", variant_id, body.payload.platform))
            return created

        async def edit_variant(self, variant_id, body):
            calls.append(("telegram", variant_id, body.content.body))
            return created

    class Session:
        def __init__(self):
            self.commits = 0

        async def commit(self):
            self.commits += 1

    async def revision_out(session, row):
        return {"id": row.id}

    monkeypatch.setattr("app.api.content_packs.EditorialService", Service)
    monkeypatch.setattr("app.api.content_packs._revision_out", revision_out)
    session = Session()
    manual_variant_id, telegram_variant_id = uuid4(), uuid4()
    manual = await edit_variant_route(manual_variant_id, _manual_route_request(), session)
    telegram = await edit_variant_route(
        telegram_variant_id,
        EditVariantRequest(
            base_revision_id=uuid4(),
            base_content_hash="b" * 64,
            content=TelegramRewriteOutput(body="Grounded", parse_mode="HTML", buttons=[]),
            media_asset_ids=[],
            edit_note="Operator edit",
        ),
        session,
    )

    assert manual == telegram == {"id": created.id}
    assert calls == [
        ("manual", manual_variant_id, "instagram"),
        ("telegram", telegram_variant_id, "Grounded"),
    ]
    assert session.commits == 2


@pytest.mark.asyncio
async def test_plural_request_projection_requires_every_requested_variant_before_ready():
    from app.generation.models import ContentPack
    from app.jobs.models import WorkflowJob

    story_id, revision_id, child_id, pack_id, brand_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id, brand_id=brand_id)
    parent.payload.pop("platform")
    parent.payload["platforms"] = ["telegram", "instagram"]
    child = child_job(parent, child_id, revision_id, status="succeeded", error=None)
    child.payload.pop("platform")
    child.payload["platforms"] = ["telegram", "instagram"]
    child.result = {"content_pack_id": str(pack_id)}
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=revision_id,
        brand_profile_id=brand_id,
        status="draft",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class Session:
        async def get(self, model, identifier):
            if model is WorkflowJob:
                return child
            if model is ContentPack:
                return pack
            return None

        async def scalars(self, statement):
            return [SimpleNamespace(platform="telegram")]

        async def scalar(self, statement):
            return None

    row = await _request_out(Session(), parent)

    assert row["status"] == "needs_review"
    assert row["pack"] is None


@pytest.mark.asyncio
async def test_needs_review_child_projects_exact_partial_pack_instead_of_hiding_it():
    from app.generation.models import ContentPack
    from app.jobs.models import WorkflowJob
    from app.stories.models import StoryRevision

    story_id, revision_id, child_id, pack_id, brand_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id, brand_id=brand_id)
    child = child_job(parent, child_id, revision_id, status="needs_review", error="Instagram needs review")
    child.result = {"content_pack_id": str(pack_id)}
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=revision_id,
        brand_profile_id=brand_id,
        status="draft",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class Session:
        async def get(self, model, identifier):
            if model is WorkflowJob:
                return child
            if model is ContentPack:
                return pack
            if model is StoryRevision:
                return SimpleNamespace(story_id=story_id)
            return None

        async def scalar(self, statement):
            return None

        async def scalars(self, statement):
            return []

    row = await _request_out(Session(), parent)

    assert row["status"] == "needs_review"
    assert row["last_failure"] == "Instagram needs review"
    assert row["pack"]["id"] == pack_id
    assert row["pack"]["variants"] == []


@pytest.mark.asyncio
async def test_succeeded_child_with_variant_but_no_current_revision_is_not_ready():
    from app.generation.models import ContentPack
    from app.jobs.models import WorkflowJob

    story_id, revision_id, child_id, pack_id, brand_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id, brand_id=brand_id)
    child = child_job(parent, child_id, revision_id, status="succeeded", error=None)
    child.result = {"content_pack_id": str(pack_id)}
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=revision_id,
        brand_profile_id=brand_id,
        status="draft",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class Session:
        async def get(self, model, identifier):
            if model is WorkflowJob:
                return child
            if model is ContentPack:
                return pack
            return None

        async def scalars(self, statement):
            return [SimpleNamespace(id=uuid4(), platform="telegram")]

        async def scalar(self, statement):
            return None

    row = await _request_out(Session(), parent)

    assert row["status"] == "needs_review"
    assert row["pack"] is None


@pytest.mark.asyncio
async def test_provider_failure_is_visible_before_a_content_pack_exists():
    story_id = uuid4()
    job = SimpleNamespace(
        id=uuid4(),
        payload={"story_id": str(story_id), "generation_provider_profile_id": str(uuid4())},
        result={},
        status="needs_review",
        error_message="Provider response failed validation",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    row = await _request_out(SimpleNamespace(), job)
    assert row["job_id"] == job.id
    assert row["story_id"] == story_id
    assert row["status"] == "needs_review"
    assert row["last_failure"] == "Provider response failed validation"
    assert row["pack"] is None
    assert "generation_provider_profile_id" not in row


def test_auto_research_job_projects_its_content_pack_continuation_without_payload_leakage():
    story_id = uuid4()
    job = SimpleNamespace(
        id=uuid4(),
        job_type="research_story",
        payload={
            "continuations": [
                {
                    "job_type": "content_pack.generate",
                    "subscriber_id": "request-1",
                    "payload": {"story_id": str(story_id), "generation_provider_profile_id": str(uuid4())},
                }
            ]
        },
        status="running",
        error_message=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    rows = _research_request_out(job)
    assert len(rows) == 1
    assert rows[0]["job_id"] == job.id
    assert rows[0]["story_id"] == story_id
    assert rows[0]["status"] == "running"
    assert "generation_provider_profile_id" not in rows[0]


@pytest.mark.asyncio
async def test_canonical_parent_uses_actionable_failed_telegram_child_before_pack():
    story_id, revision_id, child_id = uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id)
    child = child_job(parent, child_id, revision_id, status="needs_review", error="Telegram provider rejected output")

    class Session:
        async def get(self, model, identifier):
            return child

        async def scalar(self, statement):
            raise AssertionError("non-succeeded child must win before any pack fallback")

    row = await _request_out(Session(), parent)
    assert row["status"] == "needs_review"
    assert row["job_id"] == child.id
    assert row["last_failure"] == "Telegram provider rejected output"
    assert row["pack"] is None


@pytest.mark.asyncio
async def test_succeeded_telegram_child_with_exact_pack_is_ready():
    from app.generation.models import ContentPack
    from app.jobs.models import WorkflowJob
    from app.stories.models import StoryRevision

    story_id, revision_id, child_id, pack_id = uuid4(), uuid4(), uuid4(), uuid4()
    brand_id = uuid4()
    parent = request_job(story_id, revision_id, child_id, brand_id=brand_id)
    child = child_job(parent, child_id, revision_id, status="succeeded", error=None)
    child.result = {"content_pack_id": str(pack_id)}
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=revision_id,
        brand_profile_id=brand_id,
        status="draft",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class Session:
        async def get(self, model, identifier):
            if model is WorkflowJob:
                return child
            if model is ContentPack:
                return pack
            if model is StoryRevision:
                return SimpleNamespace(story_id=story_id)
            return None

        async def scalars(self, statement):
            # The pack projection resolves each table once for the page: the
            # story revisions, then the variants, then a single ranked query for
            # every variant's current revision. This pack has no revisions, so
            # that last query answers empty.
            text = str(statement)
            if "platform_variant_revisions" in text:
                return []
            if "story_revisions" in text:
                return [SimpleNamespace(id=revision_id, story_id=story_id)]
            return [SimpleNamespace(id=uuid4(), content_pack_id=pack_id, platform="telegram")]

        async def scalar(self, statement):
            return uuid4()

    row = await _request_out(Session(), parent)
    assert row["status"] == "ready"
    assert row["job_id"] == child.id
    assert row["pack"]["id"] == pack_id


@pytest.mark.asyncio
async def test_unrelated_telegram_child_is_not_associated():
    story_id, revision_id, child_id = uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id)
    unrelated = child_job(parent, child_id, uuid4(), status="needs_review", error="Unrelated failure")

    class Session:
        async def get(self, model, identifier):
            return unrelated

        async def scalar(self, statement):
            return None

    row = await _request_out(Session(), parent)
    assert row["job_id"] == parent.id
    assert row["status"] == "succeeded"
    assert row["last_failure"] is None
    assert row["pack"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [None, "web"])
async def test_child_missing_or_wrong_platform_is_not_associated(platform):
    story_id, revision_id, child_id = uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id)
    child = child_job(parent, child_id, revision_id, status="needs_review", error="Must not leak")
    if platform is None:
        child.payload.pop("platform")
    else:
        child.payload["platform"] = platform

    class Session:
        async def get(self, model, identifier):
            return child

    row = await _request_out(Session(), parent)
    assert row["job_id"] == parent.id
    assert row["status"] == "succeeded"
    assert row["last_failure"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("available_platform", [None, "web"])
async def test_exact_result_pack_without_telegram_variant_is_not_ready(available_platform):
    from app.generation.models import ContentPack
    from app.jobs.models import WorkflowJob

    story_id, revision_id, child_id, pack_id, brand_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id, brand_id=brand_id)
    child = child_job(parent, child_id, revision_id, status="succeeded", error=None)
    child.result = {"content_pack_id": str(pack_id)}
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=revision_id,
        brand_profile_id=brand_id,
        status="draft",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class Session:
        async def get(self, model, identifier):
            if model is WorkflowJob:
                return child
            if model is ContentPack:
                return pack
            return None

        async def scalar(self, statement):
            return None

        async def scalars(self, statement):
            return [] if available_platform is None else [SimpleNamespace(id=uuid4(), platform=available_platform)]

    row = await _request_out(Session(), parent)
    assert row["job_id"] == child.id
    assert row["status"] == "needs_review"
    assert row["last_failure"] == "Succeeded child did not produce an exact Telegram content pack"
    assert row["pack"] is None


@pytest.mark.asyncio
async def test_telegram_child_cannot_attach_a_pack_for_another_revision():
    from app.generation.models import ContentPack
    from app.jobs.models import WorkflowJob

    story_id, revision_id, child_id, pack_id = uuid4(), uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id)
    child = child_job(parent, child_id, revision_id, status="succeeded", error=None)
    child.result = {"content_pack_id": str(pack_id)}
    unrelated_pack = SimpleNamespace(id=pack_id, story_revision_id=uuid4())

    class Session:
        async def get(self, model, identifier):
            if model is WorkflowJob:
                return child
            if model is ContentPack:
                return unrelated_pack
            return None

        async def scalar(self, statement):
            return None

    row = await _request_out(Session(), parent)
    assert row["status"] == "needs_review"
    assert row["last_failure"] == "Succeeded child did not produce an exact Telegram content pack"
    assert row["pack"] is None


@pytest.mark.asyncio
async def test_succeeded_child_wrong_brand_result_is_rejected_without_ready():
    from app.generation.models import ContentPack
    from app.jobs.models import WorkflowJob

    story_id, revision_id, child_id, pack_id, brand_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id, brand_id=brand_id)
    child = child_job(parent, child_id, revision_id, status="succeeded", error=None)
    child.result = {"content_pack_id": str(pack_id)}
    wrong_brand_pack = SimpleNamespace(id=pack_id, story_revision_id=revision_id, brand_profile_id=uuid4())

    class Session:
        async def get(self, model, identifier):
            if model is WorkflowJob:
                return child
            if model is ContentPack:
                return wrong_brand_pack
            return None

        async def scalar(self, statement):
            return None

    row = await _request_out(Session(), parent)
    assert row["job_id"] == child.id
    assert row["status"] == "needs_review"
    assert row["last_failure"] == "Succeeded child did not produce an exact Telegram content pack"
    assert row["pack"] is None


@pytest.mark.asyncio
async def test_failed_child_wins_over_existing_wrong_brand_pack():
    story_id, revision_id, child_id, brand_id = uuid4(), uuid4(), uuid4(), uuid4()
    parent = request_job(story_id, revision_id, child_id, brand_id=brand_id)
    child = child_job(parent, child_id, revision_id, status="failed", error="Exact child failed")

    class Session:
        async def get(self, model, identifier):
            return child

        async def scalar(self, statement):
            raise AssertionError("failed child must not search any fallback pack")

    row = await _request_out(Session(), parent)
    assert row["job_id"] == child.id
    assert row["status"] == "failed"
    assert row["last_failure"] == "Exact child failed"
    assert row["pack"] is None


def request_job(story_id, revision_id, child_id, *, brand_id=None):
    brand_id = brand_id or uuid4()
    return SimpleNamespace(
        id=uuid4(),
        job_type="content_pack.generate",
        status="succeeded",
        payload={"story_id": str(story_id), "brand_profile_id": str(brand_id), "platform": "telegram"},
        result={"story_revision_id": str(revision_id), "continuation_job_id": str(child_id)},
        idempotency_key="root",
        error_message=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def child_job(parent, child_id, revision_id, *, status, error):
    return SimpleNamespace(
        id=child_id,
        job_type="content_pack.generate_telegram",
        status=status,
        payload={
            "story_revision_id": str(revision_id),
            "brand_profile_id": parent.payload["brand_profile_id"],
            "platform": "telegram",
        },
        result={},
        idempotency_key=f"content-pack-telegram:{parent.id}:{revision_id}",
        error_message=error,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _projection_pack(story_revision_id, now):
    return SimpleNamespace(
        id=uuid4(),
        story_revision_id=story_revision_id,
        brand_profile_id=uuid4(),
        status="draft",
        created_at=now,
        updated_at=now,
    )


def _projection_revision(variant_id, now):
    from app.generation.models import PlatformVariantRevision

    # A real ORM instance: the pack projection only treats a ranked row as a
    # current revision when it is one, so a namespace would silently project
    # every variant as revision-less and hide the query counts under test.
    return PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant_id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content={},
        content_hash="a" * 64,
        evidence_map=[],
        validation_results=[],
        approval_state="draft",
        approval_note=None,
        approved_at=None,
        created_by="operator",
        created_at=now,
    )


class _CountingProjectionSession:
    """Answers a pack page's selects and records which table each one read."""

    def __init__(self, packs, variants, revisions, story_revisions):
        self.rows = {
            "content_packs": packs,
            "platform_variants": variants,
            "platform_variant_revisions": revisions,
            "story_revisions": story_revisions,
        }
        self.by_id = {row.id: row for group in self.rows.values() for row in group}
        self.reads = []

    def _table(self, statement):
        text = str(statement)
        # "platform_variants" is a prefix of no other table name here, but the
        # revision table must be recognised before it to stay unambiguous.
        for table in (
            "platform_variant_revisions",
            "platform_variants",
            "story_evidence_snapshots",
            "content_packs",
            "story_revisions",
        ):
            if table in text:
                return table
        return "other"

    async def scalars(self, statement):
        table = self._table(statement)
        self.reads.append(table)
        return self.rows.get(table, [])

    async def get(self, _model, identifier):
        return self.by_id.get(identifier)


def _projection_page(pack_count, variants_per_pack):
    now = datetime(2026, 8, 13, 9, tzinfo=UTC)
    citation = {
        "evidence_key": "evidence:one",
        "evidence_snapshot_id": str(uuid4()),
        "source_url": "https://example.com/report",
        "locator": "chars:0-8",
        "excerpt_sha256": "b" * 64,
    }
    packs, variants, revisions, story_revisions = [], [], [], []
    for _ in range(pack_count):
        story_revision = SimpleNamespace(id=uuid4(), story_id=uuid4(), citations=[citation])
        story_revisions.append(story_revision)
        pack = _projection_pack(story_revision.id, now)
        packs.append(pack)
        for index in range(variants_per_pack):
            variant = SimpleNamespace(id=uuid4(), content_pack_id=pack.id, platform=("telegram", "x")[index % 2])
            variants.append(variant)
            revisions.append(_projection_revision(variant.id, now))
    return _CountingProjectionSession(packs, variants, revisions, story_revisions), packs


@pytest.mark.asyncio
@pytest.mark.parametrize("pack_count", [1, 4])
async def test_pack_page_reads_each_table_once_regardless_of_page_size(pack_count):
    from app.api.content_pack_mappers import _packs_out

    session, packs = _projection_page(pack_count, variants_per_pack=3)

    projected = await _packs_out(session, packs)

    assert [row["id"] for row in projected] == [pack.id for pack in packs]
    assert all(len(row["variants"]) == 3 for row in projected)
    assert all(item["current_revision"] is not None for row in projected for item in row["variants"])
    # One ranked query covers every variant's current revision, and each other
    # table is read once for the projection and once to warm the revision
    # graph — counts that must not move with pack_count.
    assert session.reads.count("platform_variant_revisions") == 1
    assert session.reads.count("platform_variants") == 2
    assert session.reads.count("content_packs") == 1
    assert session.reads.count("story_revisions") == 2
    # Source media resolves per story revision, not per variant: the three
    # variants of a pack share one revision, so a per-variant projection would
    # issue three times as many snapshot reads.
    assert session.reads.count("story_evidence_snapshots") == pack_count
