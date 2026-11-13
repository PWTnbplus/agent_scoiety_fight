from pathlib import Path

from mini_science.analysis_v5p11 import (
    assisted_diagnostic_eligible,
    calculate_assisted_diagnostic_delta,
    calculate_assisted_scientific_delta,
    calculate_strict_raw_delta,
    provider_billing_summary,
)
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.authorization import proposed_v5p11_authorization
from mini_science.metrics.numeric_ability_split import split_numeric_ability
from mini_science.public_loader import load_world
from mini_science.runner import _should_write_legacy_g3_report


ROOT = Path(__file__).resolve().parents[1]


def _action_row(*, condition="A_TARGET_ONLY", score=91.0, calc=1.0, stage1=True, mapping=True):
    return {
        "run_status": "COMPLETED",
        "scientific_output_available": True,
        "experiment_id_selected": "E08",
        "condition": condition,
        "action_valid": True,
        "schema_valid": True,
        "evidence_valid": True,
        "stage1_valid": stage1,
        "mapping_valid": mapping,
        "top1_action_score": score,
        "top1_score": 0.0,
        "fully_scientifically_valid": False,
        "calculator_recomputation_success": True,
        "calculator_assisted_diagnostic_score": calc,
        "assisted_calculator_accuracy": calc,
    }


def test_assisted_diagnostic_uses_action_score_not_raw_gated_top1_score():
    left = _action_row(score=91.0)
    right = _action_row(score=73.0)
    result = calculate_assisted_diagnostic_delta(left, right)
    assert result["delta"] == 18.0
    assert result["metric_mode"] == "CALCULATOR_ASSISTED_DIAGNOSTIC"


def test_strict_raw_remains_undefined_for_raw_invalid_rows():
    result = calculate_strict_raw_delta(_action_row(score=91.0), _action_row(score=73.0))
    assert result["delta"] is None
    assert result["status"] == "UNDEFINED"


def test_assisted_action_diagnostic_can_be_shown_when_stage1_science_is_invalid():
    left = _action_row(condition="C_SEQ2_TRANSFER", score=91.0, stage1=True, mapping=False)
    right = _action_row(condition="D_SEQ2_BLOCK", score=73.0, stage1=True, mapping=False)
    assert assisted_diagnostic_eligible(left)
    assert calculate_assisted_diagnostic_delta(left, right)["delta"] == 18.0
    assert calculate_assisted_scientific_delta(left, right)["delta"] is None


def test_calculator_fields_are_explicit_and_raw_values_unchanged():
    config = load_config(ROOT / "config" / "v5p11_main.json")
    view = load_world(ROOT, "IV002", "related", worlds_subdir=config.worlds_subdir)
    result = split_numeric_ability(view, "E08", {})["assisted_calculator"]
    assert result["raw_values_unchanged"] == {}
    assert result["calculator_recomputation_success"] is True
    assert result["calculator_assisted_diagnostic_score"] == 1.0
    assert result["raw_model_prediction_accuracy"] == 0.0


def test_partial_provider_billing_is_not_verified():
    result = provider_billing_summary([
        {"provider_billed_cost_usd": 0.01},
        {"provider_billed_cost_usd": None},
    ])
    assert result["provider_billing_verified"] is False
    assert result["provider_billing_coverage"] == 0.5
    assert result["provider_billed_cost_usd"] is None


def test_v5p13_r2_r3_plan_is_ten_unique_requests_and_two_shared_stage1_calls():
    config = load_config(ROOT / "config" / "v5p11_main.json")
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    plan = pilot_request_plan(ROOT, config, worlds=["IV002"], conditions=conditions, repeats=4, replicate_indices=[2, 3], request_namespace="V5P13IV002R23")
    assert len(plan) == 10
    assert len({row["request_id"] for row in plan}) == 10
    assert {row["replicate"] for row in plan} == {2, 3}
    assert sum(row["stage"] == "stage1" for row in plan) == 2
    assert sum(row["estimated_cost_usd"] for row in plan) < 0.15


def test_v5p13_proposal_binds_followup_scope_and_cap():
    config = load_config(ROOT / "config" / "v5p11_main.json")
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    plan = pilot_request_plan(ROOT, config, worlds=["IV002"], conditions=conditions, repeats=4, replicate_indices=[2, 3], request_namespace="V5P13IV002R23")
    proposal = proposed_v5p11_authorization(ROOT, config, request_plan=plan, worlds=["IV002"], conditions=conditions, repeats=4, request_namespace="V5P13IV002R23", max_unique_provider_attempts=10, max_estimated_cost_usd=0.15)
    assert proposal["protocol_variant"] == "v5p13_iv002_followup"
    assert proposal["request_ids"] == [row["request_id"] for row in plan]


def test_v5_contract_does_not_write_legacy_v3_report():
    config = load_config(ROOT / "config" / "v5p11_main.json")
    assert _should_write_legacy_g3_report(config, "kimi26") is False
