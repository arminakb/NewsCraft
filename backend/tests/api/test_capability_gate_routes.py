from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.jobs.errors import JobCapabilityUnavailable
from app.main import job_capability_unavailable


def test_capability_gate_503_is_stable_retryable_and_sanitized():
    api = FastAPI()
    api.add_exception_handler(JobCapabilityUnavailable, job_capability_unavailable)

    @api.post("/enqueue")
    async def enqueue():
        raise JobCapabilityUnavailable(
            code="secret_ref_OPENROUTER_API_KEY",
            job_type="OPENROUTER_API_KEY",
            retry_after_seconds=7,
        )

    with TestClient(api) as client:
        response = client.post("/enqueue")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "7"
    assert response.json() == {
        "detail": {
            "code": "job_capability_unknown",
            "job_type": "unknown",
            "retry_after_seconds": 7,
        }
    }
    assert "OPENROUTER" not in response.text
