import pytest

from app.api.editorial_errors import editorial_http_error
from app.workflows.errors import (
    CapabilityUnavailableError,
    EditorialValidationError,
    InvalidProviderResultError,
    MissingEvidenceError,
    StaleRevisionError,
)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (MissingEvidenceError(), 422, "missing_evidence"),
        (StaleRevisionError(), 409, "stale_revision"),
        (InvalidProviderResultError(), 422, "invalid_provider_result"),
        (EditorialValidationError(), 422, "validation_failed"),
        (CapabilityUnavailableError(), 503, "capability_unavailable"),
    ],
)
def test_editorial_domain_failures_map_once_at_the_http_edge(error, status, code) -> None:
    response = editorial_http_error(error)

    assert response.status_code == status
    assert response.detail["code"] == code
    assert response.detail["message"] == str(error)


def test_specific_validation_reason_is_preserved_below_the_stable_category() -> None:
    response = editorial_http_error(EditorialValidationError("Citation mismatch", code="citation_integrity"))

    assert response.detail == {
        "code": "validation_failed",
        "message": "Citation mismatch",
        "reason_code": "citation_integrity",
    }
