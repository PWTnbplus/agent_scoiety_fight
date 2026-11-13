from __future__ import annotations

import csv
import json
from pathlib import Path

from mini_science.ig_oracle import oracle_scores
from mini_science.simulators import predict


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT / "data" / "worlds_v5p2_dev"
PRIVATE_ROOT = ROOT / "private" / "worlds_v5p2_dev"
OUT = ROOT / "reports" / "003_V5P2_OFFLINE_DEVELOPMENT" / "WORLD_DIFFICULTY_AUDIT.csv"


def records_for_world(world_id: str) -> dict[str, object]:
    public = PUBLIC_ROOT / world_id
    private = PRIVATE_ROOT / world_id
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    truth = json.loads((private / "hidden_truth.json").read_text(encoding="utf-8"))
    oracle = json.loads((private / "oracle_results.json").read_text(encoding="utf-8"))
    menu = json.loads((public / "candidate_experiments.json").read_text(encoding="utf-8"))["experiments"]
    notes = (public / "target_notes.md").read_text(encoding="utf-8")
    observations = []
    for line in notes.splitlines():
        if "measured_state=" not in line:
            continue
        parts = line.split(":", 1)[1].replace(" ", "").split(",")
        values = {item.split("=", 1)[0]: item.split("=", 1)[1] for item in parts if "=" in item}
        observations.append({"x0": float(values["x0"]), "t": float(values["t"]), "observed_x": float(values["measured_state"])})
    audit = oracle_scores(observations, menu, float(truth["true_k"]), float(manifest["measurement_sigma"]), n_grid=1001)
    best = audit["best_experiment_ids"][0]
    fixed_e04 = float(audit["top1_score"].get("E04", 0.0))
    max_time = max(menu, key=lambda item: float(item["measure_t"]))["experiment_id"]
    max_x0 = max(menu, key=lambda item: float(item["x0"]))["experiment_id"]
    nominal_k = float(manifest["nominal_k"])
    nominal_gap = {
        str(item["experiment_id"]): (
            max(predict(model, float(item["x0"]), float(item["measure_t"]), nominal_k) for model in manifest["candidate_models"])
            - min(predict(model, float(item["x0"]), float(item["measure_t"]), nominal_k) for model in manifest["candidate_models"])
        ) / float(manifest["measurement_sigma"])
        for item in menu
    }
    simple_rule = max(nominal_gap, key=nominal_gap.get)
    random_mean = sum(float(value) for value in audit["top1_score"].values()) / len(audit["top1_score"])
    oracle_score = float(audit["top1_score"][best])
    return {
        "world_id": world_id,
        "law_family": truth["true_law"],
        "family_group": manifest["family_group"],
        "independent_theory_family": manifest["independent_theory_family"],
        "source_label": manifest["source_label"],
        "oracle_best_experiment": best,
        "oracle_top1_score": round(oracle_score, 6),
        "fixed_e04_score": round(fixed_e04, 6),
        "fixed_e04_shortfall": round(oracle_score - fixed_e04, 6),
        "max_time_experiment": max_time,
        "max_time_score": round(float(audit["top1_score"][max_time]), 6),
        "max_x0_experiment": max_x0,
        "max_x0_score": round(float(audit["top1_score"][max_x0]), 6),
        "simple_nominal_gap_experiment": simple_rule,
        "simple_nominal_gap_score": round(float(audit["top1_score"][simple_rule]), 6),
        "random_mean_score": round(random_mean, 6),
        "oracle_gap_vs_best_cheap": round(oracle_score - max(fixed_e04, float(audit["top1_score"][max_time]), float(audit["top1_score"][simple_rule])), 6),
        "best_is_fixed_e04": best == "E04",
        "best_is_max_time": best == max_time,
        "source_information_gain_status": "NOT_CAUSALLY_ESTIMATED_PUBLIC_NOTE_ONLY",
        "source_does_not_change_target_oracle": True,
    }


def main() -> None:
    worlds = sorted(path.name for path in PUBLIC_ROOT.iterdir() if path.is_dir())
    rows = [records_for_world(world_id) for world_id in worlds]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    best_ids = {str(row["oracle_best_experiment"]) for row in rows}
    if len(best_ids) < 2:
        raise SystemExit("difficulty audit failed: fewer than two distinct oracle-best actions")
    if all(bool(row["best_is_max_time"]) for row in rows):
        raise SystemExit("difficulty audit failed: all worlds reduce to max-time shortcut")
    print(f"audited {len(rows)} worlds; distinct oracle-best actions={sorted(best_ids)}")


if __name__ == "__main__":
    main()
