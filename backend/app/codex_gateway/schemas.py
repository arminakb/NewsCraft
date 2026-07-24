from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.security.scopes import ALL_SCOPES

READ_ONLY_SCOPES = tuple(sorted(scope for scope in ALL_SCOPES if scope.endswith(":read")))


def _validated_scopes(values: list[str]) -> list[str]:
    normalized = sorted({value.strip().casefold() for value in values if value.strip()})
    if set(normalized) - ALL_SCOPES:
        raise ValueError("unsupported Codex scope")
    return normalized


class PairingSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: list(READ_ONLY_SCOPES), max_length=32)
    confirm_write_scopes: bool = False

    @field_validator("device_name")
    @classmethod
    def normalize_device_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("device_name is required")
        return value

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, values: list[str]) -> list[str]:
        return _validated_scopes(values)

    @model_validator(mode="after")
    def require_write_confirmation(self) -> PairingSessionCreate:
        if any(scope.endswith(":write") for scope in self.scopes) and not self.confirm_write_scopes:
            raise ValueError("write scopes require explicit confirmation")
        return self


class PairingSessionOut(BaseModel):
    id: UUID
    device_name: str
    scopes: list[str]
    status: Literal["pending", "paired", "cancelled", "expired"]
    expires_at: datetime
    created_at: datetime


class PairingSessionCreatedOut(PairingSessionOut):
    pairing_code: str
    local_command: str


class PairingExchangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pairing_code: SecretStr


class CodexConnectionOut(BaseModel):
    id: UUID
    device_name: str
    credential_fingerprint: str
    scopes: list[str]
    status: Literal["green", "yellow", "gray", "red"]
    connection_state: Literal["active", "revoked"]
    failure_code: str | None
    created_at: datetime
    expires_at: datetime
    last_heartbeat_at: datetime | None
    last_rotated_at: datetime | None
    revoked_at: datetime | None


class CredentialIssuedOut(BaseModel):
    connection: CodexConnectionOut
    credential: str


class ConnectionScopesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scopes: list[str] = Field(max_length=32)
    confirm_write_scopes: bool = False

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, values: list[str]) -> list[str]:
        return _validated_scopes(values)

    @model_validator(mode="after")
    def require_write_confirmation(self) -> ConnectionScopesPatch:
        if any(scope.endswith(":write") for scope in self.scopes) and not self.confirm_write_scopes:
            raise ValueError("write scopes require explicit confirmation")
        return self


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_version: str | None = Field(default=None, max_length=80)

    @field_validator("agent_version")
    @classmethod
    def normalize_agent_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


class HeartbeatOut(BaseModel):
    connection_id: UUID
    status: Literal["green", "yellow", "gray", "red"]
    server_time: datetime
    next_heartbeat_seconds: int


class CapabilityOut(BaseModel):
    name: str
    required_scope: str | None
    granted: bool
    risk: Literal["read_only", "write", "high_risk"]


class GatewayActivityOut(BaseModel):
    id: UUID
    connection_id: str | None
    action: str
    outcome: str
    reason_code: str | None
    created_at: datetime


__all__ = [
    "CapabilityOut",
    "CodexConnectionOut",
    "ConnectionScopesPatch",
    "CredentialIssuedOut",
    "GatewayActivityOut",
    "HeartbeatIn",
    "HeartbeatOut",
    "PairingExchangeIn",
    "PairingSessionCreate",
    "PairingSessionCreatedOut",
    "PairingSessionOut",
    "READ_ONLY_SCOPES",
]
