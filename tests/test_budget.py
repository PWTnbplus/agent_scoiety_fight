from __future__ import annotations

import pytest

from mini_science.adapters.base import LLMResponse
from mini_science.budget import BudgetExceeded, BudgetTracker


def test_budget_limits_calls_and_tokens():
    tracker = BudgetTracker(max_total_tokens=10, max_calls=1)
    tracker.before_call()
    tracker.record(LLMResponse("x", "mock", 3, 3, 1, 0.0))
    with pytest.raises(BudgetExceeded):
        tracker.before_call()
    assert tracker.total_tokens == 6
