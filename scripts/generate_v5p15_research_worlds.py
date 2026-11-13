from __future__ import annotations

"""Generate the frozen eight-world V5-P15 research cohort.

The four RS001-RS004 worlds contain a shared source/target mechanism. The four
RS005-RS008 worlds contain a pre-registered source/target mechanism mismatch.
Public files carry observations and candidate equations; private files carry
truth and oracle scores for the evaluator only.
"""

import argparse
import json
import random
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.config import load_config
from mini_science.ig_oracle import oracle_scores
from mini_science.simulators import predict
from mini_science.worldgen import make_menu


WORLD_DESIGN = (
    ("RS001", "reaction kinetics", "cellular relaxation", "EXP_DECAY", "EXP_DECAY", "same", 1101),
    ("RS002", "population dynamics", "thermal relaxation", "HYPERBOLIC_DECAY", "HYPERBOLIC_DECAY", "same", 2203),
    # These offsets were selected before API execution by the deterministic
    # non-degeneracy gate.  The fixed seeds keep the confirmation cohort
    # reproducible while giving the two less separated mechanisms an
    # identifiable target posterior.
    ("RS003", "signal attenuation", "enzyme activity", "STRETCHED_EXP", "STRETCHED_EXP", "same", 101),
    ("RS004", "resource depletion", "circuit discharge", "BI_EXP", "BI_EXP", "same", 100),
    ("RS005", "reaction kinetics", "cellular relaxation", "EXP_DECAY", "HYPERBOLIC_DECAY", "different", 5509),
    ("RS006", "population dynamics", "thermal relaxation", "HYPERBOLIC_DECAY", "EXP_DECAY", "different", 6613),
    ("RS007", "signal attenuation", "enzyme activity", "STRETCHED_EXP", "BI_EXP", "different", 136),
    ("RS008", "resource depletion", "circuit discharge", "BI_EXP", "STRETCHED_EXP", "different", 8837),
)
SOURCE_TIMES = (0.25, 0.50, 0.90, 1.40, 2.20, 3.00, 3.80, 4.60)
EQUATIONS = (
    "EXP_DECAY: z0*exp(-k*t)",
    "HYPERBOLIC_DECAY: z0/(1+k*z0*t)",
    "STRETCHED_EXP: z0*exp(-(k*t)^2)",
    "BI_EXP: z0*(0.75*exp(-1.8*k*t)+0.25*exp(-0.25*k*t))",
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def observations(model: str, x0: float, k: float, times: tuple[float, ...], sigma: float, rng: random.Random, prefix: str) -> list[dict[str, float | str]]:
    return [
        {"evidence_id": f"{prefix}{index:02d}", "x0": x0, "t": time_point, "observed_x": round(predict(model, x0, time_point, k) + rng.gauss(0.0, sigma), 6)}
        for index, time_point in enumerate(times, 1)
    ]


def format_observations(rows: list[dict[str, float | str]], label: str) -> str:
    return "\n".join(
        f"- {row['evidence_id']}: {label}_state={float(row['observed_x']):.6f}, {label}_time={float(row['t']):.2f} s, {label}_x0={float(row['x0']):.4f}"
        for row in rows
    )


def generate(project_root: Path, config_path: Path) -> list[dict[str, object]]:
    config = load_config(config_path)
    if config.score_version != "v5p11" or config.num_worlds != len(WORLD_DESIGN):
        raise ValueError("V5P15 generator requires the eight-world v5p11 research config")
    public_root = project_root / "data" / config.worlds_subdir
    private_root = project_root / "private" / config.private_worlds_subdir
    menu = make_menu(config)
    rows: list[dict[str, object]] = []
    for world_id, target_domain, source_domain, target_law, source_law, relation, offset in WORLD_DESIGN:
        seed = config.seed + offset
        rng = random.Random(seed)
        target_k = round(0.40 + rng.random() * 0.24, 5)
        source_x0 = round(0.88 + rng.random() * 0.32, 5)
        source_k = target_k if relation == "same" else round(0.34 + rng.random() * 0.30, 5)
        target_x0 = 1.0
        target_obs = observations(target_law, target_x0, target_k, tuple(config.initial_observation_times), config.measurement_noise_std, rng, "T")
        source_obs = observations(source_law, source_x0, source_k, SOURCE_TIMES, config.measurement_noise_std, rng, "S")
        irrelevant_law = "BI_EXP" if source_law != "BI_EXP" else "EXP_DECAY"
        irrelevant_obs = observations(irrelevant_law, source_x0, source_k, SOURCE_TIMES, config.measurement_noise_std, rng, "S")
        oracle = oracle_scores(target_obs, menu, target_k, config.measurement_noise_std, models=tuple(config.candidate_models), n_grid=config.integration_grid)
        score_values = sorted(oracle["top1_score"].values())
        spread = (max(score_values) - score_values[len(score_values) // 2]) / 100.0
        valid = oracle["ig_star"] > config.min_ig_best and spread >= config.min_ig_spread and sum(score < 90.0 for score in score_values) >= 2
        if not valid:
            raise ValueError(f"INVALID_WORLD {world_id}: non-degenerate gate failed")
        public_dir = public_root / world_id
        private_dir = private_root / world_id
        public_dir.mkdir(parents=True, exist_ok=True)
        private_dir.mkdir(parents=True, exist_ok=True)
        write_json(public_dir / "manifest.json", {
            "world_id": world_id, "protocol_version": "v5p15_identifiable_world_v1",
            "target_domain": target_domain, "source_domain": source_domain,
            "seed": seed, "synthetic": True, "time_unit": "seconds",
            "target_public_x0": target_x0, "target_public_k": target_k,
            "target_public_sigma": config.measurement_noise_std,
            "source_public_x0": source_x0, "source_public_k": source_k,
            "source_public_sigma": config.measurement_noise_std,
            "measurement_sigma": config.measurement_noise_std,
            "public_unit_mapping": {"source_time": "seconds", "source_state": "normalized_state", "source_x0": "same normalized state scale as target"},
            "candidate_models": list(config.candidate_models),
            "public_variable_schema": {"source": ["source_state", "source_time"], "target": ["target_state", "target_time"]},
        })
        write_json(public_dir / "candidate_experiments.json", {"world_id": world_id, "measurement": "normalized_state", "experiments": menu})
        target_text = (
            f"# {world_id} target observations (V5-P15 public protocol)\n"
            "All times use seconds. Target initial state x0, nominal candidate-rate k, and independent Gaussian observation scale are public metadata.\n"
            f"Target x0={target_x0:.5f}; target candidate-rate k={target_k:.5f}; target noise sigma={config.measurement_noise_std:.5f}.\n"
            "Candidate equations (each candidate remains unlabeled):\n" + "\n".join(f"- {equation}" for equation in EQUATIONS) + "\n"
            "Initial target observations:\n" + format_observations(target_obs, "target") + "\nChoose exactly one experiment ID from the public menu.\n"
        )
        source_text = (
            f"# {world_id} public source observations (related record)\n"
            "All times use seconds and the source uses the same normalized state scale. Source metadata is public for shape comparison; the source mechanism remains unlabeled.\n"
            f"Source x0={source_x0:.5f}; source candidate-rate k={source_k:.5f}; source noise sigma={config.measurement_noise_std:.5f}.\n"
            "Compare source observations with the public candidate equations and state the evidence limits.\n" + format_observations(source_obs, "source") + "\n"
        )
        irrelevant_text = (
            f"# {world_id} public source observations (irrelevant control record)\n"
            "This source record is a pre-registered unrelated control with public units, metadata, and observations.\n"
            f"Source x0={source_x0:.5f}; source candidate-rate k={source_k:.5f}; source noise sigma={config.measurement_noise_std:.5f}.\n" + format_observations(irrelevant_obs, "source") + "\n"
        )
        (public_dir / "target_notes.md").write_text(target_text, encoding="utf-8")
        (public_dir / "source_related.md").write_text(source_text, encoding="utf-8")
        (public_dir / "source_irrelevant.md").write_text(irrelevant_text, encoding="utf-8")
        write_json(private_dir / "hidden_truth.json", {
            "world_id": world_id, "true_law": target_law, "true_k": target_k,
            "source_true_law": source_law, "source_k": source_k, "source_x0": source_x0,
            "expected_relation": relation,
            "expected_candidate_law_id": target_law if relation == "same" else "UNKNOWN",
            "oracle_mapping": {"source_state": "target_state", "source_time": "target_time"},
            "mapping_identifiable": relation == "same", "seed": seed, "synthetic": True,
            "protocol_version": "v5p15_identifiable_world_v1",
        })
        write_json(private_dir / "oracle_results.json", oracle)
        rows.append({"world_id": world_id, "seed": seed, "relation": relation, "target_law_private": target_law, "source_law_private": source_law, "ig_star": oracle["ig_star"], "best_experiment_ids": oracle["best_experiment_ids"]})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "v5p15_research.json")
    args = parser.parse_args()
    rows = generate(ROOT, args.config)
    print(json.dumps([{key: value for key, value in row.items() if key not in {"target_law_private", "source_law_private"}} for row in rows], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
