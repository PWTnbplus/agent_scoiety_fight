from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id: str
    mode: str
    seed: int
    num_worlds: int
    worlds_per_law: int
    true_laws: tuple[str, ...]
    candidate_models: tuple[str, ...]
    menu_size: int
    initial_observation_times: tuple[float, ...]
    candidate_initial_states: tuple[float, ...]
    candidate_measure_times: tuple[float, ...]
    measurement_noise_std: float
    integration_grid: int
    max_total_tokens_per_condition: int
    max_agent_model_calls: int
    max_tool_calls: int
    max_final_questions: int
    repeats: int
    min_ig_best: float
    min_ig_spread: float
    allow_paid_api: bool
    api_source_project: str | None
    provider: str
    conditions: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExperimentConfig":
        return cls(
            experiment_id=str(raw["experiment_id"]),
            mode=str(raw.get("mode", "offline")),
            seed=int(raw["seed"]),
            num_worlds=int(raw["num_worlds"]),
            worlds_per_law=int(raw["worlds_per_law"]),
            true_laws=tuple(raw["true_laws"]),
            candidate_models=tuple(raw["candidate_models"]),
            menu_size=int(raw["menu_size"]),
            initial_observation_times=tuple(float(x) for x in raw["initial_observation_times"]),
            candidate_initial_states=tuple(float(x) for x in raw["candidate_initial_states"]),
            candidate_measure_times=tuple(float(x) for x in raw["candidate_measure_times"]),
            measurement_noise_std=float(raw["measurement_noise_std"]),
            integration_grid=int(raw.get("integration_grid", 1001)),
            max_total_tokens_per_condition=int(raw["max_total_tokens_per_condition"]),
            max_agent_model_calls=int(raw["max_agent_model_calls"]),
            max_tool_calls=int(raw.get("max_tool_calls", 0)),
            max_final_questions=int(raw.get("max_final_questions", 1)),
            repeats=int(raw.get("repeats", 1)),
            min_ig_best=float(raw["min_ig_best"]),
            min_ig_spread=float(raw["min_ig_spread"]),
            allow_paid_api=bool(raw.get("allow_paid_api", False)),
            api_source_project=raw.get("api_source_project"),
            provider=str(raw.get("provider", "mock")),
            conditions=tuple(raw["conditions"]),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("true_laws", "candidate_models", "initial_observation_times", "candidate_initial_states", "candidate_measure_times", "conditions"):
            value[key] = list(value[key])
        return value


def load_config(path: str | Path) -> ExperimentConfig:
    path = Path(path)
    return ExperimentConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))


def project_root_from_config(path: str | Path) -> Path:
    path = Path(path).resolve()
    return path.parent.parent if path.parent.name == "config" else path.parent
