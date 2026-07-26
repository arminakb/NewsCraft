from __future__ import annotations

from typing import Literal

EditorialErrorCode = Literal[
    "missing_evidence",
    "stale_revision",
    "invalid_provider_result",
    "validation_failed",
    "capability_unavailable",
]


class EditorialWorkflowError(ValueError):
    """Stable domain failure exposed by research and generation operations."""

    def __init__(
        self,
        message: str,
        *,
        category: EditorialErrorCode,
        code: str | None = None,
    ) -> None:
        self.category = category
        self.code = code or category
        super().__init__(message)


class MissingEvidenceError(EditorialWorkflowError):
    def __init__(self, message: str = "Persisted story evidence is required") -> None:
        super().__init__(message, category="missing_evidence")


class StaleRevisionError(EditorialWorkflowError):
    def __init__(self, message: str = "The revision is no longer current") -> None:
        super().__init__(message, category="stale_revision")


class InvalidProviderResultError(EditorialWorkflowError):
    def __init__(
        self,
        message: str = "The provider returned an invalid result",
        *,
        code: str | None = None,
    ) -> None:
        super().__init__(message, category="invalid_provider_result", code=code)


class EditorialValidationError(EditorialWorkflowError):
    def __init__(
        self,
        message: str = "Editorial validation failed",
        *,
        code: str | None = None,
    ) -> None:
        super().__init__(message, category="validation_failed", code=code)


class CapabilityUnavailableError(EditorialWorkflowError):
    def __init__(self, message: str = "The required capability is unavailable") -> None:
        super().__init__(message, category="capability_unavailable")
