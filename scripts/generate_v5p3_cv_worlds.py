from __future__ import annotations

"""Generate four frozen, offline V5-P3 cross-domain validation worlds."""

import json
import math
import random
import argparse
from pathlib import Path

from mini_science.ig_oracle import oracle_scores
from mini_science.simulators import MODELS, predict


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT / "data" / "worlds_v5p3_dev"
PRIVATE_ROOT = ROOT / "private" / "worlds_v5p3_dev"


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_menu() -> list[dict[str, float | str]]:
    return [
        {"experiment_id": f"E{index:02d}", "measure_t": time_value, "unit_cost": 1.0, "x0": x0}
        for index, (x0, time_value) in enumerate(((x0, t) for x0 in (0.7, 1.4) for t in (0.5, 1.1, 1.8, 2.6)), start=1)
    ]


def target_notes(world_id: str, k: float, sigma: float, records: list[dict[str, float]]) -> str:
    lines = [
        f"# {world_id} target observations (synthetic development world)",
        "Domain analogy: chemical simulation; state z is nonnegative and normalized.",
        f"Nominal candidate-rate k={k:.4f}; observation noise sigma={sigma:.3f}.",
        "Four candidate mechanisms use this same nominal rate; none is labelled true:",
        "- EXP_DECAY: z0*exp(-k*t)",
        "- HYPERBOLIC_DECAY: z0/(1+k*z0*t)",
        "- STRETCHED_EXP: z0*exp(-(k*t)^2)",
        "- BI_EXP: z0*(0.75 exp(-1.8*k*t)+0.25 exp(-0.25*k*t))",
        "Initial observations:",
    ]
    lines.extend(f"- T{index:02d}: x0={row['x0']:.2f}, t={row['t']:.2f}, measured_state={row['observed_x']:.6f}" for index, row in enumerate(records, start=1))
    return "\n".join(lines) + "\n"


def source_note(kind: str, records: list[dict[str, float]], *, transformed: bool = False, irrelevant: bool = False) -> str:
    """Render source observations without encoding the relation label.

    ``kind`` and ``irrelevant`` remain in the signature for compatibility with
    the V5-P3 generator call sites, but are deliberately not rendered.  The
    public reader must infer any relation from the observations rather than
    from a condition name or an evaluative adjective.
    """
    if transformed:
        header = "# Public source observations"
        intro = (
            "The instrument reports concentration on a 0–100 scale and elapsed duration in minutes. "
            "For numeric comparison, concentration can be divided by 100 and minutes can be divided by 60; "
            "field correspondence and numeric unit conversion are separate questions."
        )
        lines = [f"- S{index:02d}: source_concentration={row['value']:.4f}, source_minutes={row['time']:.2f}" for index, row in enumerate(records, start=1)]
    else:
        header = "# Public source observations"
        intro = "The records are public measurements from another domain. They describe observations, not a named mechanism or a recommended target experiment."
        lines = [f"- S{index:02d}: source_state={row['value']:.6f}, source_time={row['time']:.2f}" for index, row in enumerate(records, start=1)]
    return "\n".join([header, intro] + lines + ["Evidence IDs are individual observations; no hidden label is provided.", ""])


def target_observations(law: str, k: float, sigma: float, rng: random.Random) -> list[dict[str, float]]:
    times = (0.08, 0.18)
    return [{"x0": 1.0, "t": t, "observed_x": max(0.0, predict(law, 1.0, t, k) + rng.gauss(0.0, sigma * 0.25))} for t in times]


def related_source(world_id: str, k: float, sigma: float, rng: random.Random) -> tuple[list[dict[str, float]], dict[str, str]]:
    times = (0.30, 0.75, 1.45, 2.40)
    records = [{"time": t, "value": max(0.0, predict("EXP_DECAY", 1.0, t, k) + rng.gauss(0.0, sigma * 0.20))} for t in times]
    return records, {"source_state": "target_state", "source_time": "target_time"}


def transformed_source(k: float, sigma: float, rng: random.Random) -> tuple[list[dict[str, float]], dict[str, str]]:
    times = (0.30, 0.75, 1.45, 2.40)
    records = [{"time": t * 60.0, "value": max(0.0, 100.0 * predict("EXP_DECAY", 1.0, t, k) + rng.gauss(0.0, sigma * 20.0))} for t in times]
    return records, {"source_concentration": "target_state", "source_minutes": "target_time"}


def different_source(rng: random.Random) -> list[dict[str, float]]:
    times = (0.30, 0.75, 1.45, 2.40)
    return [{"time": t, "value": 0.64 + 0.075 * math.sin(1.7 * t) + rng.gauss(0.0, 0.006)} for t in times]


def unknown_source(rng: random.Random) -> list[dict[str, float]]:
    times = (0.30, 0.75, 1.45, 2.40)
    return [{"time": t, "value": 0.77 + rng.gauss(0.0, 0.045)} for t in times]


def generate_worlds(public_root: Path = PUBLIC_ROOT, private_root: Path = PRIVATE_ROOT, *, namespace: str = "v5p3") -> None:
    if public_root.exists() and any(public_root.iterdir()):
        raise SystemExit(f"refusing to overwrite existing CV worlds: {public_root}")
    if private_root.exists() and any(private_root.iterdir()):
        raise SystemExit(f"refusing to overwrite existing CV fixtures: {private_root}")
    specs = [
        ("CV001", "same", "EXP_DECAY", True, ("source_state", "source_time"), ("target_state", "target_time")),
        ("CV002", "same", "EXP_DECAY", True, ("source_concentration", "source_minutes"), ("target_state", "target_time")),
        ("CV003", "different", "UNKNOWN", False, ("source_state", "source_time"), ("target_state", "target_time")),
        ("CV004", "unknown", "UNKNOWN", False, ("source_state", "source_time"), ("target_state", "target_time")),
    ]
    menu = make_menu()
    for index, (world_id, relation, expected_law, mapping_identifiable, source_ids, target_ids) in enumerate(specs, start=1):
        seed = 20261300 + index
        k = 0.51 + index * 0.025
        sigma = 0.04 if world_id != "CV004" else 0.08
        rng = random.Random(seed)
        target_law = ("EXP_DECAY", "EXP_DECAY", "HYPERBOLIC_DECAY", "STRETCHED_EXP")[index - 1]
        target = target_observations(target_law, k, sigma, rng)
        if world_id == "CV001":
            source, mapping = related_source(world_id, k, sigma, rng)
            source_related = source_note("shared dynamics domain", source)
        elif world_id == "CV002":
            source, mapping = transformed_source(k, sigma, rng)
            source_related = source_note("instrument calibration domain", source, transformed=True)
        elif world_id == "CV003":
            source = different_source(rng)
            mapping = {}
            source_related = source_note("seasonal control domain", source)
        else:
            source = unknown_source(rng)
            mapping = {}
            source_related = source_note("short noisy observation domain", source)
        irrelevant_source = [{"time": row["time"], "value": 0.52 + 0.03 * math.cos(row["time"] * 1.3) + rng.gauss(0.0, 0.01)} for row in source]
        if world_id == "CV002":
            irrelevant_note = source_note("matched instrument control", [{"time": row["time"] * 60.0, "value": row["value"] * 100.0} for row in irrelevant_source], transformed=True, irrelevant=True)
        else:
            irrelevant_note = source_note("matched control domain", irrelevant_source, irrelevant=True)
        public = public_root / world_id
        private = private_root / world_id
        public.mkdir(parents=True, exist_ok=False)
        private.mkdir(parents=True, exist_ok=False)
        oracle = oracle_scores(target, menu, k, sigma, models=MODELS, n_grid=1001)
        manifest = {
            "world_id": world_id,
            "seed": seed,
            "synthetic": True,
            "development_only": True,
            "world_class": "cross_domain_validation",
            "public_material_version": namespace,
            "target_domain": "chemical simulation",
            "source_domain": "cross-disciplinary measurement study",
            "candidate_models": list(MODELS),
            "measurement_sigma": sigma,
            "nominal_k": round(k, 4),
            "public_variable_schema": {"source": list(source_ids), "target": list(target_ids)},
            "source_record_count": len(source),
        }
        if world_id == "CV002":
            manifest["public_unit_conversion"] = {
                "source_minutes_to_target_time": "divide_by_60",
                "source_concentration_to_target_state": "divide_by_100",
                "mapping_and_units_are_separate": True,
            }
        target_text = target_notes(world_id, k, sigma, target)
        (public / "target_notes.md").write_text(target_text, encoding="utf-8")
        (public / "source_related.md").write_text(source_related, encoding="utf-8")
        (public / "source_irrelevant.md").write_text(irrelevant_note, encoding="utf-8")
        dump(public / "manifest.json", manifest)
        dump(public / "candidate_experiments.json", {"world_id": world_id, "measurement": "normalized_state", "experiments": menu})
        dump(private / "hidden_truth.json", {
            "world_id": world_id,
            "seed": seed,
            "true_law": target_law,
            "true_k": k,
            "expected_relation": relation,
            "expected_candidate_law_id": expected_law,
            "mapping_identifiable": mapping_identifiable,
            "oracle_mapping": mapping,
            "evidence_support_ids": ["S01", "S02", "S03", "T01", "T02"] if relation == "same" else [],
            "source_generator": "shared_decay" if relation == "same" else ("oscillatory" if relation == "different" else "short_noisy"),
        })
        dump(private / "oracle_results.json", oracle)
        dump(private / "source_reference.json", {"relation": relation, "mapping": mapping, "source_records": source})
    print(f"generated CV001-CV004 in {namespace} namespace")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, default=PUBLIC_ROOT)
    parser.add_argument("--private-root", type=Path, default=PRIVATE_ROOT)
    parser.add_argument("--namespace", default="v5p3")
    args = parser.parse_args()
    generate_worlds(args.public_root, args.private_root, namespace=args.namespace)


if __name__ == "__main__":
    main()
