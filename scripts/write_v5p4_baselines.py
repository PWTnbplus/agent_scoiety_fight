from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from mini_science.ig_oracle import oracle_scores
from mini_science.simulators import predict


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "data" / "worlds_v5p4_dev" / "CV001"
PRIVATE = ROOT / "private" / "worlds_v5p4_dev" / "CV001"
OUT = ROOT / "reports" / "005_V5P4_READY_FOR_AUTH" / "CV001_BASELINES.csv"


def target_records(text: str) -> list[dict[str, float]]:
    pattern = re.compile(r"x0=([0-9.]+), t=([0-9.]+), measured_state=([0-9.]+)")
    return [{"x0": float(x0), "t": float(t), "observed_x": float(value)} for x0, t, value in pattern.findall(text)]


def main() -> None:
    manifest = json.loads((PUBLIC / "manifest.json").read_text(encoding="utf-8"))
    truth = json.loads((PRIVATE / "hidden_truth.json").read_text(encoding="utf-8"))
    menu = json.loads((PUBLIC / "candidate_experiments.json").read_text(encoding="utf-8"))["experiments"]
    target = target_records((PUBLIC / "target_notes.md").read_text(encoding="utf-8"))
    k = float(truth["true_k"])
    sigma = float(manifest["measurement_sigma"])
    rows: list[dict[str, object]] = []
    for grid in (501, 1001, 2001):
        audit = oracle_scores(target, menu, k, sigma, n_grid=grid)
        best = audit["best_experiment_ids"][0]
        max_time = max(menu, key=lambda item: float(item["measure_t"]))["experiment_id"]
        gaps = {
            str(item["experiment_id"]): (max(predict(model, float(item["x0"]), float(item["measure_t"]), k) for model in manifest["candidate_models"]) - min(predict(model, float(item["x0"]), float(item["measure_t"]), k) for model in manifest["candidate_models"])) / sigma
            for item in menu
        }
        simple = max(gaps, key=gaps.get)
        rows.extend([
            {"metric": "oracle", "grid": grid, "selected_experiment": best, "score": round(float(audit["top1_score"][best]), 9), "reference": "oracle top-1 IG/IG*"},
            {"metric": "fixed_E04", "grid": grid, "selected_experiment": "E04", "score": round(float(audit["top1_score"]["E04"]), 9), "reference": "strong cheap fixed baseline"},
            {"metric": "max_time", "grid": grid, "selected_experiment": max_time, "score": round(float(audit["top1_score"][max_time]), 9), "reference": "max measure_t"},
            {"metric": "simple_nominal_gap", "grid": grid, "selected_experiment": simple, "score": round(float(audit["top1_score"][simple]), 9), "reference": "largest nominal candidate gap"},
            {"metric": "random_mean", "grid": grid, "selected_experiment": "RANDOM_MEAN", "score": round(sum(float(value) for value in audit["top1_score"].values()) / len(audit["top1_score"]), 9), "reference": "uniform mean over eight legal actions"},
        ])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(OUT)


if __name__ == "__main__":
    main()
