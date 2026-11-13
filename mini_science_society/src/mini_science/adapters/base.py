from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    cost_usd: float | None = None
    raw_response_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter:
    model_name = "unknown"

    def complete(self, messages: list[dict[str, str]], max_output_tokens: int) -> LLMResponse:
        raise NotImplementedError

    def audit_trace(self) -> list[dict[str, Any]]:
        return []
