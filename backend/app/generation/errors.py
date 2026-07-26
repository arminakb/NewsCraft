from app.workflows.errors import EditorialValidationError, StaleRevisionError


class InvalidGenerationRequest(EditorialValidationError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message, code=code)


class RevisionConflict(StaleRevisionError):
    pass
