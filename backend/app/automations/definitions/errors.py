from __future__ import annotations


class AutomationDefinitionError(RuntimeError):
    def __init__(self, code: str, status_code: int, message: str) -> None:
        self.code = code
        self.status_code = status_code
        self.safe_message = message
        super().__init__(message)


__all__ = ["AutomationDefinitionError"]
