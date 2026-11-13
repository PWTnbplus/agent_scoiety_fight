from __future__ import annotations

import math
import re
from typing import Any

from ..simulators import predict


PREDICTION_TOLERANCE = 0.02


def public_nominal_k(target_notes: str) -> float:
    match = re.search(r"(?:Nominal candidate-rate|Target .*?candidate-rate) k=([0-9.]+)", target_notes, flags=re.IGNORECASE)
    if match is None:
        raise ValueError("public target notes do not contain a nominal candidate rate")
    return float(match.group(1))


def audit_prediction_values(view: Any, experiment_id: str | None, predicted_values: dict[str, Any] | None, *, tolerance: float = PREDICTION_TOLERANCE, nominal_k: float | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "experiment_id": experiment_id or "",
        "tolerance": float(tolerance),
        "prediction_consistency": "NOT_CHECKED",
        "prediction_max_abs_error": None,
        "prediction_errors": {},
        "prediction_error_categories": {},
        "expected_values": {},
        "missing_models": [],
        "missing_expected_models": [],
        "unknown_models": [],
        "numeric_correct_count": 0,
        "numeric_total_count": len(getattr(view, "candidate_models", ())),
    }
    if not experiment_id or not isinstance(predicted_values, dict):
        result["prediction_consistency"] = "MISSING"
        result["missing_expected_models"] = list(getattr(view, "candidate_models", ()))
        result["missing_models"] = list(getattr(view, "candidate_models", ()))
        return result
    experiment = next((item for item in view.experiments if str(item.get("experiment_id")) == str(experiment_id)), None)
    if experiment is None:
        result["prediction_consistency"] = "INVALID_EXPERIMENT"
        return result
    if nominal_k is None:
        nominal_k = public_nominal_k(view.target_notes)
    expected = {
        model: predict(model, float(experiment["x0"]), float(experiment["measure_t"]), float(nominal_k))
        for model in view.candidate_models
    }
    result["expected_values"] = expected
    errors: dict[str, float | None] = {}
    categories: dict[str, str] = {}
    for model, value in predicted_values.items():
        if model not in expected:
            errors[str(model)] = None
            categories[str(model)] = "unknown_model"
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors[model] = None
            categories[model] = "non_numeric"
            continue
        if not math.isfinite(float(value)):
            errors[model] = None
            categories[model] = "non_finite"
            continue
        errors[model] = abs(float(value) - expected[model])
        categories[model] = "pass" if errors[model] <= tolerance else "abs_error_exceeds_tolerance"
    missing_expected = [model for model in view.candidate_models if model not in predicted_values]
    for model in missing_expected:
        errors[model] = None
        categories[model] = "missing_model"
    result["prediction_errors"] = errors
    result["prediction_error_categories"] = categories
    result["missing_expected_models"] = missing_expected
    result["unknown_models"] = [model for model in predicted_values if model not in expected]
    result["missing_models"] = missing_expected + [model for model in predicted_values if model not in expected or errors.get(model) is None]
    valid_errors = [float(errors[model]) for model in view.candidate_models if errors.get(model) is not None]
    result["numeric_correct_count"] = sum(1 for model in view.candidate_models if categories.get(model) == "pass")
    result["prediction_max_abs_error"] = max(valid_errors) if valid_errors else None
    result["prediction_consistency"] = (
        "PASS" if predicted_values and not missing_expected and not result["unknown_models"] and valid_errors and len(valid_errors) == len(view.candidate_models) and max(valid_errors) <= tolerance else "FAIL"
    )
    return result
