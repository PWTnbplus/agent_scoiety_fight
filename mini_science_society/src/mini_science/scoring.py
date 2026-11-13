from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .public_loader import load_world
from .schema import ValidationResult, validate_final_question


AGENT_COUNTS = {
    "A_TARGET_ONLY": 1,
    "B_SINGLE_RELATED": 1,
    "C_SEQ2_TRANSFER": 2,
    "D_SEQ2_BLOCK": 2,
    "S_COLLAB3": 3,
    "S_COMPETE3": 3,
}


def _load_private(project_root: Path, world_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    private = project_root / "private" / "worlds" / world_id
    truth = json.loads((private / "hidden_truth.json").read_text(encoding="utf-8"))
    oracle = json.loads((private / "oracle_results.json").read_text(encoding="utf-8"))
    return truth, oracle


def evaluate_final(project_root: str | Path, world_id: str, view, final_raw: str, *, condition: str, provider: str, model_snapshot: str, replicate: int, input_tokens: int, output_tokens: int, api_calls: int, latency_ms: int, billed_cost: float | None, attributed_full_workflow_cost: float | None, run_status: str = "COMPLETED", invalid_reason: str = "", stage1: dict[str, Any] | None = None, transfer_applied: bool | None = None, stage1_artifact_sha256: str | None = None, forwarded_artifact_sha256: str | None = None) -> dict[str, Any]:
    project_root = Path(project_root)
    truth, oracle = _load_private(project_root, world_id)
    validation = validate_final_question(final_raw, view)
    selected_id = None
    question_text = ""
    top1_score = 0.0
    ig_selected = 0.0
    reason = invalid_reason or ("" if validation.valid else validation.reason)
    if validation.valid and validation.data is not None:
        selected_id = validation.data["experiment_id"]
        question_text = validation.data["scientific_question"]
        top1_score = float(oracle["top1_score"].get(selected_id, 0.0))
        ig_selected = float(oracle["ig_nats"].get(selected_id, 0.0))
    artifact = (stage1 or {}).get("parsed_artifact") or {}
    mapping = artifact.get("variable_mapping") if isinstance(artifact, dict) else {}
    mapping_valid = mapping == {"source_state": "target_state", "source_time": "target_time"}
    candidate_law_id = artifact.get("candidate_law_id", "") if isinstance(artifact, dict) else ""
    shared_law_judgment = artifact.get("shared_law_judgment", "") if isinstance(artifact, dict) else ""
    law_id_correct = bool(candidate_law_id and candidate_law_id == truth["true_law"])
    shared_law_correct = shared_law_judgment == "same" and law_id_correct
    return {
        "run_id": "",
        "experiment_id": "mini_society_pilot_v1",
        "world_id": world_id,
        "law_family": truth["true_law"],
        "seed": truth["seed"],
        "condition": condition,
        "society_type": "SINGLE" if condition.startswith(("A_", "B_")) else ("SEQ2" if condition.startswith(("C_", "D_")) else condition.replace("S_", "")),
        "agent_count": AGENT_COUNTS.get(condition, 0),
        "provider": provider,
        "model_snapshot": model_snapshot,
        "replicate": replicate,
        "question_text": question_text,
        "experiment_id_selected": selected_id or "",
        "valid": bool(validation.valid and run_status == "COMPLETED"),
        "invalid_reason": reason,
        "top1_score": top1_score if validation.valid and run_status == "COMPLETED" else 0.0,
        "ig_selected": ig_selected if validation.valid and run_status == "COMPLETED" else 0.0,
        "ig_star": float(oracle["ig_star"]),
        "shared_law_text": artifact.get("hypothesized_shared_law", "") if isinstance(artifact, dict) else "",
        "shared_law_judgment": shared_law_judgment,
        "candidate_law_id": candidate_law_id,
        "law_id_correct": law_id_correct,
        "shared_law_correct": shared_law_correct,
        "mapping_valid": mapping_valid,
        "transfer_applied": transfer_applied if transfer_applied is not None else "",
        "stage1_artifact_sha256": stage1_artifact_sha256 or "",
        "forwarded_artifact_sha256": forwarded_artifact_sha256 or "",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "api_calls": api_calls,
        "billed_cost": billed_cost,
        "attributed_full_workflow_cost": attributed_full_workflow_cost,
        "latency_ms": latency_ms,
        "run_status": run_status,
        "non_evidence": provider == "mock",
    }
