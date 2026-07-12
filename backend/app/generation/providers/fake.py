from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.generation.providers.base import GenerationProviderRequest, GenerationProviderResult


class DeterministicFakeProvider:
    provider_name = "fake"

    def __init__(
        self,
        *,
        output: Mapping[str, Any] | None = None,
        resolved_model: str = "fake-v1",
    ) -> None:
        self._output = deepcopy(dict(output)) if output is not None else {"status": "ok"}
        self._resolved_model = resolved_model

    async def generate(self, request: GenerationProviderRequest) -> GenerationProviderResult:
        output = deepcopy(self._output)
        return GenerationProviderResult(
            provider=self.provider_name,
            requested_model=request.requested_model,
            resolved_model=self._resolved_model,
            output=output,
            raw_text=json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0},
            finish_reason="stop",
        )
