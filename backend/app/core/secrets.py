from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
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


class SecretFileSecurityError(RuntimeError):
    """Raised when a mounted secret is not a restrictive regular file."""

    def __init__(self) -> None:
        super().__init__("Secret file is unavailable")


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


class FileSecretResolver:
    """Resolve one validated reference per read from a restrictive secret mount."""

    def __init__(
        self,
        root: str | Path = "/run/secrets",
        *,
        max_bytes: int = 65_536,
        require_restrictive_permissions: bool = True,
    ) -> None:
        self._root = Path(root)
        self._max_bytes = max_bytes
        self._require_restrictive_permissions = require_restrictive_permissions

    def configured(self, reference: str) -> bool:
        try:
            self.resolve(reference)
        except SecretNotConfiguredError, SecretFileSecurityError:
            return False
        return True

    def resolve(self, reference: str) -> str:
        EnvironmentSecretResolver._validate(reference)
        path = self._root / reference
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            raise SecretNotConfiguredError(reference) from None
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise SecretFileSecurityError
            if self._require_restrictive_permissions and metadata.st_mode & 0o077:
                raise SecretFileSecurityError
            chunks: list[bytes] = []
            remaining = self._max_bytes + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(remaining, 8_192))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(descriptor)
        raw = b"".join(chunks)
        if len(raw) > self._max_bytes:
            raise SecretFileSecurityError
        try:
            value = raw.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError:
            raise SecretFileSecurityError from None
        if not value.strip():
            raise SecretNotConfiguredError(reference)
        return value


class WorkerSecretResolver:
    """Use mounted files in production and scoped environment values only locally."""

    def __init__(
        self,
        *,
        file_resolver: SecretResolver | None = None,
        environment_resolver: SecretResolver | None = None,
        allow_environment: bool,
    ) -> None:
        self._files = file_resolver or FileSecretResolver()
        self._environment = environment_resolver or EnvironmentSecretResolver()
        self._allow_environment = allow_environment

    def configured(self, reference: str) -> bool:
        try:
            self.resolve(reference)
        except SecretNotConfiguredError, SecretFileSecurityError:
            return False
        return True

    def resolve(self, reference: str) -> str:
        try:
            return self._files.resolve(reference)
        except SecretNotConfiguredError:
            if not self._allow_environment:
                raise
        return self._environment.resolve(reference)


def build_worker_secret_resolver(
    *,
    app_env: str,
    secret_root: str | Path = "/run/secrets",
    environ: Mapping[str, str] | None = None,
) -> WorkerSecretResolver:
    return WorkerSecretResolver(
        file_resolver=FileSecretResolver(secret_root),
        environment_resolver=EnvironmentSecretResolver(environ),
        allow_environment=app_env.casefold() in {"development", "local", "test"},
    )


__all__ = [
    "EnvironmentSecretResolver",
    "FileSecretResolver",
    "SecretFileSecurityError",
    "SecretNotConfiguredError",
    "SecretReferenceError",
    "SecretResolver",
    "WorkerSecretResolver",
    "build_worker_secret_resolver",
]
