from __future__ import annotations

from uuid import UUID


class InvalidJobTransition(RuntimeError):
    """Raised when a workflow job cannot perform the requested state transition."""

    def __init__(self, job_id: UUID, *, action: str, status: str) -> None:
        self.job_id = job_id
        self.action = action
        self.status = status
        super().__init__(f"Job {job_id} cannot {action} from status {status}")
