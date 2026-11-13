from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from mini_science.config import load_config
from mini_science.metrics.prediction_audit import public_nominal_k
from mini_science.public_loader import load_world
from mini_science.simulators import predict


ROOT = Path(__file__).resolve().parents[1]
TOLERANCE = 0.02


def historical_text(condition: str, field: str) -> str:
    path = ROOT / "runs" / "real_kimi26_w001_v3_01" / "agent_artifacts" / "W001" / "replicate_0" / condition / ("stage1.json" if condition == "C_SEQ2_TRANSFER" else "final.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    if condition == "C_SEQ2_TRANSFER":
        return str(value.get("raw_text", ""))
    return str(value.get("raw_text", ""))


def claims(text: str, aliases: dict[str, tuple[str, ...]]) -> dict[str, float]:
    found: dict[str, float] = {}
    for model, names in aliases.items():
        pattern = r"(?:" + "|".join(re.escape(name) for name in names) + r")(?:\s*[:=])?\s*(?:≈|~|about|approximately)?\s*([0-9]+(?:\.[0-9]+)?)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            found[model] = float(match.group(1))
    return found


def main() -> None:
    config = load_config(ROOT / "config" / "pilot_v2.json")
    view = load_world(ROOT, "W001", "related", worlds_subdir=config.worlds_subdir)
    k = public_nominal_k(view.target_notes)
    aliases = {"EXP_DECAY": ("EXP_DECAY", "EXP"), "HYPERBOLIC_DECAY": ("HYPERBOLIC_DECAY", "HYPERBOLIC"), "STRETCHED_EXP": ("STRETCHED_EXP", "STRETCHED"), "BI_EXP": ("BI_EXP", "BI_EXP")}
    cases = [("V3_G3_stage1", "C_SEQ2_TRANSFER", "E01"), ("V3_G3_B", "B_SINGLE_RELATED", "E04")]
    rows: list[dict[str, object]] = []
    for source, condition, experiment_id in cases:
        text = historical_text(condition, "raw_text")
        value = next(item for item in view.experiments if item["experiment_id"] == experiment_id)
        expected = {model: predict(model, float(value["x0"]), float(value["measure_t"]), k) for model in view.candidate_models}
        claimed = claims(text, aliases)
        for model in view.candidate_models:
            error = abs(claimed[model] - expected[model]) if model in claimed else None
            rows.append({"source": source, "condition": condition, "experiment_id": experiment_id, "model": model, "public_nominal_k": k, "expected_public_prediction": expected[model], "claimed_prediction": claimed.get(model, ""), "absolute_error": error if error is not None else "", "tolerance": TOLERANCE, "consistent_with_public_equation": bool(error is not None and error <= TOLERANCE)})
    destination = ROOT / "reports" / "v4_preflight" / "PREDICTION_NUMERIC_AUDIT.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(destination)


if __name__ == "__main__":
    main()
