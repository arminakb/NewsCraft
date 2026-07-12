from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

_ALLOWED_EXTENSIONS = {
    ".jpg",
    ".png",
    ".gif",
    ".webp",
    ".mp4",
    ".mov",
    ".pdf",
    ".doc",
    ".docx",
    ".zip",
    ".bin",
}
_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/zip": ".zip",
}


class MediaLimitExceeded(ValueError):
    """Raised before media exceeding its configured hard limit is stored."""


@dataclass(frozen=True, slots=True)
class StoredTelegramMedia:
    path: Path
    byte_length: int
    checksum_sha256: str
    mime_type: str
    kind: str


class TelegramMediaStore:
    def __init__(self, root: Path, *, max_photo_bytes: int, max_file_bytes: int) -> None:
        if max_photo_bytes < 0 or max_file_bytes < 0:
            raise ValueError("media byte limits must be non-negative")
        self.root = Path(root)
        self.max_photo_bytes = max_photo_bytes
        self.max_file_bytes = max_file_bytes

    def persist(
        self,
        content: bytes,
        *,
        mime_type: str,
        file_name: str | None,
        kind: str,
    ) -> StoredTelegramMedia:
        limit = self.max_photo_bytes if kind == "photo" else self.max_file_bytes
        if len(content) > limit:
            raise MediaLimitExceeded(f"{kind} exceeds {limit} bytes")

        checksum = sha256(content).hexdigest()
        extension = safe_extension(mime_type, file_name)
        root = self.root.resolve()
        path = root / checksum[:2] / f"{checksum}{extension}"
        if not path.resolve().is_relative_to(root):  # pragma: no cover - checksum path is defensive by design
            raise ValueError("media storage path escaped configured root")
        if not path.exists():
            _atomic_write(path, content)
        return StoredTelegramMedia(
            path=path,
            byte_length=len(content),
            checksum_sha256=checksum,
            mime_type=mime_type,
            kind=kind,
        )


def safe_extension(mime_type: str, file_name: str | None) -> str:
    suffix = Path(file_name or "").suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    expected = _MIME_EXTENSIONS.get(mime_type.lower())
    if expected is not None:
        return expected
    return suffix if suffix in _ALLOWED_EXTENSIONS else ".bin"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
