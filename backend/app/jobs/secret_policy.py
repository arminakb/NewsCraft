"""Single owner of the job-payload secret carve-outs.

Job payloads are redacted with :func:`app.core.redaction.redact_secrets` on
both the validation path (accept/reject an enqueue) and the write path (the
payload actually persisted). A very small number of opaque, server-generated
capabilities must survive that redaction because their handler cannot run
without them. Encoding that carve-out twice let the two paths drift, so both
call the helper below instead.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_RETENTION_JOB_TYPE = "execute_retention"
_RETENTION_PREVIEW_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def restore_exempt_secrets(
    job_type: str,
    payload: Mapping[str, Any],
    sanitized: dict[str, Any],
) -> dict[str, Any]:
    """Re-insert the redaction exemptions ``job_type`` is entitled to.

    ``sanitized`` is mutated in place and returned. Only the retention
    handler's ``preview_token`` is exempt, and only when it looks like the
    opaque server-generated capability it is meant to be, so the same key
    stays secret in every other job contract.
    """

    if job_type != _RETENTION_JOB_TYPE:
        return sanitized
    preview_token = payload.get("preview_token")
    if isinstance(preview_token, str) and _RETENTION_PREVIEW_TOKEN_PATTERN.fullmatch(preview_token):
        sanitized["preview_token"] = preview_token
    return sanitized
