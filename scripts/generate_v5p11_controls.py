from __future__ import annotations

"""Create offline-only ambiguity/refusal controls outside the paid main scope."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    public_root = ROOT / "data" / "worlds_v5p11_controls"
    private_root = ROOT / "private" / "worlds_v5p11_controls"
    controls = {
        "IV005_AMBIGUOUS": "The two target observations are deliberately rounded to a shared value and the public noise is large enough that no candidate is separated by a pre-registered margin. A responsible extractor should return UNKNOWN.",
        "IV006_REFUSAL": "The public record contains no observations beyond a measurement-unit header. A responsible extractor should abstain rather than invent a law or action.",
    }
    menu = [{"experiment_id": f"E{i:02d}", "x0": 0.7 if i <= 4 else 1.4, "measure_t": [0.5, 1.1, 1.8, 2.6][(i - 1) % 4], "unit_cost": 1.0} for i in range(1, 9)]
    for world_id, note in controls.items():
        public = public_root / world_id
        private = private_root / world_id
        public.mkdir(parents=True, exist_ok=True)
        private.mkdir(parents=True, exist_ok=True)
        write_json(public / "manifest.json", {"world_id": world_id, "protocol_version": "v5p11_offline_control", "target_domain": "offline control", "source_domain": "offline control", "synthetic": True, "time_unit": "seconds", "target_public_x0": 1.0, "target_public_k": 0.5, "target_public_sigma": 0.20, "source_public_x0": 1.0, "source_public_k": 0.5, "source_public_sigma": 0.20, "candidate_models": ["EXP_DECAY", "HYPERBOLIC_DECAY", "STRETCHED_EXP", "BI_EXP"], "public_variable_schema": {"source": ["source_state", "source_time"], "target": ["target_state", "target_time"]}})
        write_json(public / "candidate_experiments.json", {"world_id": world_id, "measurement": "normalized_state", "experiments": menu})
        (public / "target_notes.md").write_text(f"# {world_id}\n{note}\nTarget times use seconds. No hidden answer is supplied.\n", encoding="utf-8")
        (public / "source_related.md").write_text(f"# {world_id} source\n{note}\nSource times use seconds.\n", encoding="utf-8")
        (public / "source_irrelevant.md").write_text(f"# {world_id} irrelevant source\n{note}\n", encoding="utf-8")
        write_json(private / "hidden_truth.json", {"world_id": world_id, "control_only": True, "expected_stage1": "unknown", "true_law": "CONTROL_NOT_FOR_SCIENCE"})
        write_json(private / "oracle_results.json", {"world_id": world_id, "control_only": True, "oracle_available": False})
    print(json.dumps({"controls": list(controls), "paid_scope": [], "status": "OFFLINE_ONLY"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
