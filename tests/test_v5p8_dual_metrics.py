from __future__ import annotations

import csv
import json

import pytest

from mini_science.analysis import analyze_run, paired_metrics, write_comparisons


def _row(condition: str, *, world: str = "CV001", replicate: int = 0, action: float = 80.0, strict: bool = False, artifact: str = ""):
    return {
        "world_id": world,
        "replicate": str(replicate),
        "condition": condition,
        "model_snapshot": "kimi-k2.6",
        "config_hash": "config",
        "pair_id": f"{world}_R{replicate}",
        "action_valid": "True",
        "top1_action_score": str(action),
        "fully_scientifically_valid": str(strict),
        "top1_score": str(action if strict else 0.0),
        "proposal_valid": "True",
        "prediction_errors": json.dumps({"EXP_DECAY": 0.0 if strict else 0.1}),
        "prediction_max_abs_error": "0.0" if strict else "0.1",
        "ig_selected_action": "0.2",
        "experiment_id_selected": "E04",
        "selected_action": json.dumps({"experiment_id": "E04", "x0": 0.7, "measure_t": 2.6}),
        "candidate_law_id": "",
        "stage1_artifact_sha256": artifact,
        "forwarded_artifact_sha256": artifact,
        "stage1_transfer_eligible": "True",
        "route_intervention": "",
        "prediction_consistency": "PASS" if strict else "FAIL",
        "model_numeric_valid": str(strict),
        "input_tokens": "1",
        "output_tokens": "1",
        "full_workflow_tokens": "2",
        "unique_provider_calls": "1",
        "estimated_cost_usd": "0.001",
        "provider_billed_cost_usd": "",
    }


def test_action_only_is_available_when_strict_pair_is_undefined():
    result = paired_metrics(_row("B_SINGLE_RELATED", action=70), _row("A_TARGET_ONLY", action=50))
    assert result["delta_action_only"] == 20
    assert result["delta_strict"] is None
    assert result["action_pair_eligible"] is True
    assert result["strict_pair_eligible"] is False


def test_cd_requires_same_stage1_artifact():
    result = paired_metrics(_row("C_SEQ2_TRANSFER", strict=True, artifact="a"), _row("D_SEQ2_BLOCK", strict=True, artifact="b"))
    assert result["same_stage1_artifact"] is False
    assert result["strict_pair_eligible"] is False
    assert "stage1_artifact_mismatch" in result["exclusion_reason"]


def test_write_comparisons_keeps_legacy_strict_and_new_action_columns(tmp_path):
    path = write_comparisons(tmp_path, [_row("A_TARGET_ONLY", action=50), _row("B_SINGLE_RELATED", action=70)])
    row = next(csv.DictReader(path.open(encoding="utf-8")))
    assert row["B_minus_A"] == ""
    assert row["B_minus_A_action_only"] == "20.0"
    assert row["B_minus_A_strict"] == ""


def test_analyze_run_rejects_missing_required_columns(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "results.csv").write_text("world_id,condition\nCV001,A_TARGET_ONLY\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required analysis columns"):
        analyze_run(tmp_path, run, tmp_path / "analysis")


def test_different_repeat_or_world_never_pairs(tmp_path):
    rows = [_row("A_TARGET_ONLY", world="CV001", replicate=0), _row("B_SINGLE_RELATED", world="CV001", replicate=1), _row("C_SEQ2_TRANSFER", world="CV002"), _row("D_SEQ2_BLOCK", world="CV002")]
    path = write_comparisons(tmp_path, rows)
    records = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(records) == 3
    assert all(item["B_minus_A_action_only"] == "" for item in records if item["world_id"] == "CV001")
