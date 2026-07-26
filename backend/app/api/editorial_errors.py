from fastapi import HTTPException

from app.workflows.errors import EditorialWorkflowError

_STATUS_BY_CATEGORY = {
    "missing_evidence": 422,
    "stale_revision": 409,
    "invalid_provider_result": 422,
    "validation_failed": 422,
    "capability_unavailable": 503,
}


def editorial_http_error(exc: EditorialWorkflowError) -> HTTPException:
    detail = {
        "code": exc.category,
        "message": str(exc),
    }
    if exc.code != exc.category:
        detail["reason_code"] = exc.code
    return HTTPException(_STATUS_BY_CATEGORY[exc.category], detail)
