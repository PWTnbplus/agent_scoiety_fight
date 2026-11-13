from __future__ import annotations

"""Create fresh, offline-only V5-P2 development worlds.

The generated worlds are deliberately labelled parameter/noise variants. They
are useful for engineering and difficulty audits, not independent theoretical
families or evidence for a real scientific claim.
"""

import json
import math
import random
from pathlib import Path

from mini_science.ig_oracle import oracle_scores
from mini_science.simulators import MODELS, predict


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT / "data" / "worlds_v5p2_dev"
PRIVATE_ROOT = ROOT / "private" / "worlds_v5p2_dev"


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def menu(initial_states: tuple[float, float], times: tuple[float, float, float, float]) -> list[dict[str, float | str]]:
    items: list[dict[str, float | str]] = []
    for offset, x0 in enumerate(initial_states):
        for index, measure_t in enumerate(times):
            items.append({"experiment_id": f"E{offset * 4 + index + 1:02d}", "measure_t": measure_t, "unit_cost": 1.0, "x0": x0})
    return items


def observations(model: str, x0: float, times: tuple[float, float], k: float, sigma: float, rng: random.Random) -> list[dict[str, float | str]]:
    values = []
    for index, time in enumerate(times, start=1):
        expected = predict(model, x0, time, k)
        noisy = max(0.0, expected + rng.gauss(0.0, sigma * 0.35))
        values.append({"id": f"T{index:02d}", "x0": x0, "t": time, "measured_state": round(noisy, 6)})
    return values


def target_text(world_id: str, domain: str, nominal_k: float, sigma: float, models: tuple[str, ...], records: list[dict[str, float | str]]) -> str:
    lines = [
        f"# {world_id} target observation (synthetic development world)",
        f"Domain analogy: {domain}; state z is nonnegative and normalized.",
        f"Nominal candidate-rate k={nominal_k:.4f}; observation noise sigma={sigma:.3f}.",
        "Candidate mechanisms use this same nominal rate; none is labelled true:",
    ]
    formulas = {
        "EXP_DECAY": "z0*exp(-k*t)",
        "HYPERBOLIC_DECAY": "z0/(1+k*z0*t)",
        "STRETCHED_EXP": "z0*exp(-(k*t)^2)",
        "BI_EXP": "z0*(0.75 exp(-1.8*k*t)+0.25 exp(-0.25*k*t))",
    }
    lines.extend(f"- {model}: {formulas[model]}" for model in models)
    lines.append("Initial observations:")
    lines.extend(f"- {record['id']}: x0={float(record['x0']):.2f}, t={float(record['t']):.2f}, measured_state={float(record['measured_state']):.6f}" for record in records)
    return "\n".join(lines) + "\n"


def source_text(source_domain: str, related: bool, k: float, sigma: float, seed: int) -> str:
    if related:
        return (
            f"# Public source note ({source_domain})\n"
            "S01: An observed normalized state decreases as elapsed time increases.\n"
            "S02: The source record is consistent with a decay-like mechanism under a positive rate.\n"
            f"S03: A synthetic calibration uses a nominal rate near {k:.3f} with uncertainty scale {sigma:.3f}.\n"
            f"This is a related-domain analogy for development only (seed marker {seed}); it is not a hidden label.\n"
        )
    return (
        f"# Public source note ({source_domain})\n"
        "S01: The source record describes a bounded cyclic process rather than a decay process.\n"
        "S02: Its observations are not claimed to map state or time variables to the target.\n"
        f"S03: This matched public note is intentionally non-informative for the target law (seed marker {seed}).\n"
    )


def main() -> None:
    if PUBLIC_ROOT.exists() and any(PUBLIC_ROOT.iterdir()):
        raise SystemExit(f"refusing to overwrite existing development worlds: {PUBLIC_ROOT}")
    if PRIVATE_ROOT.exists() and any(PRIVATE_ROOT.iterdir()):
        raise SystemExit(f"refusing to overwrite existing private fixtures: {PRIVATE_ROOT}")

    laws = MODELS
    specs = [
        (0.31, 0.035, (0.62, 1.16), (0.42, 0.90, 1.55, 2.35), True),
        (0.37, 0.040, (0.74, 1.48), (0.55, 1.20, 2.05, 3.10), True),
        (0.43, 0.030, (0.68, 1.32), (0.35, 0.75, 1.40, 2.10), True),
        (0.49, 0.045, (0.86, 1.62), (0.48, 1.05, 1.85, 2.80), True),
        (0.56, 0.035, (0.58, 1.28), (0.60, 1.35, 2.30, 3.40), True),
        (0.63, 0.050, (0.80, 1.55), (0.30, 0.70, 1.30, 2.00), True),
        (0.34, 0.040, (0.66, 1.38), (0.45, 1.00, 1.75, 2.55), False),
        (0.41, 0.030, (0.72, 1.44), (0.52, 1.15, 2.15, 3.25), False),
        (0.47, 0.045, (0.60, 1.20), (0.38, 0.82, 1.48, 2.25), False),
        (0.53, 0.035, (0.78, 1.58), (0.58, 1.28, 2.25, 3.55), False),
        (0.60, 0.050, (0.70, 1.36), (0.33, 0.88, 1.62, 2.45), False),
        (0.68, 0.030, (0.90, 1.70), (0.50, 1.10, 1.95, 2.90), False),
    ]
    for index, (k, sigma, initial_states, measure_times, related) in enumerate(specs, start=1):
        world_id = f"DV{index:03d}"
        law = laws[(index - 1) % len(laws)]
        seed = 20261200 + index
        rng = random.Random(seed)
        target_records = observations(law, initial_states[0], (0.08 + (index % 3) * 0.02, 0.18 + (index % 4) * 0.03), k, sigma, rng)
        domain = ("chemical simulation" if index % 2 else "ecological population")
        source_domain = "physics simulation" if related else "cyclic control"
        public = PUBLIC_ROOT / world_id
        private = PRIVATE_ROOT / world_id
        public.mkdir(parents=True, exist_ok=False)
        private.mkdir(parents=True, exist_ok=False)
        experiments = menu(initial_states, measure_times)
        nominal_k = round(k + (0.004 if index % 2 else -0.003), 4)
        manifest = {
            "world_id": world_id,
            "seed": seed,
            "synthetic": True,
            "development_only": True,
            "variant_index": index,
            "family_group": "parameter_noise_variant",
            "independent_theory_family": False,
            "target_domain": domain,
            "source_domain": source_domain,
            "candidate_models": list(MODELS),
            "measurement_sigma": sigma,
            "nominal_k": nominal_k,
            "source_label": "related_domain_analogy" if related else "matched_irrelevant_public_note",
        }
        menu_payload = {"world_id": world_id, "measurement": "normalized_state", "experiments": experiments}
        target_notes = target_text(world_id, domain, nominal_k, sigma, MODELS, target_records)
        related_note = source_text(source_domain, related, nominal_k, sigma, seed)
        irrelevant_note = source_text("matched irrelevant source", False, nominal_k, sigma, seed)
        public_target_for_oracle = [{"x0": record["x0"], "t": record["t"], "observed_x": record["measured_state"]} for record in target_records]
        oracle = oracle_scores(public_target_for_oracle, experiments, k, sigma, models=MODELS, n_grid=1001)
        dump(public / "manifest.json", manifest)
        dump(public / "candidate_experiments.json", menu_payload)
        (public / "target_notes.md").write_text(target_notes, encoding="utf-8")
        (public / "source_related.md").write_text(related_note, encoding="utf-8")
        (public / "source_irrelevant.md").write_text(irrelevant_note, encoding="utf-8")
        dump(private / "hidden_truth.json", {"world_id": world_id, "seed": seed, "true_law": law, "true_k": k})
        dump(private / "oracle_results.json", oracle)

    print(f"generated {len(specs)} fresh development worlds under {PUBLIC_ROOT}")


if __name__ == "__main__":
    main()
