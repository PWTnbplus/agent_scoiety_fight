from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

from .config import ExperimentConfig
from .ig_oracle import oracle_scores
from .simulators import MODELS, predict
from .world_registry import configured_world_ids


WORLD_SPECS = (
    ("W001", "chemical simulation", "physics simulation", "EXP_DECAY"),
    ("W002", "biological quantity simulation", "mathematical time-series simulation", "EXP_DECAY"),
    ("W003", "chemical simulation", "physics simulation", "HYPERBOLIC_DECAY"),
    ("W004", "biological quantity simulation", "mathematical time-series simulation", "HYPERBOLIC_DECAY"),
)
# Frozen pilot offsets. W002 uses a nearby deterministic seed selected before
# running agents so every world clears the pre-registered non-degeneracy gate.
WORLD_SEED_OFFSETS = (1009, 2019, 3027, 4036)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_menu(config: ExperimentConfig) -> list[dict[str, float | str]]:
    menu = [
        {"experiment_id": f"E{index:02d}", "x0": x0, "measure_t": measure_t, "unit_cost": 1.0}
        for index, (x0, measure_t) in enumerate(
            ((x0, measure_t) for x0 in config.candidate_initial_states for measure_t in config.candidate_measure_times),
            start=1,
        )
    ]
    if len(menu) != config.menu_size or len({item["experiment_id"] for item in menu}) != len(menu):
        raise ValueError("configured menu does not produce the required unique action count")
    return menu


def _format_observations(observations: list[dict[str, float]], prefix: str) -> str:
    return "\n".join(
        f"- {prefix}{index:02d}: x0={row['x0']:.2f}, t={row['t']:.2f}, measured_state={row['observed_x']:.5f}"
        for index, row in enumerate(observations, start=1)
    )


def _target_notes(world_id: str, domain: str, k: float, sigma: float, observations: list[dict[str, float]]) -> str:
    return (
        f"# {world_id} target observation (synthetic simulation)\n"
        f"Domain analogy: {domain}; state z is nonnegative and normalized.\n"
        f"Nominal candidate-rate k={k:.4f}; observation noise sigma={sigma:.3f}.\n"
        "Four candidate mechanisms use this same nominal rate; none is labelled true:\n"
        "- EXP_DECAY: z0*exp(-k*t)\n"
        "- HYPERBOLIC_DECAY: z0/(1+k*z0*t)\n"
        "- STRETCHED_EXP: z0*exp(-(k*t)^2)\n"
        "- BI_EXP: z0*(0.75 exp(-1.8*k*t)+0.25 exp(-0.25*k*t))\n"
        "Initial observations:\n"
        + _format_observations(observations, "T")
        + "\nChoose exactly one experiment ID from the public menu to discriminate at least two candidates.\n"
    )


def _source_notes(domain: str, observations: list[dict[str, float]]) -> str:
    return (
        "# Source study (synthetic simulation)\n"
        f"Domain analogy: {domain}; a normalized state observed over a longer time range.\n"
        "The records are evidence only; infer shape cautiously and do not assume a named law.\n"
        + _format_observations(observations, "S")
        + "\n"
    )


def generate_worlds(project_root: str | Path, config: ExperimentConfig) -> list[dict[str, Any]]:
    project_root = Path(project_root)
    data_root = project_root / "data" / config.worlds_subdir
    private_root = project_root / "private" / config.private_worlds_subdir
    menu = make_menu(config)
    results: list[dict[str, Any]] = []
    for index, (world_id, target_domain, source_domain, true_law) in enumerate(WORLD_SPECS[: config.num_worlds]):
        seed = config.seed + WORLD_SEED_OFFSETS[index]
        rng = random.Random(seed)
        k = round(rng.uniform(0.38, 0.65), 4)
        source_k = round(rng.uniform(0.42, 0.61), 4)
        sigma = config.measurement_noise_std
        target_observations = [
            {"x0": 1.0, "t": time_point, "observed_x": round(predict(true_law, 1.0, time_point, k) + rng.gauss(0.0, sigma), 5)}
            for time_point in config.initial_observation_times
        ]
        source_observations = [
            {"x0": 1.0, "t": time_point, "observed_x": round(predict(true_law, 1.0, time_point, source_k) + rng.gauss(0.0, sigma), 5)}
            for time_point in (0.3, 0.7, 1.4, 2.6)
        ]
        irrelevant_law = "HYPERBOLIC_DECAY" if true_law == "EXP_DECAY" else "EXP_DECAY"
        irrelevant_observations = [
            {"x0": 1.0, "t": time_point, "observed_x": round(predict(irrelevant_law, 1.0, time_point, source_k) + rng.gauss(0.0, sigma), 5)}
            for time_point in (0.3, 0.7, 1.4, 2.6)
        ]
        oracle = oracle_scores(target_observations, menu, k, sigma, models=tuple(config.candidate_models), n_grid=config.integration_grid)
        score_values = sorted(oracle["top1_score"].values())
        spread = (max(score_values) - score_values[len(score_values) // 2]) / 100.0
        valid = oracle["ig_star"] > config.min_ig_best and spread >= config.min_ig_spread and sum(score < 90.0 for score in score_values) >= 2
        if not valid:
            raise ValueError(f"INVALID_WORLD {world_id}: non-degenerate gate failed; regenerate with a frozen design")

        public_dir = data_root / world_id
        private_dir = private_root / world_id
        public_dir.mkdir(parents=True, exist_ok=True)
        private_dir.mkdir(parents=True, exist_ok=True)
        write_json(public_dir / "manifest.json", {
            "world_id": world_id,
            "target_domain": target_domain,
            "source_domain": source_domain,
            "seed": seed,
            "synthetic": True,
            "nominal_k": k,
            "measurement_sigma": sigma,
            "candidate_models": list(config.candidate_models),
        })
        write_json(public_dir / "candidate_experiments.json", {
            "world_id": world_id,
            "measurement": "normalized_state",
            "experiments": menu,
        })
        (public_dir / "target_notes.md").write_text(_target_notes(world_id, target_domain, k, sigma, target_observations), encoding="utf-8")
        (public_dir / "source_related.md").write_text(_source_notes(source_domain, source_observations), encoding="utf-8")
        (public_dir / "source_irrelevant.md").write_text(_source_notes(source_domain, irrelevant_observations), encoding="utf-8")
        write_json(private_dir / "hidden_truth.json", {
            "world_id": world_id,
            "true_law": true_law,
            "true_k": k,
            "source_true_law": true_law,
            "source_k": source_k,
            "irrelevant_true_law": irrelevant_law,
            "seed": seed,
            "synthetic": True,
        })
        write_json(private_dir / "oracle_results.json", oracle)
        results.append({"world_id": world_id, "seed": seed, "world_valid": True, "synthetic": True, "ig_star": oracle["ig_star"]})
    return results


def validate_worlds(project_root: str | Path, config: ExperimentConfig) -> list[dict[str, Any]]:
    project_root = Path(project_root)
    reports: list[dict[str, Any]] = []
    for world_id in configured_world_ids(project_root, config):
        public_dir = project_root / "data" / config.worlds_subdir / world_id
        private_dir = project_root / "private" / config.private_worlds_subdir / world_id
        if not public_dir.is_dir() or not private_dir.is_dir():
            raise FileNotFoundError(f"missing generated world: {world_id}")
        public_files = {path.name for path in public_dir.iterdir() if path.is_file()}
        if public_files != {"manifest.json", "target_notes.md", "source_related.md", "source_irrelevant.md", "candidate_experiments.json"}:
            raise AssertionError(f"unexpected public files for {world_id}: {public_files}")
        if any("hidden_truth" in path.read_text(encoding="utf-8") or "oracle_results" in path.read_text(encoding="utf-8") for path in public_dir.iterdir()):
            raise AssertionError(f"private marker leaked into public world {world_id}")
        menu = json.loads((public_dir / "candidate_experiments.json").read_text(encoding="utf-8"))["experiments"]
        if len(menu) != config.menu_size or len({item["experiment_id"] for item in menu}) != config.menu_size:
            raise AssertionError(f"invalid experiment menu for {world_id}")
        oracle = json.loads((private_dir / "oracle_results.json").read_text(encoding="utf-8"))
        scores = list(oracle["top1_score"].values())
        if oracle["ig_star"] <= config.min_ig_best or not math.isclose(max(scores), 100.0, abs_tol=1e-8) or min(scores) < 0 or max(scores) > 100:
            raise AssertionError(f"invalid oracle for {world_id}")
        reports.append({"world_id": world_id, "menu_size": len(menu), "ig_star": oracle["ig_star"], "best_experiment_ids": oracle["best_experiment_ids"]})
    return reports
