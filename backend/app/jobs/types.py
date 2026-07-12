from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"


class JobErrorClass(StrEnum):
    RETRYABLE = "retryable"
    NEEDS_REVIEW = "needs_review"
    PERMANENT = "permanent"


class JobOrigin(StrEnum):
    MANUAL = "manual"
    SCHEDULER = "scheduler"
    AUTOMATION = "automation"
    RETRY = "retry"
