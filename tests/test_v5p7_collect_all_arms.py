"""Ensure a scientific output error never prevents collecting the complete paired design.

The fake provider makes zero network requests. Budget, identity and authorisation
checks remain enforced by the real V5-P4 session gate.
"""
from __future__ import annotations

import csv
from pathlib import Path

from mini_science.adapters.base import LLMResponse
from mini_science.authorization import create_v5p4_authorization, V5P4_CONFIRMATION_PHRASE
from mini_science.config import load_config
from mini_science.runner import run_pilot


class UnscientificPaidFixture:
    model_name = "kimi-k2.6"
    input_cost_per_1k = 0.00095
    output_cost_per_1k = 0.004

    def __init__(self):
        self.calls = 0

    def complete(self, messages, max_output_tokens):
        self.calls += 1
        return LLMResponse(
            text="{this is intentionally invalid JSON}",
            model=self.model_name,
            input_tokens=100,
            output_tokens=60,
            latency_ms=1,
            cost_usd=0.0004,
            metadata={
                "returned_model": self.model_name,
                "usage_verified": True,
                "finish_reason": "stop",
                "provider_billing_verified": False,
            },
        )


def test_v5p4_real_runtime_collects_all_five_even_with_science_failures(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config/v5p4_offline_dev.json")
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    session = create_v5p4_authorization(
        root, config, approved_by="user_explicit",
        confirmation=V5P4_CONFIRMATION_PHRASE,
        authorization_note="offline fake-only five-arm test",
        request_plan=__import__("mini_science.budget_plan", fromlist=["pilot_request_plan"]).pilot_request_plan(root, config, worlds=["CV001"], conditions=conditions, repeats=1),
        worlds=["CV001"], conditions=conditions,
        max_unique_provider_attempts=5, max_estimated_cost_usd=0.05,
    )
    fixture = UnscientificPaidFixture()
    monkeypatch.setattr("mini_science.runner.make_adapter", lambda *args, **kwargs: fixture)
    try:
        out = run_pilot(
            root, config, provider="kimi26", worlds=["CV001"],
            conditions=conditions, repeats=1, allow_paid_api=True,
            run_dir=tmp_path / "five_calls", session_dir=session.parent,
            global_max_calls=5, global_max_cost_usd=0.05,
        )
        assert fixture.calls == 5
        with (out / "results.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 4
        assert all(str(row.get("run_status")) != "NOT_EXECUTED" for row in rows)
        assert all(str(row.get("valid")).lower() in {"false", "0"} for row in rows)
        import json
        events = [json.loads(line) for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
        assert any(item.get("event_type") == "SCIENTIFIC_OUTPUT_INVALID" for item in events)
    finally:
        # The session was created in the supplied copy of the project root.
        import shutil
        shutil.rmtree(session.parent, ignore_errors=True)
