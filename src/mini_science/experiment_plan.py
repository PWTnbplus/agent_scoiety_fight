from __future__ import annotations

"""Deterministic, auditable execution plans for v2 runs."""

import hashlib
import json
from pathlib import Path
import random
import re
from typing import Any, Iterable

from .config import ExperimentConfig
from .schema import canonical_json, sha256_json
from .stable_fingerprint import stable_tree_hash
from .world_registry import resolve_worlds


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def config_hash(config: ExperimentConfig) -> str:
    return sha256_json(config.to_dict())


def world_hash(project_root: str | Path, world_id: str, *, worlds_subdir: str = "worlds", private_worlds_subdir: str = "worlds") -> str:
    root = Path(project_root)
    paths = sorted([
        *((root / "data" / worlds_subdir / world_id).glob("*")),
        *((root / "private" / private_worlds_subdir / world_id).glob("*")),
    ], key=lambda path: path.name)
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file():
            digest.update(path.name.encode("utf-8"))
            digest.update(file_sha256(path).encode("ascii"))
    return digest.hexdigest()


def source_tree_hash(project_root: str | Path) -> str:
    root = Path(project_root) / "src"
    # Offline tests often create a temporary project containing only generated
    # worlds.  Keep their historical runner behavior by fingerprinting the
    # installed package source in that harness case; the authorization
    # preflight itself always hashes the real project/src directory directly,
    # where a missing root remains fail-closed.
    if not root.is_dir():
        root = Path(__file__).resolve().parent
    return stable_tree_hash(root)


def _law_family(project_root: Path, world_id: str, private_worlds_subdir: str) -> str:
    path = project_root / "private" / private_worlds_subdir / world_id / "hidden_truth.json"
    if not path.exists():
        return "UNKNOWN"
    value = json.loads(path.read_text(encoding="utf-8"))
    return str(value.get("true_law", "UNKNOWN"))


def _stage_rows(
    *,
    project_root: Path,
    config: ExperimentConfig,
    run_id: str,
    pair_id: str,
    world_id: str,
    replicate: int,
    condition: str,
    stage: str,
    order_index: int,
) -> dict[str, Any]:
    stage_calls = 1 if stage in {"stage1", "stage2"} else 0
    if condition in {"S_COLLAB3", "S_COMPETE3"} and stage == "stage2":
        stage_calls = 3
    source_variant = "irrelevant" if condition == "A_TARGET_ONLY" else "related"
    agent_name = "pattern_extractor" if stage == "stage1" else ("single_question_designer" if condition in {"A_TARGET_ONLY", "B_SINGLE_RELATED"} else "question_designer")
    request_id = f"{pair_id}:{condition}:{stage}:{agent_name}:attempt1"
    return {
        "run_id": run_id,
        "pair_id": pair_id,
        "world_id": world_id,
        "law_family_id": _law_family(project_root, world_id, config.private_worlds_subdir),
        "replicate": replicate,
        "condition": condition,
        "stage": stage,
        "request_id": request_id,
        "agent_name": agent_name,
        "stage1_shared_key": pair_id,
        "model_snapshot": "configured-model",
        "source_variant": source_variant,
        "assigned_budget_tokens": config.max_total_tokens_per_condition,
        "max_model_calls": stage_calls,
        "seed": config.plan_seed if config.plan_seed is not None else config.seed,
        "order_index": order_index,
        "status": "PENDING",
        "config_hash": config_hash(config),
        "world_hash": world_hash(project_root, world_id, worlds_subdir=config.worlds_subdir, private_worlds_subdir=config.private_worlds_subdir),
    }


def build_plan(
    project_root: str | Path,
    config: ExperimentConfig,
    *,
    run_id: str = "v2_plan",
    worlds: Iterable[str] | None = None,
    conditions: Iterable[str] | None = None,
    repeats: int | None = None,
    request_namespace: str | None = None,
    replicate_indices: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    root = Path(project_root).resolve()
    selected_worlds = resolve_worlds(root, config, list(worlds) if worlds is not None else "all")
    selected_conditions = list(conditions or config.conditions)
    repeat_count = config.repeats if repeats is None else int(repeats)
    selected_replicates = list(range(repeat_count)) if replicate_indices is None else sorted({int(value) for value in replicate_indices})
    if not selected_replicates or (replicate_indices is not None and any(value < 0 or value >= repeat_count for value in selected_replicates)):
        raise ValueError("replicate_indices must select positive absolute repeat indices within the configured design")
    if request_namespace is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,100}", str(request_namespace)):
        raise ValueError("request_namespace must be a stable alphanumeric namespace")
    rng = random.Random(config.plan_seed if config.plan_seed is not None else config.seed)
    if config.randomize_order:
        rng.shuffle(selected_worlds)
    rows: list[dict[str, Any]] = []
    order_index = 0
    for world_id in selected_worlds:
        for replicate in selected_replicates:
            pair_prefix = f"{request_namespace}_" if request_namespace else ("V5P11_" if str(config.score_version).startswith("v5p11") else ("V5P8_" if str(config.score_version).startswith("v5p8") else ""))
            pair_id = f"{pair_prefix}{world_id}_R{replicate}"
            singleton = [condition for condition in selected_conditions if condition in {"A_TARGET_ONLY", "B_SINGLE_RELATED"}]
            seq2 = [condition for condition in selected_conditions if condition in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK", "E_SEQ2_IRRELEVANT_TRANSFER", "F_SEQ2_MISALIGNED_TRANSFER"}]
            societies = [condition for condition in selected_conditions if condition in {"S_COLLAB3", "S_COMPETE3"}]
            if config.randomize_order:
                rng.shuffle(singleton)
                rng.shuffle(seq2)
                rng.shuffle(societies)
            for condition in singleton:
                rows.append(_stage_rows(project_root=root, config=config, run_id=run_id, pair_id=pair_id, world_id=world_id, replicate=replicate, condition=condition, stage="stage2", order_index=order_index))
                order_index += 1
            if seq2:
                owner = "C_SEQ2_TRANSFER" if "C_SEQ2_TRANSFER" in seq2 else seq2[0]
                rows.append(_stage_rows(project_root=root, config=config, run_id=run_id, pair_id=pair_id, world_id=world_id, replicate=replicate, condition=owner, stage="stage1", order_index=order_index))
                order_index += 1
                for condition in seq2:
                    rows.append(_stage_rows(project_root=root, config=config, run_id=run_id, pair_id=pair_id, world_id=world_id, replicate=replicate, condition=condition, stage="stage2", order_index=order_index))
                    order_index += 1
            for condition in societies:
                rows.append(_stage_rows(project_root=root, config=config, run_id=run_id, pair_id=pair_id, world_id=world_id, replicate=replicate, condition=condition, stage="stage2", order_index=order_index))
                order_index += 1
    return rows


def write_plan(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    destination.write_text(text, encoding="utf-8")
    return destination


def read_plan(path: str | Path) -> list[dict[str, Any]]:
    destination = Path(path)
    if not destination.exists():
        return []
    return [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_fingerprint(project_root: str | Path, config: ExperimentConfig, *, provider: str, model_snapshot: str, worlds: list[str], conditions: list[str], repeats: int, request_namespace: str | None = None, replicate_indices: Iterable[int] | None = None) -> dict[str, Any]:
    value = {
        "config_hash": config_hash(config),
        "world_hashes": {world_id: world_hash(project_root, world_id, worlds_subdir=config.worlds_subdir, private_worlds_subdir=config.private_worlds_subdir) for world_id in sorted(worlds)},
        "provider": provider,
        "model_snapshot": model_snapshot,
        "worlds": list(worlds),
        "conditions": list(conditions),
        "repeats": repeats,
        "replicate_indices": list(range(repeats)) if replicate_indices is None else sorted({int(value) for value in replicate_indices}),
        "score_version": config.score_version,
        "source_tree_hash": source_tree_hash(project_root),
    }
    if request_namespace:
        value["request_namespace"] = request_namespace
    return value


def fingerprint_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
