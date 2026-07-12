from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Protocol

_SECRET_REFERENCE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")


class SecretReferenceError(ValueError):
    """Raised when a secret reference is not an allowed environment key."""

    def __init__(self) -> None:
        super().__init__("Invalid secret reference")


class SecretNotConfiguredError(LookupError):
    """Raised when a validated secret reference has no non-empty value."""

    def __init__(self, reference: str) -> None:
        self.reference = reference
        super().__init__(reference)


class SecretResolver(Protocol):
    def configured(self, reference: str) -> bool: ...

    def resolve(self, reference: str) -> str: ...


class EnvironmentSecretResolver:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    @staticmethod
    def _validate(reference: str) -> None:
        if _SECRET_REFERENCE_PATTERN.fullmatch(reference) is None:
            raise SecretReferenceError

    def configured(self, reference: str) -> bool:
        self._validate(reference)
        value = self._environ.get(reference)
        return value is not None and bool(value.strip())

    def resolve(self, reference: str) -> str:
        self._validate(reference)
        value = self._environ.get(reference)
        if value is None or not value.strip():
            raise SecretNotConfiguredError(reference)
        return value
