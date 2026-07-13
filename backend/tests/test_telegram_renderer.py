from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.generation.telegram_schema import TelegramVariantContent
from app.publishing.telegram.renderer import (
    TelegramPublishNeedsReview,
    build_publish_plan,
    validate_renderability_policy,
)


def _revision(**content_overrides):
    content = {
        "body": "<b>Hello</b>",
        "parse_mode": "HTML",
        "buttons": [{"text": "Read", "url": "https://example.com/story"}],
        "source_item_id": None,
        "source_url": None,
        "media_policy": "preserve",
        "media_asset_ids": [],
        "direction": "rtl",
        "dry_run": False,
    }
    content.update(content_overrides)
    return SimpleNamespace(id=uuid4(), content=content)


def _destination():
    return SimpleNamespace(id=uuid4(), target_ref="@target", secret_ref="TELEGRAM_TOKEN")


def _media(tmp_path: Path, kind: str, index: int):
    extension = {"image": ".jpg", "video": ".mp4", "document": ".pdf"}[kind]
    path = tmp_path / f"asset-{index}{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"media-{index}".encode()
    path.write_bytes(payload)
    return SimpleNamespace(
        id=uuid4(),
        kind=kind,
        storage_path=str(path),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        fetch_status="downloaded",
        mime_type={"image": "image/jpeg", "video": "video/mp4", "document": "application/pdf"}[kind],
    )


def test_text_only_uses_send_message_and_nullable_source_identity():
    revision = _revision(source_item_id=None)

    plan = build_publish_plan(revision, [], _destination())

    assert [operation.method for operation in plan.operations] == ["sendMessage"]
    assert plan.operations[0].fields["chat_id"] == "@target"
    assert "source_item_id" not in plan.operations[0].fields


@pytest.mark.parametrize(
    ("kind", "method"),
    [("image", "sendPhoto"), ("video", "sendVideo"), ("document", "sendDocument")],
)
def test_single_media_is_reuploaded_with_caption(tmp_path: Path, kind: str, method: str):
    media = _media(tmp_path, kind, 0)
    revision = _revision(media_asset_ids=[media.id], source_item_id=uuid4())

    plan = build_publish_plan(revision, [media], _destination())

    assert [operation.method for operation in plan.operations] == [method]
    assert plan.operations[0].file_paths == (Path(media.storage_path),)
    assert plan.operations[0].fields["caption"] == "<b>Hello</b>"


def test_compatible_album_is_grouped_in_stable_groups_of_ten(tmp_path: Path):
    media = [_media(tmp_path, "image" if index % 2 == 0 else "video", index) for index in range(12)]
    revision = _revision(media_asset_ids=[item.id for item in media], buttons=[])

    plan = build_publish_plan(revision, media, _destination())

    assert [operation.method for operation in plan.operations] == ["sendMediaGroup", "sendMediaGroup"]
    assert [len(operation.file_paths) for operation in plan.operations] == [10, 2]
    assert "caption" in plan.operations[0].fields["media"][0]
    assert all("caption" not in item for item in plan.operations[1].fields["media"])
    assert [item["media"] for item in plan.operations[1].fields["media"]] == [
        "attach://file0",
        "attach://file1",
    ]


def test_group_chunk_never_contains_one_item(tmp_path: Path):
    media = [_media(tmp_path, "document", index) for index in range(11)]
    plan = build_publish_plan(_revision(media_asset_ids=[item.id for item in media], buttons=[]), media, _destination())
    assert [operation.method for operation in plan.operations] == ["sendMediaGroup", "sendDocument"]


def test_group_with_buttons_uses_captionless_media_and_one_button_message(tmp_path: Path):
    media = [_media(tmp_path, "image", index) for index in range(2)]
    plan = build_publish_plan(_revision(media_asset_ids=[item.id for item in media]), media, _destination())
    assert [operation.method for operation in plan.operations] == ["sendMediaGroup", "sendMessage"]
    assert all("caption" not in item for item in plan.operations[0].fields["media"])
    assert plan.operations[1].fields["reply_markup"]["inline_keyboard"]


def test_long_caption_sends_uncaptioned_media_then_message(tmp_path: Path):
    media = _media(tmp_path, "image", 0)
    revision = _revision(body="x" * 1025, media_asset_ids=[media.id])

    plan = build_publish_plan(revision, [media], _destination())

    assert [operation.method for operation in plan.operations] == ["sendPhoto", "sendMessage"]
    assert "caption" not in plan.operations[0].fields
    assert plan.operations[1].fields["text"] == "x" * 1025


def test_body_over_telegram_limit_fails_shared_schema_validation():
    with pytest.raises(ValidationError):
        build_publish_plan(_revision(body="x" * 4097), [], _destination())


def test_media_policies_fail_closed(tmp_path: Path):
    media = _media(tmp_path, "image", 0)
    omitted = build_publish_plan(_revision(media_policy="omit", media_asset_ids=[media.id]), [media], _destination())
    assert [operation.method for operation in omitted.operations] == ["sendMessage"]

    with pytest.raises(TelegramPublishNeedsReview, match="replace_manually"):
        build_publish_plan(
            _revision(media_policy="replace_manually", media_asset_ids=[media.id]), [media], _destination()
        )


def test_pure_renderability_policy_matches_build_plan_without_media_rows():
    for media_policy in ("omit", "preserve"):
        validate_renderability_policy(
            TelegramVariantContent.model_validate(_revision(media_policy=media_policy).content)
        )

    with pytest.raises(TelegramPublishNeedsReview, match="replace_manually"):
        validate_renderability_policy(
            TelegramVariantContent.model_validate(_revision(media_policy="replace_manually").content)
        )


def test_mixed_documents_and_visual_media_require_review(tmp_path: Path):
    media = [_media(tmp_path, "document", 0), _media(tmp_path, "video", 1)]
    with pytest.raises(TelegramPublishNeedsReview, match="mixed"):
        build_publish_plan(_revision(media_asset_ids=[item.id for item in media]), media, _destination())


def test_plan_hashes_are_deterministic_and_contain_no_sensitive_or_absolute_values(tmp_path: Path):
    media = [_media(tmp_path, "image", 0), _media(tmp_path, "video", 1)]
    revision = _revision(media_asset_ids=[item.id for item in media], source_item_id=uuid4())
    destination = _destination()

    first = build_publish_plan(revision, media, destination)
    second = build_publish_plan(revision, list(reversed(media)), destination)

    assert first.payload_hash == second.payload_hash
    assert [item.key for item in first.operations] == [item.key for item in second.operations]
    assert [item.request_hash for item in first.operations] == [item.request_hash for item in second.operations]
    hashable_fields = repr([item.fields for item in first.operations])
    assert destination.secret_ref not in hashable_fields
    assert str(tmp_path) not in hashable_fields


def test_missing_or_mismatched_media_requires_review(tmp_path: Path):
    media = _media(tmp_path, "image", 0)
    with pytest.raises(TelegramPublishNeedsReview, match="media"):
        build_publish_plan(_revision(media_asset_ids=[uuid4()]), [media], _destination())


def test_media_must_be_downloaded_unique_and_checksum_verified(tmp_path: Path):
    media = _media(tmp_path, "image", 0)
    revision = _revision(media_asset_ids=[media.id])
    media.checksum_sha256 = None
    with pytest.raises(TelegramPublishNeedsReview, match="checksum"):
        build_publish_plan(revision, [media], _destination())
    media.checksum_sha256 = "f" * 64
    with pytest.raises(TelegramPublishNeedsReview, match="checksum"):
        build_publish_plan(revision, [media], _destination())
    media.checksum_sha256 = hashlib.sha256(Path(media.storage_path).read_bytes()).hexdigest()
    media.fetch_status = "failed"
    with pytest.raises(TelegramPublishNeedsReview, match="downloaded"):
        build_publish_plan(revision, [media], _destination())
    media.fetch_status = "downloaded"
    with pytest.raises(TelegramPublishNeedsReview, match="media"):
        build_publish_plan(revision, [media, media], _destination())


def test_hashes_ignore_storage_root_for_identical_bytes(tmp_path: Path):
    first = _media(tmp_path / "one", "image", 0)
    second = _media(tmp_path / "two", "image", 0)
    second.id = first.id
    revision = _revision(media_asset_ids=[first.id])
    destination = _destination()
    assert build_publish_plan(revision, [first], destination).payload_hash == build_publish_plan(
        revision, [second], destination
    ).payload_hash


def test_wire_mime_and_extension_are_validated_and_hashed(tmp_path: Path):
    first = _media(tmp_path, "image", 0)
    revision = _revision(media_asset_ids=[first.id])
    jpeg = build_publish_plan(revision, [first], _destination())
    assert jpeg.operations[0].uploads[0].filename == "upload-0.jpg"
    assert jpeg.operations[0].uploads[0].mime_type == "image/jpeg"

    png_path = Path(first.storage_path).with_suffix(".png")
    png_path.write_bytes(Path(first.storage_path).read_bytes())
    first.storage_path = str(png_path)
    first.mime_type = "image/png"
    png = build_publish_plan(revision, [first], _destination())
    assert png.operations[0].request_hash != jpeg.operations[0].request_hash
    assert png.payload_hash != jpeg.payload_hash

    first.mime_type = "image/jpeg"
    with pytest.raises(TelegramPublishNeedsReview, match="MIME"):
        build_publish_plan(revision, [first], _destination())


def test_file_read_errors_do_not_expose_absolute_paths(tmp_path: Path, monkeypatch):
    media = _media(tmp_path, "image", 0)
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError(f"failed: {self}")))
    with pytest.raises(TelegramPublishNeedsReview) as caught:
        build_publish_plan(_revision(media_asset_ids=[media.id]), [media], _destination())
    assert str(tmp_path) not in str(caught.value)
    assert caught.value.__cause__ is None
