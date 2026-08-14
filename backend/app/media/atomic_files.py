from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write"]


def atomic_write(path: Path, content: bytes) -> None:
    """Publish `content` at `path` atomically and concurrency-safely.

    The temporary file name is unique per writer (`tempfile.mkstemp`), so two
    processes writing the same content-addressed destination never share a
    scratch path — a deterministic `<path>.tmp` lets one writer truncate the
    file another writer is about to publish. Publication uses `os.link`, which
    is atomic and refuses to clobber an existing destination: for the
    content-addressed stores that call this helper an existing file already
    holds exactly these bytes, so losing the race is success, not an error.
    """

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
