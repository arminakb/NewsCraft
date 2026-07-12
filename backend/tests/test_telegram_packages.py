from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.content_production.packages import TelegramPackageService, build_package_payload
from app.db.models import (
    Base,
    ContentProductionRun,
    DraftQualityReport,
    TelegramDraft,
    TelegramPostPackage,
    VisualBrief,
)


def test_telegram_post_packages_table_is_registered():
    table = Base.metadata.tables["telegram_post_packages"]

    assert {
        "production_run_id",
        "draft_id",
        "media_asset_id",
        "image_request_id",
        "package_json",
        "approval_status",
        "approved_at",
        "rejected_at",
        "revision_requested_at",
        "created_at",
        "updated_at",
    }.issubset(table.columns.keys())
    assert "ix_telegram_post_packages_approval_status" in {index.name for index in table.indexes}


def test_telegram_post_packages_migration_adds_table():
    migration = Path("alembic/versions/0011_telegram_post_packages.py").read_text()

    assert "telegram_post_packages" in migration
    assert "0010_visual_briefs" in migration
    assert "approval_status" in migration


def test_package_payload_blocks_dispatch_before_final_approval():
    payload = build_package_payload(draft=_draft(), quality_report=_quality_report(), visual_brief=_visual_brief())

    assert payload["approval_status"] == "pending"
    assert payload["dispatch_readiness"] == "blocked_pending_final_approval"
    assert payload["media"]["status"] == "selected"
    assert payload["post_text"]


async def test_package_service_builds_package_and_requests_final_approval():
    run = _run(state="media_ready")
    draft = _draft(production_run_id=run.id)
    quality = _quality_report(production_run_id=run.id, draft_id=draft.id)
    visual = _visual_brief(production_run_id=run.id)
    session = FakeSession()

    package = await TelegramPackageService(session).build_package(
        run=run,
        draft=draft,
        quality_report=quality,
        visual_brief=visual,
    )

    assert isinstance(package, TelegramPostPackage)
    assert package.approval_status == "pending"
    assert package.media_asset_id == visual.selected_media_asset_id
    assert run.state == "final_approval_pending"
    assert session.added == [package]


async def test_final_approval_transitions_to_final_approved():
    run = _run(state="final_approval_pending")
    package = _package(run)
    session = FakeSession()

    approved = await TelegramPackageService(session).approve(run=run, package=package)

    assert approved.approval_status == "approved"
    assert approved.approved_at is not None
    assert run.state == "final_approved"


async def test_final_reject_and_revision_are_explicit_gates():
    reject_run = _run(state="final_approval_pending")
    revision_run = _run(state="final_approval_pending")
    session = FakeSession()

    rejected = await TelegramPackageService(session).reject(run=reject_run, package=_package(reject_run))
    revision = await TelegramPackageService(session).request_revision(run=revision_run, package=_package(revision_run))

    assert rejected.approval_status == "rejected"
    assert reject_run.state == "final_rejected"
    assert revision.approval_status == "revision_requested"
    assert revision_run.state == "revision_requested"


async def test_final_approval_rejects_wrong_state():
    run = _run(state="package_ready")

    with pytest.raises(ValueError):
        await TelegramPackageService(FakeSession()).approve(run=run, package=_package(run))


def _draft(production_run_id=None):
    return TelegramDraft(
        id=uuid4(),
        production_run_id=production_run_id or uuid4(),
        brief_id=uuid4(),
        draft_text="تیتر: خبر\n\nنکات اصلی:\n- The rollout starts this week.",
        title="خبر",
        hashtags_json=["#خبر"],
        source_links_json=["https://example.com/story"],
        warnings_json=[],
        status="draft",
    )


def _quality_report(production_run_id=None, draft_id=None):
    return DraftQualityReport(
        id=uuid4(),
        production_run_id=production_run_id or uuid4(),
        draft_id=draft_id or uuid4(),
        status="passed",
        score=1,
        factuality_warnings_json=[],
        unsupported_claims_json=[],
        style_warnings_json=[],
        required_revisions_json=[],
    )


def _visual_brief(production_run_id=None):
    return VisualBrief(
        id=uuid4(),
        production_run_id=production_run_id or uuid4(),
        status="selected",
        selected_media_asset_id=uuid4(),
        needs_generation=False,
        provider_request_json={},
        provider_result_json={},
    )


def _run(state: str):
    return ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=uuid4(),
        platform="telegram",
        state=state,
    )


def _package(run: ContentProductionRun):
    draft = _draft(production_run_id=run.id)
    return TelegramPostPackage(
        id=uuid4(),
        production_run_id=run.id,
        draft_id=draft.id,
        package_json={},
        approval_status="pending",
    )


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed_count += 1
