from __future__ import annotations

import csv
import shutil
from pathlib import Path

from mini_science.analysis import analyze_run
from mini_science.config import load_config
from mini_science.public_loader import load_world
from mini_science.scoring import evaluate_final


SOURCE_RUN = Path("runs/real_v5p8_micro_cv001_20261113T034139Z")


def test_partial_live_run_separates_usage_reserved_and_not_evaluated(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    for name in ("results.csv", "call_ledger.jsonl", "config_frozen.json", "manifest.json"):
        shutil.copy2(SOURCE_RUN / name, run / name)
    out = tmp_path / "analysis"
    outputs = analyze_run(Path("."), run, out)

    budget = next(csv.DictReader(outputs["budget"].open(encoding="utf-8")))
    assert budget["completed_response_usage_local_estimate_usd"] == "0.00208955"
    assert budget["unknown_billable_reserved_estimate_usd"] == "0.00564535"
    assert budget["all_attempts_reserved_estimate_usd"] == "0.0112907"
    assert budget["legacy_local_estimated_cost_usd_unique_mixed_not_usage"] == "0.0077349"
    assert budget["unique_provider_tokens_completed_only"] == "1368"

    rows = list(csv.DictReader(outputs["per_condition"].open(encoding="utf-8")))
    unfinished = {row["condition"]: row for row in rows if row["condition"] != "A_TARGET_ONLY"}
    assert all(row["model_numeric_valid"] == "" for row in unfinished.values())
    assert all(row["numeric_prediction_accuracy"] == "" for row in unfinished.values())
    assert all(row["prediction_consistency"] == "NOT_EVALUATED" for row in unfinished.values())

    pairs = list(csv.DictReader(outputs["paired_effects"].open(encoding="utf-8")))
    cd = next(row for row in pairs if row["contrast"] == "C-D")
    assert cd["delta_action_only"] == ""
    assert cd["delta_strict"] == ""
    assert cd["same_stage1_artifact"] == ""
    assert "stage1_not_executed" in cd["validity_reason"]

    prediction_rows = list(csv.DictReader(outputs["prediction_errors"].open(encoding="utf-8")))
    unfinished_prediction_rows = [row for row in prediction_rows if row["condition"] != "A_TARGET_ONLY"]
    assert unfinished_prediction_rows
    assert all(row["error_category"] == "NOT_EVALUATED" for row in unfinished_prediction_rows)
    assert all(row["nearest_menu_action"] == "" for row in unfinished_prediction_rows)


def test_scoring_marks_upstream_missing_rows_as_not_evaluated():
    config = load_config("config/v5p8_four_world_two_repeats.json")
    view = load_world(".", "CV001", "related", worlds_subdir=config.worlds_subdir)
    row = evaluate_final(
        ".",
        "CV001",
        view,
        "",
        condition="D_SEQ2_BLOCK",
        provider="kimi26",
        model_snapshot="kimi-k2.6",
        replicate=0,
        input_tokens=None,
        output_tokens=None,
        api_calls=0,
        latency_ms=0,
        billed_cost=None,
        attributed_full_workflow_cost=None,
        run_status="UPSTREAM_FAIL_FAST",
        invalid_reason="UPSTREAM_FAIL_FAST",
        worlds_subdir=config.worlds_subdir,
        private_worlds_subdir=config.private_worlds_subdir,
        require_predicted_values=True,
        require_selected_action=True,
        separate_scientific_validity=True,
    )
    assert row["scientific_output_available"] is False
    assert row["action_valid"] is None
    assert row["model_numeric_valid"] is None
    assert row["fully_scientifically_valid"] is None
    assert row["prediction_consistency"] == "NOT_EVALUATED"
