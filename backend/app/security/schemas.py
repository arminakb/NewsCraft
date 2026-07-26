from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class SecretWriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr = Field(min_length=1, max_length=65_536)
__all__ = ["SecretWriteIn"]
