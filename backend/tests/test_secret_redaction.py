from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.redaction import redact_secrets, redact_url
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus


def test_recursive_redaction_covers_keys_credentials_tokens_urls_and_literals_without_mutation():
    literal = "editor-super-secret"
    source = {
        "Authorization": "Bearer abc.def",
        "nested": {
            "api_key": "key-value",
            "basic": "Basic dXNlcjpwYXNz",
            "telegram": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
            "url": "https://user:pass@example.com/path?token=visible&safe=yes",
            "literal": f"prefix {literal} suffix",
        },
        "items": ("Bearer second", {"safe": "visible"}),
    }

    redacted = redact_secrets(source, secrets=(literal,))

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert "dXNlcj" not in redacted["nested"]["basic"]
    assert "123456789:" not in redacted["nested"]["telegram"]
    assert redacted["nested"]["url"] == "https://example.com/path?token=%5BREDACTED%5D&safe=yes"
    assert literal not in redacted["nested"]["literal"]
    assert source["Authorization"] == "Bearer abc.def"
    assert source["nested"]["url"].startswith("https://user:pass@")


def test_redact_url_removes_userinfo_and_secret_query_values():
    assert redact_url("https://user:pass@example.com/a?api_key=one&q=ok") == (
        "https://example.com/a?api_key=%5BREDACTED%5D&q=ok"
    )
    assert "user:pass" not in redact_secrets(
        "failure https://user:pass@example.com/a?token=x"
    )
    assert redact_url("https://example.com:bad/a?token=x") == "[REDACTED]"


def test_redaction_is_cycle_safe_preserves_shared_refs_and_usage_metric_keys():
    shared = {"access_token": "secret", "input_tokens": 10}
    source = {
        "left": shared,
        "right": shared,
        "output_tokens": 4,
        "tokenizer_name": "safe-tokenizer",
        "session_count": 2,
    }
    source["cycle"] = source

    redacted = redact_secrets(source)

    assert redacted["left"] == redacted["right"] == {
        "access_token": "[REDACTED]",
        "input_tokens": 10,
    }
    assert redacted["output_tokens"] == 4
    assert redacted["tokenizer_name"] == "safe-tokenizer"
    assert redacted["session_count"] == 2
    assert redacted["cycle"] == "[REDACTED]"


def test_secret_key_boundaries_redact_value_suffixes_but_keep_metrics():
    source = {
        "token_value": "one",
        "api_key_value": "two",
        "input_tokens": 10,
        "output_tokens": 4,
        "token_usage": {"total": 14},
        "tokenizer_name": "safe",
        "session_count": 2,
    }
    assert redact_secrets(source) == {
        "token_value": "[REDACTED]",
        "api_key_value": "[REDACTED]",
        "input_tokens": 10,
        "output_tokens": 4,
        "token_usage": {"total": 14},
        "tokenizer_name": "safe",
        "session_count": 2,
    }


class FakeJobSession:
    def __init__(self, job):
        self.job = job
        self.added = []

    async def scalar(self, statement):
        return self.job

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


def running_job(now):
    return WorkflowJob(
        id=uuid4(),
        job_type="test",
        status=JobStatus.RUNNING,
        payload={},
        result={},
        priority=0,
        idempotency_key=str(uuid4()),
        origin=JobOrigin.AUTOMATION,
        pause_sensitive=True,
        attempt_count=1,
        max_attempts=3,
        lease_owner="worker",
        lease_expires_at=now + timedelta(minutes=1),
        progress=0,
    )


async def test_job_repository_redacts_result_and_failure_before_persistence():
    now = datetime(2026, 7, 12, tzinfo=UTC)
    succeeded = running_job(now)
    success_session = FakeJobSession(succeeded)
    await JobRepository(success_session).finish_job(
        job_id=succeeded.id,
        worker_id="worker",
        result={"nested": {"access_token": "raw-token", "safe": "visible"}},
        now=now,
    )
    assert succeeded.result == {
        "nested": {"access_token": "[REDACTED]", "safe": "visible"}
    }
    assert all(
        "raw-token" not in str(item.event_data)
        for item in success_session.added
        if isinstance(item, WorkflowEvent)
    )

    failed = running_job(now)
    failure_session = FakeJobSession(failed)
    await JobRepository(failure_session).fail_job(
        job_id=failed.id,
        worker_id="worker",
        error_class=JobErrorClass.PERMANENT,
        error_code="bad_token=raw-token",
        error_message="Bearer raw-token",
        now=now,
    )
    assert "raw-token" not in failed.error_message
    assert "raw-token" not in failed.error_code
