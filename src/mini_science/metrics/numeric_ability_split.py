from __future__ import annotations

"""Separate raw Agent arithmetic from post-selection calculator assistance."""

from typing import Any

from .public_calculator import audit_assisted_predictions
from .prediction_audit import audit_prediction_values


def split_numeric_ability(view: Any, experiment_id: str, raw_predicted_values: dict[str, Any] | None, *, tolerance: float = 0.02) -> dict[str, Any]:
    raw = audit_prediction_values(view, experiment_id, raw_predicted_values, tolerance=tolerance)
    assisted = audit_assisted_predictions(view, experiment_id, raw_predicted_values, tolerance=tolerance)
    return {
        "raw_agent": {
            "mode": "RAW_AGENT",
            "values": raw_predicted_values if isinstance(raw_predicted_values, dict) else {},
            "correct_count": raw.get("numeric_correct_count"),
            "total_count": raw.get("numeric_total_count"),
            "accuracy": (raw.get("numeric_correct_count") / raw.get("numeric_total_count") if raw.get("numeric_total_count") else None),
            "prediction_consistency": raw.get("prediction_consistency"),
            "prediction_errors": raw.get("prediction_errors", {}),
        },
        "assisted_calculator": {
            **assisted,
            "raw_model_prediction_accuracy": (raw.get("numeric_correct_count") / raw.get("numeric_total_count") if raw.get("numeric_total_count") else None),
            "calculator_recomputation_success": bool(assisted.get("calculator_recomputation_success", False)),
            "calculator_assisted_diagnostic_score": assisted.get("calculator_assisted_diagnostic_score", assisted.get("accuracy")),
        },
    }
