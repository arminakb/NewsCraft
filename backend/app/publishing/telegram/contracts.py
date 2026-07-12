from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

TelegramMethod = Literal["sendMessage", "sendPhoto", "sendVideo", "sendDocument", "sendMediaGroup"]


@dataclass(frozen=True, slots=True)
class TelegramUploadMetadata:
    attach_name: str
    filename: str
    mime_type: str
    media_type: Literal["photo", "video", "document"]
    checksum_sha256: str


@dataclass(frozen=True, slots=True)
class TelegramPublishOperation:
    index: int
    key: str
    method: TelegramMethod
    fields: dict[str, Any]
    file_paths: tuple[Path, ...] = field(repr=False)
    request_hash: str
    uploads: tuple[TelegramUploadMetadata, ...] = ()


@dataclass(frozen=True, slots=True)
class TelegramPublishPlan:
    destination_id: UUID
    revision_id: UUID
    payload_hash: str
    operations: tuple[TelegramPublishOperation, ...]


@dataclass(frozen=True, slots=True)
class TelegramOperationResult:
    remote_message_ids: tuple[int, ...]
    response_metadata: dict[str, Any]
