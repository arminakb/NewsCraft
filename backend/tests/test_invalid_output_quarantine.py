import os
from datetime import UTC, datetime, timedelta

import pytest

from app.generation.invalid_output_quarantine import AgeInvalidOutputQuarantine


@pytest.fixture(autouse=True)
def execute_thread_work_inline(monkeypatch):
    calls = []

    async def to_thread(function, *args, **kwargs):
        calls.append(function)
        return function(*args, **kwargs)

    monkeypatch.setattr("app.generation.invalid_output_quarantine.asyncio.to_thread", to_thread)
    return calls


async def test_age_quarantine_writes_only_ciphertext_and_prunes_expired_artifacts(
    tmp_path, monkeypatch, execute_thread_work_inline
):
    recipient = tmp_path / "recipient.txt"
    recipient.write_text("age1testrecipient", encoding="utf-8")
    root = tmp_path / "quarantine"
    old = root / "old.age"
    root.mkdir()
    old.write_bytes(b"old-ciphertext")
    old_time = (datetime.now(UTC) - timedelta(days=8)).timestamp()
    os.utime(old, (old_time, old_time))

    class Process:
        returncode = 0

        def __init__(self, output):
            self.output = output

        async def communicate(self, content):
            self.output.write_bytes(b"encrypted:" + content[::-1])
            return b"", b""

    async def create_process(*arguments, **kwargs):
        output = arguments[arguments.index("--output") + 1]
        return Process(__import__("pathlib").Path(output))

    monkeypatch.setattr("app.generation.invalid_output_quarantine.shutil.which", lambda value: "/usr/bin/age")
    monkeypatch.setattr(
        "app.generation.invalid_output_quarantine.asyncio.create_subprocess_exec",
        create_process,
    )
    quarantine = AgeInvalidOutputQuarantine(
        root=root,
        recipient_file=recipient,
        max_bytes=100,
        ttl_days=7,
    )

    await quarantine.store(b"private-plaintext", stage="schema", response_sha256="a" * 64)

    artifacts = list(root.glob("*.age"))
    assert len(artifacts) == 1
    assert artifacts[0].read_bytes() == b"encrypted:" + b"private-plaintext"[::-1]
    assert artifacts[0].stat().st_mode & 0o777 == 0o600
    assert not old.exists()
    assert not any(path.read_bytes() == b"private-plaintext" for path in root.iterdir())
    assert len(execute_thread_work_inline) == 3


async def test_age_quarantine_skips_oversized_content_before_process_start(tmp_path, monkeypatch):
    recipient = tmp_path / "recipient.txt"
    recipient.write_text("age1testrecipient", encoding="utf-8")
    monkeypatch.setattr("app.generation.invalid_output_quarantine.shutil.which", lambda value: "/usr/bin/age")
    quarantine = AgeInvalidOutputQuarantine(
        root=tmp_path / "quarantine",
        recipient_file=recipient,
        max_bytes=4,
        ttl_days=7,
    )

    await quarantine.store(b"oversized", stage="schema", response_sha256="a" * 64)

    assert not quarantine.root.exists()
