from __future__ import annotations

import math

from mini_science.metrics.prediction_audit import audit_prediction_values
from mini_science.public_loader import load_world
from mini_science.simulators import predict


def test_numeric_audit_exposes_per_model_categories():
    view = load_world(".", "W001", worlds_subdir="worlds_v2_dev")
    item = next(item for item in view.experiments if item["experiment_id"] == "E04")
    values = {model: predict(model, float(item["x0"]), float(item["measure_t"]), 0.494) for model in view.candidate_models}
    values["EXP_DECAY"] += 0.1
    result = audit_prediction_values(view, "E04", values)
    assert result["prediction_consistency"] == "FAIL"
    assert result["prediction_error_categories"]["EXP_DECAY"] == "abs_error_exceeds_tolerance"
    assert result["prediction_error_categories"]["HYPERBOLIC_DECAY"] == "pass"
    assert result["numeric_correct_count"] == 3


def test_numeric_audit_marks_missing_unknown_and_nonfinite():
    view = load_world(".", "W001", worlds_subdir="worlds_v2_dev")
    result = audit_prediction_values(view, "E04", {"EXP_DECAY": math.nan, "UNKNOWN": 0.1})
    assert result["prediction_error_categories"]["EXP_DECAY"] == "non_finite"
    assert result["prediction_error_categories"]["UNKNOWN"] == "unknown_model"
    assert set(result["missing_expected_models"]) == set(view.candidate_models) - {"EXP_DECAY"}
