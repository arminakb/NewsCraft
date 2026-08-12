from __future__ import annotations


class AutomationDefinitionError(RuntimeError):
    def __init__(
        self,
        code: str,
        status_code: int,
        message: str,
        *,
        node_id: str | None = None,
        node_type: str | None = None,
        field_path: str | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.safe_message = message
        self.node_id = node_id
        self.node_type = node_type
        self.field_path = field_path
        super().__init__(message)


__all__ = ["AutomationDefinitionError"]
