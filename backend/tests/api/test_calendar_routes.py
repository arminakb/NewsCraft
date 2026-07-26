from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.calendar as calendar_api
from app.api.calendar import ManualPublicationPlanOut, router
from app.db.session import get_session
from app.manual_publication.calendar import encode_publication_cursor
from app.manual_publication.service import ManualPublicationError

PLAN_ID = UUID("11111111-1111-4111-8111-111111111111")
REVISION_ID = UUID("31111111-1111-4111-8111-111111111111")
OTHER_REVISION_ID = UUID("32222222-2222-4222-8222-222222222222")


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture
def api_client():
    session = _Session()
    app = FastAPI()
    app.include_router(router)

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, session


def _plan(**overrides):
    values = {
        "id": PLAN_ID,
        "platform_variant_revision_id": REVISION_ID,
        "platform": "instagram",
        "scheduled_for": datetime(2026, 7, 14, 8, tzinfo=UTC),
        "display_timezone": "Asia/Tehran",
        "status": "planned",
        "checklist_state": {"caption_final": False},
        "external_url": None,
        "operator_note": None,
        "completed_at": None,
        "created_at": datetime(2026, 7, 13, 8, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 13, 8, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_manual_plan_output_rejects_non_boolean_checklist_storage():
    with pytest.raises(ValidationError):
        ManualPublicationPlanOut.model_validate(_plan(checklist_state={"caption_final": 1}))


def test_calendar_route_allows_exact_93_day_window_and_returns_strict_projection(api_client, monkeypatch):
    client, session = api_client
    start = datetime(2026, 7, 13, 8, tzinfo=UTC)
    seen = {}

    async def fake_list(_session, *, start, end, display_timezone):
        seen.update(start=start, end=end, display_timezone=display_timezone)
        return [
            {
                "id": f"manual:{PLAN_ID}",
                "kind": "manual_publication",
                "platform": "instagram",
                "revision_id": REVISION_ID,
                "title": "Verified",
                "starts_at": start,
                "status": "planned",
                "action_url": f"/review/{REVISION_ID}",
            }
        ]

    monkeypatch.setattr(calendar_api, "list_calendar_events", fake_list)
    response = client.get(
        "/calendar",
        params={
            "start": start.isoformat(),
            "end": (start + timedelta(days=93)).isoformat(),
            "timezone": "Asia/Tehran",
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["revision_id"] == str(REVISION_ID)
    assert response.json()["timezone"] == "Asia/Tehran"
    assert seen == {
        "start": start,
        "end": start + timedelta(days=93),
        "display_timezone": "Asia/Tehran",
    }
    assert session.commits == 0


@pytest.mark.parametrize(
    "params",
    [
        {
            "start": "2026-07-13T08:00:00Z",
            "end": "2026-10-14T08:00:00.000001Z",
            "timezone": "UTC",
        },
        {
            "start": "2026-07-13T08:00:00",
            "end": "2026-07-14T08:00:00Z",
            "timezone": "UTC",
        },
        {
            "start": "2026-07-14T08:00:00Z",
            "end": "2026-07-13T08:00:00Z",
            "timezone": "UTC",
        },
        {
            "start": "2026-07-13T08:00:00Z",
            "end": "2026-07-14T08:00:00Z",
            "timezone": "Mars/Olympus_Mons",
        },
        {
            "start": "2026-07-13T08:00:00Z",
            "end": "2026-07-14T08:00:00Z",
            "timezone": "/etc/passwd",
        },
        {
            "start": "2026-07-13T08:00:00Z",
            "end": "2026-07-14T08:00:00Z",
            "timezone": "../UTC",
        },
    ],
)
def test_calendar_route_rejects_invalid_windows_before_query(api_client, monkeypatch, params):
    client, _session = api_client

    async def should_not_query(*_args, **_kwargs):
        raise AssertionError("invalid windows must not query")

    monkeypatch.setattr(calendar_api, "list_calendar_events", should_not_query)
    response = client.get("/calendar", params=params)
    assert response.status_code == 422


def test_calendar_route_does_not_misreport_projection_corruption_as_user_input(api_client, monkeypatch):
    client, _session = api_client

    async def corrupt_projection(*_args, **_kwargs):
        raise ValueError("stored calendar row is invalid")

    monkeypatch.setattr(calendar_api, "list_calendar_events", corrupt_projection)
    with pytest.raises(ValueError, match="stored calendar row is invalid"):
        client.get(
            "/calendar",
            params={
                "start": "2026-07-13T08:00:00Z",
                "end": "2026-07-14T08:00:00Z",
                "timezone": "UTC",
            },
        )


def test_publications_route_delegates_stable_cursor_platform_and_limit(api_client, monkeypatch):
    client, session = api_client
    seen = {}
    cursor = encode_publication_cursor(
        datetime(2026, 7, 13, 10, tzinfo=UTC),
        "manual_publication",
        PLAN_ID,
    )

    async def fake_list(_session, *, cursor, platform, limit):
        seen.update(cursor=cursor, platform=platform, limit=limit)
        return {
            "items": [
                {
                    "id": PLAN_ID,
                    "kind": "manual_publication",
                    "platform": "blog",
                    "revision_id": REVISION_ID,
                    "occurred_at": datetime(2026, 7, 13, 9, tzinfo=UTC),
                    "status": "manual_published",
                    "external_url": "https://news.example.test/post",
                    "action_url": f"/review/{REVISION_ID}",
                }
            ],
            "next_cursor": "next-page",
        }

    monkeypatch.setattr(calendar_api, "list_publications", fake_list)
    response = client.get(
        "/publications",
        params={"cursor": cursor, "platform": "blog", "limit": 7},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["kind"] == "manual_publication"
    assert response.json()["items"][0]["revision_id"] == str(REVISION_ID)
    assert response.json()["next_cursor"] == "next-page"
    assert seen == {"cursor": cursor, "platform": "blog", "limit": 7}
    assert session.commits == 0


def test_publications_route_rejects_bad_cursor_and_platform(api_client, monkeypatch):
    client, _session = api_client

    async def should_not_query(*_args, **_kwargs):
        raise AssertionError("invalid cursor must not query")

    monkeypatch.setattr(calendar_api, "list_publications", should_not_query)
    invalid_cursor_response = client.get("/publications", params={"cursor": "bad"})
    invalid_platform_response = client.get("/publications", params={"platform": "linkedin"})
    assert invalid_cursor_response.status_code == 422
    assert invalid_platform_response.status_code == 422


def test_publications_route_does_not_mask_projection_corruption(api_client, monkeypatch):
    client, _session = api_client

    async def corrupt_projection(*_args, **_kwargs):
        raise ValueError("stored publication row is invalid")

    monkeypatch.setattr(calendar_api, "list_publications", corrupt_projection)
    with pytest.raises(ValueError, match="stored publication row is invalid"):
        client.get("/publications")


def test_real_application_registers_calendar_and_manual_publication_routes():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "get" in paths["/calendar"]
    assert "get" in paths["/publications"]
    assert "post" in paths["/manual-publication-plans"]
    assert "get" in paths["/platform-variant-revisions/{revision_id}/manual-publication-plan"]
    assert "patch" in paths["/manual-publication-plans/{plan_id}/checklist"]
    assert "post" in paths["/manual-publication-plans/{plan_id}/mark-published"]
    assert "post" in paths["/manual-publication-plans/{plan_id}/cancel"]


def test_latest_manual_plan_for_revision_is_read_only_and_exact(api_client, monkeypatch):
    client, session = api_client
    calls = []

    class FakeService:
        def __init__(self, bound_session):
            assert bound_session is session

        async def latest_plan_for_revision(self, revision_id):
            calls.append(revision_id)
            return _plan()

    monkeypatch.setattr(calendar_api, "ManualPublicationService", FakeService)
    response = client.get(f"/platform-variant-revisions/{REVISION_ID}/manual-publication-plan")

    assert response.status_code == 200
    assert response.json()["id"] == str(PLAN_ID)
    assert response.json()["platform_variant_revision_id"] == str(REVISION_ID)
    assert calls == [REVISION_ID]
    assert session.commits == 0


def test_latest_manual_plan_for_revision_returns_404_without_writes(api_client, monkeypatch):
    client, session = api_client

    class FakeService:
        def __init__(self, bound_session):
            assert bound_session is session

        async def latest_plan_for_revision(self, _revision_id):
            return None

    monkeypatch.setattr(calendar_api, "ManualPublicationService", FakeService)
    response = client.get(f"/platform-variant-revisions/{REVISION_ID}/manual-publication-plan")

    assert response.status_code == 404
    assert response.json() == {"detail": "Manual publication plan not found"}
    assert session.commits == 0


def test_latest_manual_plan_for_revision_does_not_mask_projection_corruption(
    api_client,
    monkeypatch,
):
    client, session = api_client

    class FakeService:
        def __init__(self, bound_session):
            assert bound_session is session

        async def latest_plan_for_revision(self, _revision_id):
            return _plan(platform_variant_revision_id=OTHER_REVISION_ID)

    monkeypatch.setattr(calendar_api, "ManualPublicationService", FakeService)
    with pytest.raises(RuntimeError, match="revision identity mismatch"):
        client.get(f"/platform-variant-revisions/{REVISION_ID}/manual-publication-plan")
    assert session.commits == 0


@pytest.mark.parametrize(
    ("method", "path", "json_body", "service_method", "expected_kwargs"),
    [
        (
            "post",
            "/manual-publication-plans",
            {
                "revision_id": str(REVISION_ID),
                "scheduled_for": "2026-07-14T08:00:00Z",
                "display_timezone": "Asia/Tehran",
            },
            "create_plan",
            {
                "revision_id": REVISION_ID,
                "scheduled_for": datetime(2026, 7, 14, 8, tzinfo=UTC),
                "display_timezone": "Asia/Tehran",
            },
        ),
        (
            "patch",
            f"/manual-publication-plans/{PLAN_ID}/checklist",
            {"checklist_state": {"caption_final": True}},
            "update_checklist",
            {"plan_id": PLAN_ID, "checklist_state": {"caption_final": True}},
        ),
        (
            "post",
            f"/manual-publication-plans/{PLAN_ID}/mark-published",
            {"external_url": "https://instagram.com/p/abc", "note": "Posted from mobile"},
            "mark_published",
            {
                "plan_id": PLAN_ID,
                "external_url": "https://instagram.com/p/abc",
                "note": "Posted from mobile",
            },
        ),
        (
            "post",
            f"/manual-publication-plans/{PLAN_ID}/cancel",
            None,
            "cancel",
            {"plan_id": PLAN_ID},
        ),
    ],
)
def test_manual_mutations_delegate_exact_values_and_commit_only_after_success(
    api_client,
    monkeypatch,
    method,
    path,
    json_body,
    service_method,
    expected_kwargs,
):
    client, session = api_client
    calls = []

    class FakeService:
        def __init__(self, bound_session):
            assert bound_session is session

        def __getattr__(self, name):
            assert name == service_method

            async def invoke(*args, **kwargs):
                calls.append((args, kwargs))
                return _plan(
                    status="manual_published" if name == "mark_published" else "planned",
                    external_url=("https://instagram.com/p/abc" if name == "mark_published" else None),
                    operator_note="Posted from mobile" if name == "mark_published" else None,
                    completed_at=(datetime(2026, 7, 14, 8, 5, tzinfo=UTC) if name == "mark_published" else None),
                )

            return invoke

    monkeypatch.setattr(calendar_api, "ManualPublicationService", FakeService)
    response = client.request(method, path, json=json_body)

    assert response.status_code in {200, 201}
    assert response.json()["platform_variant_revision_id"] == str(REVISION_ID)
    assert calls == [((), expected_kwargs)]
    assert session.commits == 1


@pytest.mark.parametrize(
    ("body", "expected_note"),
    [
        ({}, None),
        ({"external_url": None, "note": "Recorded manually"}, "Recorded manually"),
    ],
)
def test_mark_published_allows_null_or_omitted_external_url_and_keeps_note_optional(
    api_client,
    monkeypatch,
    body,
    expected_note,
):
    client, session = api_client
    calls = []

    class FakeService:
        def __init__(self, bound_session):
            assert bound_session is session

        async def mark_published(self, **kwargs):
            calls.append(kwargs)
            return _plan(
                status="manual_published",
                external_url=None,
                operator_note=expected_note,
                completed_at=datetime(2026, 7, 14, 8, 5, tzinfo=UTC),
            )

    monkeypatch.setattr(calendar_api, "ManualPublicationService", FakeService)
    response = client.post(f"/manual-publication-plans/{PLAN_ID}/mark-published", json=body)

    assert response.status_code == 200
    assert response.json()["external_url"] is None
    assert response.json()["operator_note"] == expected_note
    assert calls == [{"plan_id": PLAN_ID, "external_url": None, "note": expected_note}]
    assert session.commits == 1


def test_manual_mutation_maps_domain_error_without_committing(api_client, monkeypatch):
    client, session = api_client

    class RejectingService:
        def __init__(self, _session):
            pass

        async def create_plan(self, **_kwargs):
            raise ManualPublicationError(
                "revision is not approved",
                code="revision_not_approved",
                status_code=409,
            )

    monkeypatch.setattr(calendar_api, "ManualPublicationService", RejectingService)
    response = client.post(
        "/manual-publication-plans",
        json={
            "revision_id": str(REVISION_ID),
            "scheduled_for": "2026-07-14T08:00:00Z",
            "display_timezone": "Asia/Tehran",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "revision_not_approved",
            "message": "revision is not approved",
        }
    }
    assert session.commits == 0


@pytest.mark.parametrize(
    "path,json_body",
    [
        (
            "/manual-publication-plans",
            {
                "revision_id": str(REVISION_ID),
                "scheduled_for": "2026-07-14T08:00:00",
                "display_timezone": "Asia/Tehran",
            },
        ),
        (
            f"/manual-publication-plans/{PLAN_ID}/checklist",
            {"checklist_state": {}},
        ),
        (
            f"/manual-publication-plans/{PLAN_ID}/checklist",
            {"checklist_state": {"caption_final": 1}},
        ),
        (
            f"/manual-publication-plans/{PLAN_ID}/checklist",
            {"checklist_state": {"caption_final": "true"}},
        ),
        (
            f"/manual-publication-plans/{PLAN_ID}/mark-published",
            {"external_url": "javascript:alert(1)", "note": "unsafe"},
        ),
        (
            f"/manual-publication-plans/{PLAN_ID}/mark-published",
            {"external_url": "https://example.test/post with spaces", "note": "unsafe"},
        ),
    ],
)
def test_manual_mutation_schemas_are_strict(api_client, path, json_body):
    client, session = api_client
    method = "patch" if path.endswith("/checklist") else "post"
    response = client.request(method, path, json=json_body)
    assert response.status_code == 422
    assert session.commits == 0
