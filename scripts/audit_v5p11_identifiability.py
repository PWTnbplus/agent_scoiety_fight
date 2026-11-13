from __future__ import annotations

"""Audit V5-P11 public identifiability without opening private truth."""

import argparse
import csv
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.simulators import MODELS, predict

SOURCE_RE = re.compile(r"-\s*S(?P<id>\d+):\s*source_state=(?P<value>[0-9.]+),\s*source_time=(?P<time>[0-9.]+)\s*s,\s*source_x0=(?P<x0>[0-9.]+)")
TARGET_RE = re.compile(r"-\s*T(?P<id>\d+):\s*target_state=(?P<value>[0-9.]+),\s*target_time=(?P<time>[0-9.]+)\s*s,\s*target_x0=(?P<x0>[0-9.]+)")


def parse_rows(text: str, pattern: re.Pattern[str]) -> list[dict[str, float]]:
    return [{"value": float(m.group("value")), "time": float(m.group("time")), "x0": float(m.group("x0"))} for m in pattern.finditer(text)]


def rss(model: str, rows: list[dict[str, float]], k: float) -> float:
    return sum((row["value"] - predict(model, row["x0"], row["time"], k)) ** 2 for row in rows)


def audit(root: Path, config_path: Path, output: Path) -> list[dict[str, object]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    records: list[dict[str, object]] = []
    for world_id in config["allowed_worlds"]:
        public = root / "data" / config["worlds_subdir"] / world_id
        manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
        source = parse_rows((public / "source_related.md").read_text(encoding="utf-8"), SOURCE_RE)
        target = parse_rows((public / "target_notes.md").read_text(encoding="utf-8"), TARGET_RE)
        source_k = float(manifest["source_public_k"])
        target_k = float(manifest["target_public_k"])
        sigma = float(manifest["source_public_sigma"])
        source_fit = sorted((rss(model, source, source_k), model) for model in MODELS)
        target_fit = sorted((rss(model, target, target_k), model) for model in MODELS)
        source_gap = source_fit[1][0] - source_fit[0][0]
        target_gap = target_fit[1][0] - target_fit[0][0]
        source_margin = source_gap / max(len(source) * sigma * sigma, 1e-12)
        target_margin = target_gap / max(len(target) * sigma * sigma, 1e-12)
        records.append({
            "world_id": world_id,
            "public_metadata_complete": True,
            "source_observations": len(source),
            "target_observations": len(target),
            "time_unit": manifest.get("time_unit"),
            "source_x0_public": manifest.get("source_public_x0"),
            "source_k_public": source_k,
            "source_sigma_public": sigma,
            "source_best_candidate": source_fit[0][1],
            "source_best_rss": source_fit[0][0],
            "source_second_best_rss_gap": source_gap,
            "source_separability_sigma2": source_margin,
            "target_best_candidate": target_fit[0][1],
            "target_best_rss": target_fit[0][0],
            "target_second_best_rss_gap": target_gap,
            "target_separability_sigma2": target_margin,
            "public_identifiability_status": "POTENTIALLY_IDENTIFIABLE" if source_margin >= 1.0 else "AMBIGUOUS_SOURCE_SHAPE",
            "public_source_files": "manifest.json;candidate_experiments.json;target_notes.md;source_related.md",
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "v5p11_main.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "015_V5P11_PROJECT_FINISH" / "PUBLIC_IDENTIFIABILITY_BY_WORLD.csv")
    args = parser.parse_args()
    print(json.dumps(audit(ROOT, args.config, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
