from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


@pytest.mark.asyncio
async def test_four_platform_pack_exports_and_manual_completion(
    app_harness,
    researched_story,
):
    requested = await app_harness.request_pack(
        researched_story.id,
        research_run_id=researched_story.research_run_id,
        platforms=["telegram", "instagram", "x", "blog"],
    )
    await app_harness.run_until_idle()

    pack = await app_harness.pack_for_job(requested["job_id"])
    current_revisions = [item["current_revision"] for item in pack["variants"]]
    assert len(current_revisions) == 4
    assert {item["platform"] for item in current_revisions} == {
        "telegram",
        "instagram",
        "x",
        "blog",
    }

    approved = [await app_harness.approve_exact_revision(item) for item in current_revisions]
    revision_ids = [item["id"] for item in approved]
    assert all(item["approval_state"] == "approved" for item in approved)

    export_job = await app_harness.request_export(
        pack["id"],
        revision_ids=revision_ids,
        formats=["json", "markdown", "html", "zip"],
        include_media=False,
    )
    await app_harness.run_until_idle()

    export = await app_harness.export_for_job(export_job["job_id"])
    assert export["status"] == "succeeded"
    artifact = export["artifact"]
    assert artifact["state"] == "complete"
    assert artifact["archive_file"] == "bundle.zip"
    manifest = artifact["manifest"]
    assert manifest["schema_version"] == "newscraft-export-v1"
    assert manifest["content_pack_id"] == pack["id"]
    assert [item["revision_id"] for item in manifest["variants"]] == revision_ids
    revision_id_by_platform = {item["platform"]: item["id"] for item in approved}
    expected_file_matrix = [
        (
            f"{platform}/{revision_id_by_platform[platform]}/content.{extension}",
            kind,
            platform,
            revision_id_by_platform[platform],
            None,
        )
        for platform in ("telegram", "instagram", "x", "blog")
        for kind, extension in (
            ("json", "json"),
            ("markdown", "md"),
            ("html", "html"),
        )
    ]
    assert [
        (
            item["file_name"],
            item["kind"],
            item["platform"],
            item["revision_id"],
            item["media_asset_id"],
        )
        for item in manifest["files"]
    ] == expected_file_matrix
    await app_harness.assert_export_downloads(export)

    instagram = next(item for item in approved if item["platform"] == "instagram")
    scheduled_for = datetime.now(UTC) + timedelta(hours=2)
    plan = await app_harness.create_manual_plan(
        instagram["id"],
        scheduled_for=scheduled_for,
        display_timezone="Asia/Tehran",
    )
    completed = await app_harness.complete_all_checks_and_mark_published(
        plan,
        external_url="https://www.instagram.com/p/newscraft-release/",
        note="Published manually from the approved package.",
    )
    assert completed["status"] == "manual_published"
    assert completed["platform_variant_revision_id"] == instagram["id"]
    assert completed["external_url"] == ("https://www.instagram.com/p/newscraft-release/")
    assert completed["completed_at"] is not None

    persisted = await app_harness.get_json(f"/platform-variant-revisions/{instagram['id']}/manual-publication-plan")
    assert persisted == completed

    calendar = await app_harness.calendar(
        start=scheduled_for - timedelta(hours=1),
        end=scheduled_for + timedelta(hours=1),
        display_timezone="Asia/Tehran",
    )
    assert calendar["timezone"] == "Asia/Tehran"
    assert [
        {
            "kind": item["kind"],
            "platform": item["platform"],
            "revision_id": item["revision_id"],
            "status": item["status"],
        }
        for item in calendar["items"]
    ] == [
        {
            "kind": "manual_publication",
            "platform": "instagram",
            "revision_id": instagram["id"],
            "status": "manual_published",
        }
    ]
