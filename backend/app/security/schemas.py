from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class SecretWriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr = Field(min_length=1, max_length=65_536)


class SecretMetadataOut(BaseModel):
    configured: bool = True
    last_rotated_at: datetime


__all__ = ["SecretMetadataOut", "SecretWriteIn"]
