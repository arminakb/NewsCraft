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


class JobType(StrEnum):
    MANUAL_INTAKE = "manual_intake"
    STORY_GROUP_PENDING = "story.group_pending"
    RESEARCH_STORY = "research_story"
    TELEGRAM_ROUTE_INITIALIZE = "telegram.route.initialize"
    TELEGRAM_ROUTE_POLL = "telegram.route.poll"
    TELEGRAM_ROUTE_BACKFILL = "telegram.route.backfill"
    TELEGRAM_ROUTE_DRY_RUN = "telegram.route.dry_run"
    TELEGRAM_ROUTE_PROCESS = "telegram.route.process"
    TELEGRAM_DESTINATION_CHECK = "telegram.destination.check"
    TELEGRAM_PUBLISH = "telegram.publish"
