from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.automations.telegram.media import MediaLimitExceeded, TelegramMediaStore


def test_media_store_persists_by_checksum_without_duplicate_files(tmp_path):
    store = TelegramMediaStore(tmp_path, max_photo_bytes=10, max_file_bytes=20)

    first = store.persist(b"photo", mime_type="image/jpeg", file_name="source.jpg", kind="photo")
    second = store.persist(b"photo", mime_type="image/jpeg", file_name="again.jpg", kind="photo")

    assert first == second
    assert first.path.read_bytes() == b"photo"
    assert first.path.name == f"{first.checksum_sha256}.jpg"
    assert list(tmp_path.rglob(f"{first.checksum_sha256}.*")) == [first.path]


def test_media_store_rejects_oversized_file_before_persistence(tmp_path):
    store = TelegramMediaStore(tmp_path, max_photo_bytes=4, max_file_bytes=8)

    with pytest.raises(MediaLimitExceeded, match="photo exceeds 4 bytes"):
        store.persist(b"12345", mime_type="image/jpeg", file_name="big.jpg", kind="photo")

    assert list(Path(tmp_path).rglob("*.*")) == []


@pytest.mark.parametrize(
    ("mime_type", "file_name", "expected_suffix"),
    [
        ("image/jpeg", "../../escape.exe", ".jpg"),
        ("application/pdf", "/tmp/report.pdf", ".pdf"),
        ("application/octet-stream", "archive.tar.gz", ".bin"),
        ("video/mp4", None, ".mp4"),
    ],
)
def test_media_store_uses_only_allowlisted_suffixes_inside_checksum_root(
    tmp_path, mime_type, file_name, expected_suffix
):
    store = TelegramMediaStore(tmp_path / "assets", max_photo_bytes=20, max_file_bytes=20)

    stored = store.persist(b"safe", mime_type=mime_type, file_name=file_name, kind="document")

    assert stored.path.suffix == expected_suffix
    assert stored.path.resolve().is_relative_to((tmp_path / "assets").resolve())
    assert not (tmp_path / "escape.exe").exists()


def test_media_store_atomic_deduplication_leaves_no_temporary_files(tmp_path):
    store = TelegramMediaStore(tmp_path, max_photo_bytes=20, max_file_bytes=20)

    with ThreadPoolExecutor(max_workers=4) as executor:
        stored = list(
            executor.map(
                lambda _: store.persist(b"same-content", mime_type="image/png", file_name="same.png", kind="photo"),
                range(8),
            )
        )

    assert len({item.path for item in stored}) == 1
    assert stored[0].path.read_bytes() == b"same-content"
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == [stored[0].path]
