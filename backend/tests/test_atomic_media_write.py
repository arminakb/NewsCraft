from __future__ import annotations

import os
import threading
from pathlib import Path

from app.media.atomic_files import atomic_write


def test_scratch_file_is_not_a_deterministic_sibling_of_the_destination(tmp_path: Path) -> None:
    """Two writers of the same content-addressed path must not share a scratch file.

    The historical implementation used `<path>.tmp`, a pure function of the
    destination, so concurrent downloads of identical bytes collided on one
    temporary file and could publish a half-written image.
    """

    destination = tmp_path / "ab" / "cafe.jpg"
    observed: list[str] = []
    real_link = os.link

    def recording_link(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        observed.append(str(source))
        real_link(source, target)

    original = os.link
    os.link = recording_link  # type: ignore[assignment]
    try:
        atomic_write(destination, b"\xff\xd8payload")
    finally:
        os.link = original  # type: ignore[assignment]

    assert destination.read_bytes() == b"\xff\xd8payload"
    assert observed, "the helper must publish through a scratch file"
    assert observed[0] != f"{destination}.tmp"
    assert list(destination.parent.glob("*.tmp")) == []


def test_concurrent_writers_of_one_destination_all_publish_intact_content(tmp_path: Path) -> None:
    destination = tmp_path / "ab" / "cafe.png"
    content = b"\x89PNG\r\n\x1a\n" + b"x" * 200_000
    writers = 8
    start = threading.Barrier(writers)
    failures: list[BaseException] = []

    def writer() -> None:
        try:
            start.wait(timeout=10)
            atomic_write(destination, content)
        except BaseException as error:  # noqa: BLE001 - recorded and re-raised by the assertion
            failures.append(error)

    threads = [threading.Thread(target=writer) for _ in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert failures == []
    assert destination.read_bytes() == content
    assert list(destination.parent.glob("*.tmp")) == []


def test_existing_destination_is_left_untouched(tmp_path: Path) -> None:
    destination = tmp_path / "ab" / "cafe.gif"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"GIF89a-original")

    atomic_write(destination, b"GIF89a-original")

    assert destination.read_bytes() == b"GIF89a-original"
    assert list(destination.parent.glob("*.tmp")) == []
