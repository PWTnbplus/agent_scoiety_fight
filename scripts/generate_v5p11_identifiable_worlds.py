from __future__ import annotations

"""Generate frozen V5-P11 identifiable worlds without touching historical worlds."""

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
    ("IV001", "EXP_DECAY", "EXP_DECAY", "same", 1101),
    ("IV002", "HYPERBOLIC_DECAY", "EXP_DECAY", "different", 2203),
    ("IV003", "STRETCHED_EXP", "STRETCHED_EXP", "same", 3307),
    ("IV004", "BI_EXP", "HYPERBOLIC_DECAY", "different", 4411),
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
    if config.score_version != "v5p11":
        raise ValueError("V5P11 generator requires score_version=v5p11")
    public_root = project_root / "data" / config.worlds_subdir
    private_root = project_root / "private" / config.private_worlds_subdir
    menu = make_menu(config)
    rows: list[dict[str, object]] = []
    for world_id, target_law, source_law, relation, offset in WORLD_DESIGN:
        seed = config.seed + offset
        rng = random.Random(seed)
        target_k = round(0.42 + rng.random() * 0.20, 5)
        source_x0 = 1.0 if relation == "same" else round(0.85 + rng.random() * 0.55, 5)
        source_k = target_k if relation == "same" else round(0.36 + rng.random() * 0.28, 5)
        target_x0 = 1.0
        target_obs = observations(target_law, target_x0, target_k, tuple(config.initial_observation_times), config.measurement_noise_std, rng, "T")
        source_obs = observations(source_law, source_x0, source_k, SOURCE_TIMES, config.measurement_noise_std, rng, "S")
        irrelevant_obs = observations("EXP_DECAY" if source_law != "EXP_DECAY" else "BI_EXP", source_x0, source_k, SOURCE_TIMES, config.measurement_noise_std, rng, "S")
        oracle = oracle_scores(target_obs, menu, target_k, config.measurement_noise_std, models=tuple(config.candidate_models), n_grid=config.integration_grid)
        public_dir = public_root / world_id
        private_dir = private_root / world_id
        public_dir.mkdir(parents=True, exist_ok=True)
        private_dir.mkdir(parents=True, exist_ok=True)
        write_json(public_dir / "manifest.json", {
            "world_id": world_id,
            "protocol_version": "v5p11_identifiable_world_v1",
            "target_domain": "synthetic time-series target",
            "source_domain": "synthetic time-series source",
            "seed": seed,
            "synthetic": True,
            "time_unit": "seconds",
            "target_public_x0": target_x0,
            "target_public_k": target_k,
            "target_public_sigma": config.measurement_noise_std,
            "measurement_sigma": config.measurement_noise_std,
            "source_public_x0": source_x0,
            "source_public_k": source_k,
            "source_public_sigma": config.measurement_noise_std,
            "public_unit_mapping": {"source_time": "seconds", "source_state": "normalized_state", "source_x0": "same normalized state scale as target"},
            "candidate_models": list(config.candidate_models),
            "public_variable_schema": {"source": ["source_state", "source_time"], "target": ["target_state", "target_time"]},
        })
        write_json(public_dir / "candidate_experiments.json", {"world_id": world_id, "measurement": "normalized_state", "experiments": menu})
        target_text = (
            f"# {world_id} target observations (V5-P11 public protocol)\n"
            "All times use seconds. Target initial state x0 and nominal candidate-rate k are public metadata; sigma is the independent Gaussian observation scale.\n"
            f"Target x0={target_x0:.5f}; target candidate-rate k={target_k:.5f}; target noise sigma={config.measurement_noise_std:.5f}.\n"
            "Candidate equations (none is labelled as true):\n" + "\n".join(f"- {equation}" for equation in EQUATIONS) + "\n"
            "Initial target observations:\n" + format_observations(target_obs, "target") + "\n"
            "Choose exactly one experiment ID from the public menu.\n"
        )
        source_text = (
            f"# {world_id} public source observations (related record)\n"
            "All times use seconds and the source uses the same normalized state scale. The source initial state x0, candidate-rate k, and independent Gaussian noise sigma are public so the source shape can be audited without hidden calibration assumptions.\n"
            f"Source x0={source_x0:.5f}; source candidate-rate k={source_k:.5f}; source noise sigma={config.measurement_noise_std:.5f}.\n"
            "Compare the source observations to the public candidate equations; the source law and relation label are intentionally not disclosed.\n"
            + format_observations(source_obs, "source") + "\n"
        )
        irrelevant_text = (
            f"# {world_id} public source observations (irrelevant control record)\n"
            "All times use seconds and the source uses the same normalized state scale. The source initial state x0, candidate-rate k, and independent Gaussian noise sigma are public. This record is a pre-registered negative control and is not the related record used by B/C/D.\n"
            f"Source x0={source_x0:.5f}; source candidate-rate k={source_k:.5f}; source noise sigma={config.measurement_noise_std:.5f}.\n"
            + format_observations(irrelevant_obs, "source") + "\n"
        )
        (public_dir / "target_notes.md").write_text(target_text, encoding="utf-8")
        (public_dir / "source_related.md").write_text(source_text, encoding="utf-8")
        (public_dir / "source_irrelevant.md").write_text(irrelevant_text, encoding="utf-8")
        write_json(private_dir / "hidden_truth.json", {
            "world_id": world_id,
            "true_law": target_law,
            "true_k": target_k,
            "source_true_law": source_law,
            "source_k": source_k,
            "source_x0": source_x0,
            "expected_relation": relation,
            "expected_candidate_law_id": target_law if relation == "same" else "UNKNOWN",
            "oracle_mapping": {"source_state": "target_state", "source_time": "target_time"},
            "mapping_identifiable": relation == "same",
            "seed": seed,
            "synthetic": True,
            "protocol_version": "v5p11_identifiable_world_v1",
        })
        write_json(private_dir / "oracle_results.json", oracle)
        rows.append({"world_id": world_id, "seed": seed, "relation": relation, "target_law_private": target_law, "source_law_private": source_law, "ig_star": oracle["ig_star"], "best_experiment_ids": oracle["best_experiment_ids"]})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "v5p11_main.json")
    args = parser.parse_args()
    rows = generate(ROOT, args.config)
    print(json.dumps([{key: value for key, value in row.items() if key not in {"target_law_private", "source_law_private"}} for row in rows], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
