from __future__ import annotations

from uuid import UUID


def _sanitize_handler_message(message: str) -> str:
    sanitized = " ".join(str(message).split())
    return (sanitized or "Job handler failed")[:500]


class JobHandlerError(RuntimeError):
    def __init__(self, *, code: str, message: str = "Job handler failed") -> None:
        self.code = str(code)
        self.message = _sanitize_handler_message(message)
        super().__init__(self.message)


class RetryableJobError(JobHandlerError):
    """A handler failure that may succeed on a later attempt."""


class NeedsReviewJobError(JobHandlerError):
    """A handler outcome requiring operator review."""


class PermanentJobError(JobHandlerError):
    """A handler failure that must not be retried automatically."""


class InvalidJobTransition(RuntimeError):
    """Raised when a workflow job cannot perform the requested state transition."""

    def __init__(self, job_id: UUID, *, action: str, status: str) -> None:
        self.job_id = job_id
        self.action = action
        self.status = status
        super().__init__(f"Job {job_id} cannot {action} from status {status}")


class UnknownJobTypeError(LookupError):
    """Raised when no handler is registered for a workflow job type."""


class DuplicateJobHandlerError(ValueError):
    """Raised when a workflow job type already has a registered handler."""
