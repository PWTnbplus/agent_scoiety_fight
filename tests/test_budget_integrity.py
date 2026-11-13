from __future__ import annotations

import json

import pytest

from mini_science.adapters.base import LLMResponse
from mini_science.budget import BudgetExceeded, BudgetTracker
from mini_science.config import load_config
from mini_science.runner import run_pilot
from mini_science.worldgen import generate_worlds


def test_pre_call_budget_blocks_impossible_next_call():
    tracker = BudgetTracker(max_total_tokens=6500, max_calls=3)
    tracker.before_call(estimated_input_tokens=4000, max_output_tokens=2500)
    tracker.record(LLMResponse("x", "fixture", 4000, 2500, 1, None))
    with pytest.raises(BudgetExceeded):
        tracker.before_call(1, 1)


def test_missing_usage_is_unverified_and_not_zero_billed():
    tracker = BudgetTracker(max_total_tokens=6500, max_calls=3)
    tracker.before_call(10, 10)
    tracker.record(LLMResponse("x", "fixture", None, None, 1, None))
    assert tracker.usage_verified is False
    assert tracker.budget_verified is False
    assert tracker.cost_usd is None


def test_cd_shared_stage1_is_one_unique_pair_call_and_two_workflow_calls(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    run_dir = run_pilot(tmp_path, config, provider="behavioral-mock", behavioral_scenario="constant", worlds=["W001"], conditions=["C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=1)
    calls = [json.loads(line) for line in (run_dir / "call_ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(calls) == 3
    assert sum(record["stage"] == "stage1" for record in calls) == 1
    rows = list(__import__("csv").DictReader((run_dir / "results.csv").open(encoding="utf-8")))
    assert {row["full_workflow_calls"] for row in rows} == {"2"}
