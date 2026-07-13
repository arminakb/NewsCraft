from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.content_packs import _request_out, _research_request_out
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
        ("/platform-variants/{variant_id}/regenerate", "POST"),
        ("/platform-variant-revisions/{revision_id}/approve", "POST"),
        ("/platform-variant-revisions/{revision_id}/reject", "POST"),
    }
    assert expected <= routes


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
            return [SimpleNamespace(id=uuid4(), platform="telegram")]

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
