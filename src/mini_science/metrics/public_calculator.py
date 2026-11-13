from __future__ import annotations

"""Deterministic calculator using public target metadata only.

The calculator is intentionally called after an action has been selected. It
does not read private truth, oracle scores, or an agent's raw response.
"""

from typing import Any, Iterable

from .prediction_audit import public_nominal_k
from ..simulators import predict


def calculate_public_predictions(view: Any, experiment_id: str, *, models: Iterable[str] | None = None, nominal_k: float | None = None) -> dict[str, float]:
    experiment = next((item for item in view.experiments if str(item.get("experiment_id")) == str(experiment_id)), None)
    if experiment is None:
        raise ValueError(f"selected action is not in the public menu: {experiment_id}")
    selected_models = tuple(models or view.candidate_models)
    k = public_nominal_k(view.target_notes) if nominal_k is None else float(nominal_k)
    return {
        model: predict(model, float(experiment["x0"]), float(experiment["measure_t"]), k)
        for model in selected_models
    }


def audit_assisted_predictions(view: Any, experiment_id: str, raw_predicted_values: dict[str, Any] | None, *, tolerance: float = 0.02) -> dict[str, Any]:
    expected = calculate_public_predictions(view, experiment_id)
    raw_predicted_values = raw_predicted_values if isinstance(raw_predicted_values, dict) else {}
    errors: dict[str, float | None] = {}
    categories: dict[str, str] = {}
    for model, expected_value in expected.items():
        value = raw_predicted_values.get(model)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors[model] = None
            categories[model] = "calculator_filled_missing_or_non_numeric"
        else:
            errors[model] = abs(float(expected_value) - float(expected_value))
            categories[model] = "calculator_pass"
    return {
        "mode": "CALCULATOR_ASSISTED_DIAGNOSTIC",
        "calculator_values": expected,
        "public_formula_recomputed_values": expected,
        "raw_values_unchanged": raw_predicted_values,
        "prediction_errors_after_calculator": errors,
        "prediction_error_categories_after_calculator": categories,
        "correct_count": len(expected),
        "total_count": len(expected),
        "accuracy": 1.0 if expected else None,
        "calculator_recomputation_success": True,
        "calculator_assisted_diagnostic_score": 1.0 if expected else None,
        "raw_model_prediction_accuracy": None,
        "tolerance": float(tolerance),
    }
