from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.generation.telegram_schema import TelegramVariantContent
from app.publishing.telegram.contracts import (
    TelegramMethod,
    TelegramPublishOperation,
    TelegramPublishPlan,
    TelegramUploadMetadata,
)

_CAPTION_LIMIT = 1024
_GROUP_LIMIT = 10
_MEDIA_TYPES = {"image": "photo", "photo": "photo", "video": "video", "document": "document"}
_SINGLE_METHODS: dict[str, TelegramMethod] = {
    "photo": "sendPhoto",
    "video": "sendVideo",
    "document": "sendDocument",
}
_UPLOAD_FORMATS: dict[tuple[str, str], tuple[set[str], str]] = {
    ("photo", "image/jpeg"): ({".jpg", ".jpeg"}, ".jpg"),
    ("photo", "image/png"): ({".png"}, ".png"),
    ("photo", "image/gif"): ({".gif"}, ".gif"),
    ("photo", "image/webp"): ({".webp"}, ".webp"),
    ("video", "video/mp4"): ({".mp4"}, ".mp4"),
    ("video", "video/quicktime"): ({".mov"}, ".mov"),
    ("document", "application/pdf"): ({".pdf"}, ".pdf"),
    ("document", "application/msword"): ({".doc"}, ".doc"),
    (
        "document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ): ({".docx"}, ".docx"),
    ("document", "application/zip"): ({".zip"}, ".zip"),
    ("document", "application/octet-stream"): ({".bin"}, ".bin"),
}


class TelegramPublishNeedsReview(ValueError):
    """Raised when a revision cannot be rendered without an operator decision."""


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _buttons(content: TelegramVariantContent) -> dict[str, Any] | None:
    if not content.buttons:
        return None
    return {
        "inline_keyboard": [
            [{"text": button.text, "url": str(button.url)}]
            for button in content.buttons
        ]
    }


def _ordered_media(content: TelegramVariantContent, media: Iterable[Any]) -> list[Any]:
    items = list(media)
    requested_ids = list(content.media_asset_ids)
    by_id = {item.id: item for item in items}
    if (
        len(by_id) != len(items)
        or len(set(requested_ids)) != len(requested_ids)
        or len(by_id) != len(requested_ids)
        or set(by_id) != set(requested_ids)
    ):
        raise TelegramPublishNeedsReview("revision media assets are missing or mismatched")
    return [by_id[media_id] for media_id in content.media_asset_ids]


def _media_descriptor(item: Any, attach_index: int) -> tuple[dict[str, str], Path]:
    kind = _MEDIA_TYPES.get(str(item.kind).lower())
    if kind is None:
        raise TelegramPublishNeedsReview(f"unsupported media kind: {item.kind}")
    if not item.storage_path:
        raise TelegramPublishNeedsReview("media asset has no local storage path")
    path = Path(item.storage_path)
    if getattr(item, "fetch_status", None) != "downloaded":
        raise TelegramPublishNeedsReview("media asset is not downloaded")
    if not isinstance(getattr(item, "checksum_sha256", None), str):
        raise TelegramPublishNeedsReview("media asset has no verified checksum")
    if not path.is_file():
        raise TelegramPublishNeedsReview("media asset is not a readable regular file")
    mime_type = str(getattr(item, "mime_type", "")).casefold()
    upload_format = _UPLOAD_FORMATS.get((kind, mime_type))
    if upload_format is None or path.suffix.casefold() not in upload_format[0]:
        raise TelegramPublishNeedsReview("media MIME, kind, and storage extension do not agree")
    try:
        content = path.read_bytes()
    except OSError:
        raise TelegramPublishNeedsReview("media asset is not readable") from None
    checksum = hashlib.sha256(content).hexdigest()
    if item.checksum_sha256 != checksum:
        raise TelegramPublishNeedsReview("media asset checksum mismatch")
    descriptor = {
        "type": kind,
        "media": f"attach://file{attach_index}",
        "checksum_sha256": checksum,
        "mime_type": mime_type,
        "filename": f"upload-{attach_index}{upload_format[1]}",
    }
    return descriptor, path


def _hashable_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return fields


def _operation(
    index: int,
    method: TelegramMethod,
    fields: dict[str, Any],
    files: list[tuple[dict[str, str], Path]],
) -> TelegramPublishOperation:
    file_hashes = [
        {
            "attach": descriptor["media"],
            "filename": descriptor["filename"],
            "kind": descriptor["type"],
            "mime_type": descriptor["mime_type"],
            "sha256": descriptor["checksum_sha256"],
        }
        for descriptor, _ in files
    ]
    request_hash = _canonical_hash({"method": method, "fields": _hashable_fields(fields), "files": file_hashes})
    return TelegramPublishOperation(
        index=index,
        key=f"telegram:{index}:{request_hash[:24]}",
        method=method,
        fields=fields,
        file_paths=tuple(path for _, path in files),
        request_hash=request_hash,
        uploads=tuple(
            TelegramUploadMetadata(
                attach_name=descriptor["media"].removeprefix("attach://"),
                filename=descriptor["filename"],
                mime_type=descriptor["mime_type"],
                media_type=descriptor["type"],
                checksum_sha256=descriptor["checksum_sha256"],
            )
            for descriptor, _ in files
        ),
    )


def _message_fields(content: TelegramVariantContent, target_ref: str) -> dict[str, Any]:
    fields: dict[str, Any] = {"chat_id": target_ref, "text": content.body, "parse_mode": content.parse_mode}
    markup = _buttons(content)
    if markup is not None:
        fields["reply_markup"] = markup
    return fields


def _single_media_fields(
    content: TelegramVariantContent,
    target_ref: str,
    descriptor: dict[str, str],
    *,
    caption: bool,
) -> dict[str, Any]:
    kind = descriptor["type"]
    fields: dict[str, Any] = {"chat_id": target_ref, kind: descriptor["media"], "parse_mode": content.parse_mode}
    if caption:
        fields["caption"] = content.body
        markup = _buttons(content)
        if markup is not None:
            fields["reply_markup"] = markup
    return fields


def _render_media(
    content: TelegramVariantContent,
    ordered_media: list[Any],
    target_ref: str,
) -> list[tuple[TelegramMethod, dict[str, Any], list[tuple[dict[str, str], Path]]]]:
    files = [_media_descriptor(item, index) for index, item in enumerate(ordered_media)]
    kinds = {descriptor["type"] for descriptor, _ in files}
    if "document" in kinds and len(kinds) > 1:
        raise TelegramPublishNeedsReview("mixed documents and photo/video media require review")
    use_caption = len(content.body) <= _CAPTION_LIMIT
    rendered: list[tuple[TelegramMethod, dict[str, Any], list[tuple[dict[str, str], Path]]]] = []
    force_message = len(files) > 1 and bool(content.buttons)
    if len(files) == 1:
        descriptor, _ = files[0]
        rendered.append(
            (
                _SINGLE_METHODS[descriptor["type"]],
                _single_media_fields(content, target_ref, descriptor, caption=use_caption),
                files,
            )
        )
    else:
        for start in range(0, len(files), _GROUP_LIMIT):
            group = files[start : start + _GROUP_LIMIT]
            group = [
                (
                    {
                        **descriptor,
                        "media": f"attach://file{offset}",
                        "filename": f"upload-{offset}{Path(descriptor['filename']).suffix}",
                    },
                    path,
                )
                for offset, (descriptor, path) in enumerate(group)
            ]
            if len(group) == 1:
                descriptor, _ = group[0]
                rendered.append(
                    (
                        _SINGLE_METHODS[descriptor["type"]],
                        _single_media_fields(
                            content,
                            target_ref,
                            descriptor,
                            caption=use_caption and start == 0 and not force_message,
                        ),
                        group,
                    )
                )
                continue
            media_fields: list[dict[str, Any]] = []
            for offset, (descriptor, _) in enumerate(group):
                item = {"type": descriptor["type"], "media": descriptor["media"]}
                if use_caption and start == 0 and offset == 0 and not force_message:
                    item.update({"caption": content.body, "parse_mode": content.parse_mode})
                media_fields.append(item)
            rendered.append(("sendMediaGroup", {"chat_id": target_ref, "media": media_fields}, group))
    if not use_caption or force_message:
        rendered.append(("sendMessage", _message_fields(content, target_ref), []))
    return rendered


def build_publish_plan(revision: Any, media: Iterable[Any], destination: Any) -> TelegramPublishPlan:
    """Build an idempotent, secret-free operation plan for one approved revision."""

    content = TelegramVariantContent.model_validate(revision.content)
    if content.media_policy == "replace_manually":
        raise TelegramPublishNeedsReview("replace_manually revisions cannot be rendered")

    rendered: list[tuple[TelegramMethod, dict[str, Any], list[tuple[dict[str, str], Path]]]]
    if content.media_policy == "omit" or not content.media_asset_ids:
        rendered = [("sendMessage", _message_fields(content, destination.target_ref), [])]
    else:
        ordered = _ordered_media(content, media)
        rendered = _render_media(content, ordered, destination.target_ref)

    operations = tuple(
        _operation(index, method, fields, files)
        for index, (method, fields, files) in enumerate(rendered)
    )
    payload_hash = _canonical_hash(
        {
            "destination_id": str(destination.id),
            "revision_id": str(revision.id),
            "operations": [
                {"index": operation.index, "key": operation.key, "request_hash": operation.request_hash}
                for operation in operations
            ],
        }
    )
    return TelegramPublishPlan(destination.id, revision.id, payload_hash, operations)
