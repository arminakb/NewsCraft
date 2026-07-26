from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


class InvalidOutputQuarantineError(RuntimeError):
    pass


class AgeInvalidOutputQuarantine:
    """Encrypt invalid provider bytes directly from memory; never persist plaintext."""

    def __init__(
        self,
        *,
        root: str | Path,
        recipient_file: str | Path,
        max_bytes: int,
        ttl_days: int,
        age_executable: str = "age",
    ) -> None:
        if not 1 <= ttl_days <= 7 or max_bytes < 1:
            raise ValueError("invalid quarantine bounds")
        executable = shutil.which(age_executable)
        if executable is None:
            raise InvalidOutputQuarantineError("age executable is unavailable")
        self.root = Path(root)
        self.recipient_file = Path(recipient_file)
        self.max_bytes = max_bytes
        self.ttl = timedelta(days=ttl_days)
        self.age_executable = executable

    async def store(self, content: bytes, *, stage: str, response_sha256: str) -> None:
        if len(content) > self.max_bytes:
            logger.warning(
                "invalid provider output quarantine skipped stage=%s response_sha256=%s reason=size_limit",
                stage,
                response_sha256,
            )
            return
        if not self.recipient_file.is_file():
            raise InvalidOutputQuarantineError("age recipient file is unavailable")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        await self.prune()
        artifact_id = uuid4().hex
        temporary = self.root / f".{artifact_id}.age.tmp"
        destination = self.root / f"{artifact_id}.age"
        process = await asyncio.create_subprocess_exec(
            self.age_executable,
            "--recipients-file",
            str(self.recipient_file),
            "--output",
            str(temporary),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        _stdout, _stderr = await process.communicate(content)
        if process.returncode != 0:
            temporary.unlink(missing_ok=True)
            raise InvalidOutputQuarantineError("invalid output encryption failed")
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
        logger.warning(
            "invalid provider output quarantined artifact_id=%s stage=%s response_sha256=%s",
            artifact_id,
            stage,
            response_sha256,
        )

    async def prune(self, *, now: datetime | None = None) -> None:
        if not self.root.exists():
            return
        cutoff = (now or datetime.now(UTC)).timestamp() - self.ttl.total_seconds()
        for path in self.root.glob("*.age"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except FileNotFoundError:
                continue


__all__ = ["AgeInvalidOutputQuarantine", "InvalidOutputQuarantineError"]
