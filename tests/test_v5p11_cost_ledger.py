from __future__ import annotations

import csv

from mini_science.analysis_v5p11 import write_not_run_analysis


def test_v5p11_not_run_cost_ledger_does_not_mix_reserve_and_usage(tmp_path):
    output = tmp_path / "not_run"
    write_not_run_analysis(".", "config/v5p11_main.json", output)
    rows = list(csv.DictReader((output / "cost_provider_ledger.csv").open(encoding="utf-8")))
    assert rows[0]["status"] == "NOT_RUN"
    assert rows[0]["reserved_estimate_usd"] == ""
    assert rows[0]["usage_estimate_usd"] == ""
    assert rows[0]["provider_billed_cost_usd"] == ""
