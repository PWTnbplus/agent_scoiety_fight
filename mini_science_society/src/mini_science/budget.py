from __future__ import annotations

from dataclasses import dataclass, field

from .adapters.base import LLMResponse


class BudgetExceeded(RuntimeError):
    pass


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

    def before_call(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded("maximum model calls exceeded")

    def record(self, response: LLMResponse) -> None:
        input_tokens = response.input_tokens or 0
        output_tokens = response.output_tokens or 0
        if self.total_input_tokens + self.total_output_tokens + input_tokens + output_tokens > self.max_total_tokens:
            raise BudgetExceeded("maximum total tokens exceeded after provider response")
        self.calls += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.latency_ms += response.latency_ms
        if response.cost_usd is not None:
            self.costs.append(float(response.cost_usd))

    def record_final_question(self) -> None:
        self.final_questions += 1
        if self.final_questions > 1:
            raise BudgetExceeded("more than one final question produced")

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def cost_usd(self) -> float | None:
        return sum(self.costs) if self.costs else (0.0 if self.calls else None)
