from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class GenerationProviderRequest:
    run_id: UUID
    purpose: str
    requested_model: str | None
    messages: tuple[ProviderMessage, ...]
    response_schema: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GenerationProviderResult:
    provider: str
    requested_model: str | None
    resolved_model: str
    output: dict[str, Any]
    raw_text: str
    usage: dict[str, Any]
    finish_reason: str | None


class GenerationProvider(Protocol):
    provider_name: str

    async def generate(self, request: GenerationProviderRequest) -> GenerationProviderResult: ...
