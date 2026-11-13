from __future__ import annotations

import csv
import json
from pathlib import Path

from mini_science.metrics.prediction_audit import audit_prediction_values
from mini_science.public_loader import load_world


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "v5_p1_real_w001_20261112_145649"
if not RUN.exists():
    RUN = ROOT / "evidence" / "historical_v5p1_real_w001"
OUT_DIR = ROOT / "reports" / "003_V5P2_OFFLINE_DEVELOPMENT"


def main() -> None:
    rows = list(csv.DictReader((RUN / "results.csv").open(encoding="utf-8")))
    view = load_world(ROOT, "W001", "related", worlds_subdir="worlds_v2_dev")
    failures: list[dict[str, object]] = []
    action_rows: list[dict[str, object]] = []
    for row in rows:
        predicted = json.loads(row.get("predicted_values") or "{}")
        audit = audit_prediction_values(view, row.get("experiment_id_selected"), predicted)
        for model in view.candidate_models:
            failures.append({
                "world_id": row["world_id"],
                "condition": row["condition"],
                "experiment_id": row["experiment_id_selected"],
                "model": model,
                "predicted_value": predicted.get(model),
                "expected_value": audit["expected_values"].get(model),
                "absolute_error": audit["prediction_errors"].get(model),
                "tolerance": audit["tolerance"],
                "pass": bool(audit["prediction_errors"].get(model) is not None and float(audit["prediction_errors"][model]) <= float(audit["tolerance"])),
            })
        selected = next(item for item in view.experiments if item["experiment_id"] == row["experiment_id_selected"])
        numeric_pass = audit["prediction_consistency"] == "PASS"
        stage1_gate = row["condition"] not in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"} or row.get("mapping_valid", "").lower() == "true"
        action_rows.append({
            "world_id": row["world_id"],
            "condition": row["condition"],
            "selected_action": row["experiment_id_selected"],
            "selected_x0": selected["x0"],
            "selected_measure_t": selected["measure_t"],
            "action_top1_score": row["top1_score"],
            "fixed_e04_top1_score": "",
            "numeric_prediction_consistency": audit["prediction_consistency"],
            "numeric_max_abs_error": audit["prediction_max_abs_error"],
            "numeric_pass": numeric_pass,
            "stage1_mapping_gate": stage1_gate,
            "strict_scientifically_valid": bool(numeric_pass and stage1_gate),
            "historical_valid_flag": row["valid"],
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failed_path = OUT_DIR / "FAILED_PREDICTIONS_DIAG.csv"
    with failed_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(failures[0]))
        writer.writeheader()
        writer.writerows(failures)

    by_condition = {row["condition"]: row for row in action_rows}
    def score(condition: str) -> float:
        return float(by_condition[condition]["action_top1_score"])
    fixed_e04_score = score("A_TARGET_ONLY")
    action_path = OUT_DIR / "W001_ACTION_VS_NUMERIC_TABLE.csv"
    for row in action_rows:
        row["fixed_e04_top1_score"] = fixed_e04_score
        row["action_vs_fixed_e04"] = float(row["action_top1_score"]) - fixed_e04_score
        row["B_minus_A_action"] = score("B_SINGLE_RELATED") - score("A_TARGET_ONLY") if row["condition"] == "B_SINGLE_RELATED" else ""
        row["C_minus_D_action"] = score("C_SEQ2_TRANSFER") - score("D_SEQ2_BLOCK") if row["condition"] == "C_SEQ2_TRANSFER" else ""
        row["C_minus_B_action"] = score("C_SEQ2_TRANSFER") - score("B_SINGLE_RELATED") if row["condition"] == "C_SEQ2_TRANSFER" else ""
        row["strict_pair_status"] = "PAIR_VALID" if all(bool(item["strict_scientifically_valid"]) for item in action_rows) else "PAIR_INVALID"
    with action_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(action_rows[0]))
        writer.writeheader()
        writer.writerows(action_rows)
    print(f"replayed {len(failures)} historical prediction values without API calls")


if __name__ == "__main__":
    main()
