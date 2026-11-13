from __future__ import annotations

import math


MODELS = ("EXP_DECAY", "HYPERBOLIC_DECAY", "STRETCHED_EXP", "BI_EXP")


def predict(model: str, x0: float, t: float, k: float) -> float:
    """Predict a nonnegative synthetic state; this is not a domain law claim."""
    if x0 <= 0 or t < 0 or k <= 0:
        raise ValueError("require x0>0, t>=0 and k>0")
    if model == "EXP_DECAY":
        value = x0 * math.exp(-k * t)
    elif model == "HYPERBOLIC_DECAY":
        value = x0 / (1.0 + k * x0 * t)
    elif model == "STRETCHED_EXP":
        value = x0 * math.exp(-(k * t) ** 2)
    elif model == "BI_EXP":
        value = x0 * (0.75 * math.exp(-1.8 * k * t) + 0.25 * math.exp(-0.25 * k * t))
    else:
        raise ValueError(f"unknown candidate model: {model}")
    if not math.isfinite(value) or value < 0:
        raise ArithmeticError("model prediction must be finite and nonnegative")
    return value
