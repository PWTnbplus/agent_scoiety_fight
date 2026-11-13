from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from .adapters.base import LLMResponse


class BudgetExceeded(RuntimeError):
    pass


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()), math.ceil(len(text) / 2)) if text else 0


@dataclass
class BudgetTracker:
    max_total_tokens: int
    max_calls: int
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    calls: int = 0
    final_questions: int = 0
    latency_ms: int = 0
    costs: list[float] = field(default_factory=list)
    usage_verified: bool = True
    unknown_usage_calls: int = 0
    over_budget: bool = False
    _reserved_tokens: int = 0
    _reserved_calls: int = 0

    def before_call(self, estimated_input_tokens: int = 0, max_output_tokens: int = 0) -> None:
        if self.calls + self._reserved_calls >= self.max_calls:
            raise BudgetExceeded("maximum model calls exceeded before provider request")
        estimate = max(0, int(estimated_input_tokens)) + max(0, int(max_output_tokens))
        if self.total_tokens + self._reserved_tokens + estimate > self.max_total_tokens:
            raise BudgetExceeded("maximum total tokens would be exceeded before provider request")
        self._reserved_calls += 1
        self._reserved_tokens += estimate

    def seed_usage(self, response: LLMResponse | None) -> None:
        if response is None:
            self.usage_verified = False
            self.unknown_usage_calls += 1
            self.calls += 1
            return
        self.calls += 1
        self.latency_ms += int(response.latency_ms or 0)
        if response.input_tokens is None or response.output_tokens is None:
            self.usage_verified = False
            self.unknown_usage_calls += 1
        else:
            self.total_input_tokens += int(response.input_tokens)
            self.total_output_tokens += int(response.output_tokens)
        if response.cost_usd is not None:
            self.costs.append(float(response.cost_usd))

    def record(self, response: LLMResponse) -> None:
        if self._reserved_calls:
            self._reserved_calls -= 1
        self._reserved_tokens = 0
        self.calls += 1
        if response.input_tokens is None or response.output_tokens is None:
            self.usage_verified = False
            self.unknown_usage_calls += 1
        else:
            self.total_input_tokens += int(response.input_tokens)
            self.total_output_tokens += int(response.output_tokens)
            if self.total_tokens > self.max_total_tokens:
                self.over_budget = True
                raise BudgetExceeded("provider usage exceeded maximum total tokens")
        self.latency_ms += response.latency_ms
        if response.cost_usd is not None:
            self.costs.append(float(response.cost_usd))

    def record_failure(self) -> None:
        if self._reserved_calls:
            self._reserved_calls -= 1
        self._reserved_tokens = 0
        self.usage_verified = False
        self.unknown_usage_calls += 1

    def record_final_question(self) -> None:
        self.final_questions += 1
        if self.final_questions > 1:
            raise BudgetExceeded("more than one final question produced")

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def cost_usd(self) -> float | None:
        return sum(self.costs) if self.costs else None

    @property
    def budget_verified(self) -> bool:
        return self.usage_verified and not self.over_budget and not self._reserved_calls

    def snapshot(self) -> dict[str, Any]:
        return {
            "max_total_tokens": self.max_total_tokens,
            "max_calls": self.max_calls,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "calls": self.calls,
            "cost_usd": self.cost_usd,
            "usage_verified": self.usage_verified,
            "unknown_usage_calls": self.unknown_usage_calls,
            "over_budget": self.over_budget,
            "budget_verified": self.budget_verified,
        }
