from __future__ import annotations

import csv
import json

from mini_science.analysis_v5p11 import analyze_v5p11_run, write_not_run_analysis


def test_v5p11_not_run_is_not_scientifically_valid(tmp_path):
    output = tmp_path / "not_run"
    write_not_run_analysis(".", "config/v5p11_main.json", output)
    summary = json.loads((output / "overall_summary.json").read_text(encoding="utf-8"))
    assert summary["result_rows"] == 0
    assert summary["completed_scientific_rows"] == 0
    assert summary["strict_scientific_valid_rate"]["n"] == 0
    assert (output / "paired_deltas_action.csv").read_text(encoding="utf-8").startswith("world_id")


def test_v5p11_mock_analysis_has_eight_action_pairs(tmp_path):
    output = tmp_path / "mock_analysis"
    analyze_v5p11_run(".", "config/v5p11_main.json", "runs/mock_v5p11_cv001_cv004_20261113T", output, real_status="NON_EVIDENCE")
    rows = (output / "paired_deltas_action.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + 8 * 3
    assert all("UNDEFINED" not in row for row in rows[1:])


def test_v5p11_analysis_writes_real_baseline_rows_and_diagnostics(tmp_path):
    output = tmp_path / "mock_with_baselines"
    analyze_v5p11_run(".", "config/v5p11_main.json", "runs/mock_v5p11_cv001_cv004_20261113T", output, real_status="NON_EVIDENCE")
    rows = list(csv.DictReader((output / "baseline_comparison.csv").open(encoding="utf-8")))
    assert len(rows) == 20 * 2 + 32
    assert {row["method"] for row in rows if row["method"].startswith("REAL_AGENT_")} == {"REAL_AGENT_A_TARGET_ONLY", "REAL_AGENT_B_SINGLE_RELATED", "REAL_AGENT_C_SEQ2_TRANSFER", "REAL_AGENT_D_SEQ2_BLOCK"}
    assert "SEE_REPORT_BASELINES" not in (output / "baseline_comparison.csv").read_text(encoding="utf-8")
    result_rows = list(csv.DictReader((output / "results_raw.csv").open(encoding="utf-8")))
    assert all(row["scientific_diagnostic_reason"] for row in result_rows)
