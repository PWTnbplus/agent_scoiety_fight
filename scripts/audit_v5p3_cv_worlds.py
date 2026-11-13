from __future__ import annotations

import csv
import argparse
import json
import math
import re
from pathlib import Path

from mini_science.ig_oracle import entropy, oracle_scores, target_posterior
from mini_science.simulators import predict


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT / "data" / "worlds_v5p3_dev"
PRIVATE_ROOT = ROOT / "private" / "worlds_v5p3_dev"
OUT = ROOT / "reports" / "004_V5P3_OFFLINE_AND_AUTH_REQUEST"


def target_records(text: str) -> list[dict[str, float]]:
    pattern = re.compile(r"x0=([0-9.]+), t=([0-9.]+), measured_state=([0-9.]+)")
    return [{"x0": float(x0), "t": float(t), "observed_x": float(value)} for x0, t, value in pattern.findall(text)]


def source_records(text: str, manifest: dict) -> list[dict[str, float]]:
    if "source_concentration" in text:
        pattern = re.compile(r"source_concentration=([0-9.]+), source_minutes=([0-9.]+)")
        return [{"x0": 1.0, "t": float(minutes) / 60.0, "observed_x": float(value) / 100.0} for value, minutes in pattern.findall(text)]
    pattern = re.compile(r"source_state=([0-9.]+), source_time=([0-9.]+)")
    return [{"x0": 1.0, "t": float(time_value), "observed_x": float(value)} for value, time_value in pattern.findall(text)]


def baseline_row(world_id: str) -> dict[str, object]:
    public = PUBLIC_ROOT / world_id
    private = PRIVATE_ROOT / world_id
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    truth = json.loads((private / "hidden_truth.json").read_text(encoding="utf-8"))
    menu = json.loads((public / "candidate_experiments.json").read_text(encoding="utf-8"))["experiments"]
    target = target_records((public / "target_notes.md").read_text(encoding="utf-8"))
    audit = oracle_scores(target, menu, float(truth["true_k"]), float(manifest["measurement_sigma"]), n_grid=1001)
    best = audit["best_experiment_ids"][0]
    max_time = max(menu, key=lambda item: float(item["measure_t"]))["experiment_id"]
    nominal_k = float(manifest["nominal_k"])
    simple_gaps = {
        str(item["experiment_id"]): (max(predict(model, float(item["x0"]), float(item["measure_t"]), nominal_k) for model in manifest["candidate_models"]) - min(predict(model, float(item["x0"]), float(item["measure_t"]), nominal_k) for model in manifest["candidate_models"])) / float(manifest["measurement_sigma"])
        for item in menu
    }
    simple = max(simple_gaps, key=simple_gaps.get)
    random_mean = sum(float(value) for value in audit["top1_score"].values()) / len(audit["top1_score"])
    return {
        "world_id": world_id,
        "relation": truth["expected_relation"],
        "world_class": manifest["world_class"],
        "oracle_best_experiment": best,
        "oracle_top1_score": round(float(audit["top1_score"][best]), 6),
        "fixed_e04_score": round(float(audit["top1_score"].get("E04", 0.0)), 6),
        "max_time_experiment": max_time,
        "max_time_score": round(float(audit["top1_score"][max_time]), 6),
        "simple_nominal_gap_experiment": simple,
        "simple_nominal_gap_score": round(float(audit["top1_score"][simple]), 6),
        "random_mean_score": round(random_mean, 6),
        "fixed_e04_shortfall": round(float(audit["top1_score"][best] - audit["top1_score"].get("E04", 0.0)), 6),
        "best_is_fixed_e04": best == "E04",
        "best_is_max_time": best == max_time,
    }


def discriminability_row(world_id: str) -> dict[str, object]:
    public = PUBLIC_ROOT / world_id
    private = PRIVATE_ROOT / world_id
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    truth = json.loads((private / "hidden_truth.json").read_text(encoding="utf-8"))
    target = target_records((public / "target_notes.md").read_text(encoding="utf-8"))
    source = source_records((public / "source_related.md").read_text(encoding="utf-8"), manifest)
    target_post = target_posterior(target, float(truth["true_k"]), float(manifest["measurement_sigma"]))
    target_entropy = entropy(target_post)
    if truth["expected_relation"] == "same":
        source_post = target_posterior(source, float(truth["true_k"]), float(manifest["measurement_sigma"]))
        combined_post = target_posterior(target + source, float(truth["true_k"]), float(manifest["measurement_sigma"]))
        source_support = max(source_post) - sorted(source_post)[-2]
        compatible_entropy = entropy(source_post)
        combined_entropy = entropy(combined_post)
        support_label = "shared_numeric_structure"
    else:
        source_post = [0.25, 0.25, 0.25, 0.25]
        compatible_entropy = entropy(source_post)
        combined_entropy = target_entropy
        source_support = 0.0
        support_label = "no_transferable_target_structure"
    source_text = (public / "source_related.md").read_text(encoding="utf-8")
    forbidden = [model for model in manifest["candidate_models"] if model in source_text] + re.findall(r"\bE0[1-8]\b", source_text)
    return {
        "world_id": world_id,
        "relation": truth["expected_relation"],
        "target_only_entropy": round(target_entropy, 8),
        "source_compatible_entropy": round(compatible_entropy, 8),
        "target_plus_source_entropy": round(combined_entropy, 8),
        "source_support": round(float(source_support), 8),
        "support_label": support_label,
        "source_record_count": len(source),
        "mapping_identifiable": truth["mapping_identifiable"],
        "confound_checks": "PASS" if not forbidden else "FAIL:" + ",".join(forbidden),
        "source_formula_or_action_leak": bool(forbidden),
    }


def main() -> None:
    global PUBLIC_ROOT, PRIVATE_ROOT, OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-subdir", default="worlds_v5p3_dev")
    parser.add_argument("--private-subdir", default="worlds_v5p3_dev")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    PUBLIC_ROOT = ROOT / "data" / args.public_subdir
    PRIVATE_ROOT = ROOT / "private" / args.private_subdir
    OUT = args.output
    OUT.mkdir(parents=True, exist_ok=True)
    worlds = [f"CV{index:03d}" for index in range(1, 5)]
    difficulty = [baseline_row(world_id) for world_id in worlds]
    with (OUT / "WORLD_DIFFICULTY_AUDIT.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(difficulty[0]))
        writer.writeheader()
        writer.writerows(difficulty)
    previous = ROOT / "reports" / "003_V5P2_OFFLINE_DEVELOPMENT" / "WORLD_DIFFICULTY_AUDIT.csv"
    if previous.exists():
        old_rows = list(csv.DictReader(previous.open(encoding="utf-8")))
        combined_fields = sorted(set(difficulty[0]) | {key for row in old_rows for key in row})
        with (OUT / "WORLD_DIFFICULTY_AUDIT_ALL.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=combined_fields)
            writer.writeheader()
            writer.writerows([{key: row.get(key, "") for key in combined_fields} for row in old_rows + difficulty])
    discriminability = [discriminability_row(world_id) for world_id in worlds]
    source_path = OUT / "SOURCE_EVIDENCE_DISCRIMINABILITY.csv"
    with source_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(discriminability[0]))
        writer.writeheader()
        writer.writerows(discriminability)
    (OUT / "source_evidence_discriminability.csv").write_bytes(source_path.read_bytes())
    (OUT / "SOURCE_EVIDENCE_AUDIT.csv").write_bytes(source_path.read_bytes())
    mapping_rows = []
    for world_id in worlds:
        truth = json.loads((PRIVATE_ROOT / world_id / "hidden_truth.json").read_text(encoding="utf-8"))
        manifest = json.loads((PUBLIC_ROOT / world_id / "manifest.json").read_text(encoding="utf-8"))
        mapping_rows.append({
            "world_id": world_id,
            "expected_relation": truth["expected_relation"],
            "mapping_identifiable": truth["mapping_identifiable"],
            "public_source_fields": json.dumps(manifest["public_variable_schema"]["source"], ensure_ascii=False),
            "public_target_fields": json.dumps(manifest["public_variable_schema"]["target"], ensure_ascii=False),
            "oracle_mapping_private": json.dumps(truth["oracle_mapping"], ensure_ascii=False, sort_keys=True),
            "abstention_allowed": truth["expected_relation"] != "same",
        })
    mapping_path = OUT / "MAPPING_VALIDATION.csv"
    with mapping_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(mapping_rows[0]))
        writer.writeheader()
        writer.writerows(mapping_rows)
    (OUT / "mapping_validation.csv").write_bytes(mapping_path.read_bytes())
    if any(row["confound_checks"] != "PASS" for row in discriminability):
        raise SystemExit("source leakage audit failed")
    print("audited CV001-CV004: public source leakage checks passed")


if __name__ == "__main__":
    main()
