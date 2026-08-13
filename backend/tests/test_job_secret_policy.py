from __future__ import annotations

import pytest

from app.jobs.repository import _redact_job_payload
from app.jobs.secret_policy import restore_exempt_secrets
from app.jobs.types import _reject_secret_payload

_TOKEN = "a" * 64
_MALFORMED = "not-a-preview-token"


def test_retention_preview_token_survives_both_paths() -> None:
    payload = {"retention_run_id": "run", "preview_token": _TOKEN}

    _reject_secret_payload("execute_retention", dict(payload))
    assert _redact_job_payload("execute_retention", dict(payload))["preview_token"] == _TOKEN


def test_preview_token_is_not_exempt_for_other_job_types() -> None:
    payload = {"preview_token": _TOKEN}

    with pytest.raises(ValueError):
        _reject_secret_payload("telegram.publish", dict(payload))
    assert _redact_job_payload("telegram.publish", dict(payload))["preview_token"] != _TOKEN


def test_malformed_preview_tokens_are_not_exempt() -> None:
    payload = {"preview_token": _MALFORMED}

    with pytest.raises(ValueError):
        _reject_secret_payload("execute_retention", dict(payload))
    assert _redact_job_payload("execute_retention", dict(payload))["preview_token"] != _MALFORMED


@pytest.mark.parametrize(
    ("job_type", "token"),
    [
        ("execute_retention", _TOKEN),
        ("execute_retention", _MALFORMED),
        ("telegram.publish", _TOKEN),
        ("automation.run.start", _MALFORMED),
    ],
)
def test_validation_and_write_paths_share_one_exemption(job_type: str, token: str) -> None:
    """Both paths must agree, because both delegate to the same policy."""

    payload = {"preview_token": token}
    from_validation = restore_exempt_secrets(job_type, payload, {"preview_token": "***"})
    from_write = restore_exempt_secrets(job_type, payload, {"preview_token": "***"})
    assert from_validation == from_write
    exempt = from_write["preview_token"] == token
    assert exempt is (job_type == "execute_retention" and token == _TOKEN)
