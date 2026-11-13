from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .metrics.prediction_audit import audit_prediction_values, public_nominal_k
from .public_loader import load_world
from .schema import ValidationResult, parse_json_object, validate_final_question, validate_mapping, validate_predicted_values, validate_selected_action
from .simulators import predict


AGENT_COUNTS = {
    "A_TARGET_ONLY": 1,
    "B_SINGLE_RELATED": 1,
    "C_SEQ2_TRANSFER": 2,
    "D_SEQ2_BLOCK": 2,
    "E_SEQ2_IRRELEVANT_TRANSFER": 2,
    "F_SEQ2_MISALIGNED_TRANSFER": 2,
    "S_COLLAB3": 3,
    "S_COMPETE3": 3,
}

GAP_THRESHOLD = 1.0


def _load_private(project_root: Path, world_id: str, *, private_worlds_subdir: str = "worlds") -> tuple[dict[str, Any], dict[str, Any]]:
    private = project_root / "private" / private_worlds_subdir / world_id
    truth = json.loads((private / "hidden_truth.json").read_text(encoding="utf-8"))
    oracle = json.loads((private / "oracle_results.json").read_text(encoding="utf-8"))
    return truth, oracle


def _prediction_gap(project_root: Path, world_id: str, view: Any, experiment_id: str | None, pair: list[str], *, worlds_subdir: str, private_worlds_subdir: str) -> float | None:
    if not experiment_id or len(pair) < 2 or any(model not in view.candidate_models for model in pair):
        return None
    experiment = next((item for item in view.experiments if str(item.get("experiment_id")) == str(experiment_id)), None)
    if experiment is None:
        return None
    truth, _ = _load_private(project_root, world_id, private_worlds_subdir=private_worlds_subdir)
    manifest = json.loads((project_root / "data" / worlds_subdir / world_id / "manifest.json").read_text(encoding="utf-8"))
    sigma = float(manifest.get("measurement_sigma", 0.04))
    predictions = [predict(model, float(experiment["x0"]), float(experiment["measure_t"]), float(truth["true_k"])) for model in pair]
    return abs(predictions[0] - predictions[1]) / sigma


def evaluate_final(project_root: str | Path, world_id: str, view, final_raw: str, *, condition: str, provider: str, model_snapshot: str, replicate: int, input_tokens: int | None, output_tokens: int | None, api_calls: int, latency_ms: int, billed_cost: float | None, attributed_full_workflow_cost: float | None, run_status: str = "COMPLETED", invalid_reason: str = "", stage1: dict[str, Any] | None = None, transfer_applied: bool | None = None, stage1_artifact_sha256: str | None = None, forwarded_artifact_sha256: str | None = None, evidence_policy: Any | None = None, worlds_subdir: str = "worlds", private_worlds_subdir: str = "worlds", contract_valid: bool = True, contract_invalid_reason: str = "", require_predicted_values: bool = False, require_selected_action: bool = False, separate_scientific_validity: bool = False, extra_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    project_root = Path(project_root)
    truth, oracle = _load_private(project_root, world_id, private_worlds_subdir=private_worlds_subdir)
    parsed = parse_json_object(final_raw)
    validation = validate_final_question(final_raw, view, evidence_policy=evidence_policy, require_predicted_values=(require_predicted_values and not separate_scientific_validity), require_selected_action=False)
    prediction_validation = ValidationResult(True, "not_required", validation.data)
    if separate_scientific_validity and validation.valid and validation.data is not None and require_predicted_values:
        prediction_validation = validate_predicted_values(validation.data, view)
    action_validation = validate_selected_action((validation.data or {}).get("selected_action"), view) if require_selected_action and validation.data is not None else ValidationResult(not require_selected_action, "not_required", None)
    execution_completed = run_status == "COMPLETED"
    scientific_output_available = bool(execution_completed and validation.valid and validation.data is not None)
    selected_id = None
    question_text = ""
    top1_score = 0.0
    ig_selected = 0.0
    reason = invalid_reason or (contract_invalid_reason if not contract_valid else ("" if validation.valid else validation.reason))
    scientific_numeric_valid = bool(prediction_validation.valid)
    action_valid = bool(action_validation.valid)
    selected_data = validation.data if validation.valid and validation.data is not None else None
    if selected_data is not None:
        selected_id = selected_data["experiment_id"]
        question_text = selected_data["scientific_question"]
        top1_score = float(oracle["top1_score"].get(selected_id, 0.0))
        ig_selected = float(oracle["ig_nats"].get(selected_id, 0.0))
    selected_pair = []
    predicted_gap = None
    prediction_text_structured = False
    prediction_audit = {"prediction_consistency": "NOT_CHECKED", "prediction_max_abs_error": None, "prediction_errors": {}}
    if validation.data is not None:
        selected_pair = [str(value) for value in validation.data.get("hypotheses_to_discriminate", [])]
        predicted_gap = _prediction_gap(project_root, world_id, view, selected_id, selected_pair, worlds_subdir=worlds_subdir, private_worlds_subdir=private_worlds_subdir)
        predicted_text = str(validation.data.get("predicted_difference", ""))
        prediction_text_structured = any(token in predicted_text.lower() for token in ("predict", "difference", "increase", "decrease", "higher", "lower")) or any(char.isdigit() for char in predicted_text)
        prediction_audit = audit_prediction_values(view, selected_id, selected_data.get("predicted_values"), nominal_k=public_nominal_k(view.target_notes))
    if separate_scientific_validity and require_predicted_values:
        scientific_numeric_valid = bool(prediction_validation.valid and prediction_audit.get("prediction_consistency") == "PASS")
    final_valid = bool(validation.valid and contract_valid and run_status == "COMPLETED" and scientific_numeric_valid and action_valid)
    artifact = (stage1 or {}).get("parsed_artifact") or {}
    mapping = artifact.get("variable_mapping") if isinstance(artifact, dict) else {}
    relation = str(artifact.get("shared_law_judgment", "")) if isinstance(artifact, dict) else ""
    mapping_valid = bool(validate_mapping(mapping, view, relation=relation).valid) if stage1 is not None else True
    candidate_law_id = artifact.get("candidate_law_id", "") if isinstance(artifact, dict) else ""
    shared_law_judgment = artifact.get("shared_law_judgment", "") if isinstance(artifact, dict) else ""
    law_id_correct = bool(candidate_law_id and candidate_law_id == truth["true_law"])
    shared_law_correct = shared_law_judgment == "same" and law_id_correct
    evidence_valid = bool(validation.valid)
    truth_checks = (stage1 or {}).get("truth_checks") or {}
    stage1_relation_correct = truth_checks.get("stage1_relation_correct", shared_law_correct if stage1 is not None else "")
    stage1_law_identification_correct = truth_checks.get("stage1_law_identification_correct", law_id_correct if stage1 is not None else "")
    stage1_mapping_correct = truth_checks.get("stage1_mapping_correct", mapping_valid if stage1 is not None else "")
    stage1_abstention_appropriate = truth_checks.get("stage1_abstention_appropriate", "")
    if stage1 is None:
        stage1_science_valid = True
    else:
        expected_relation = truth_checks.get("expected_relation", "same")
        stage1_science_valid = bool(stage1_relation_correct and ((stage1_law_identification_correct and stage1_mapping_correct) if expected_relation == "same" else stage1_abstention_appropriate))
    law_valid = stage1_science_valid if stage1 is not None else True
    selected_action = (selected_data or {}).get("selected_action")
    action_score = top1_score if action_valid else 0.0
    transport_valid = execution_completed
    fully_scientifically_valid = bool(transport_valid and validation.valid and contract_valid and evidence_valid and law_valid and mapping_valid and scientific_numeric_valid and action_valid and stage1_science_valid) if scientific_output_available else None
    if not scientific_output_available:
        top1_score = None
        ig_selected = None
        prediction_text_structured = None
        prediction_audit = {"prediction_consistency": "NOT_EVALUATED", "prediction_max_abs_error": None, "prediction_errors": {}, "prediction_error_categories": {}, "numeric_correct_count": None, "numeric_total_count": None}
        selected_pair = []
        predicted_gap = None
        selected_action = None
        action_valid = None
        scientific_numeric_valid = None
        action_score = None
        mapping_valid = None
        evidence_valid = None
        law_valid = None
        stage1_science_valid = None
        stage1_relation_valid = None
        stage1_relation_correct = None
        stage1_law_identification_correct = None
        stage1_mapping_correct = None
        stage1_abstention_appropriate = None
        shared_law_judgment = ""
        candidate_law_id = ""
        shared_law_correct = None
        law_id_correct = None
    result = {
        "run_id": "",
        "experiment_id": "mini_society_pilot_v1",
        "world_id": world_id,
        "law_family": truth["true_law"],
        "seed": truth["seed"],
        "condition": condition,
        "society_type": "SINGLE" if condition.startswith(("A_", "B_")) else ("SEQ2" if condition.startswith(("C_", "D_", "E_", "F_")) else condition.replace("S_", "")),
        "agent_count": AGENT_COUNTS.get(condition, 0),
        "provider": provider,
        "model_snapshot": model_snapshot,
        "replicate": replicate,
        "question_text": question_text,
        "experiment_id_selected": selected_id or "",
        "valid": final_valid,
        "invalid_reason": reason,
        "transport_success": transport_valid,
        "scientific_output_available": scientific_output_available,
        "format_valid": bool(parsed.valid) if scientific_output_available else None,
        "proposal_valid": bool(validation.valid and contract_valid) if scientific_output_available else None,
        "format_invalid_reason": parsed.reason if not parsed.valid and scientific_output_available else ("NOT_EVALUATED" if not scientific_output_available else ""),
        "proposal_invalid_reason": validation.reason if not validation.valid and scientific_output_available else (contract_invalid_reason if not contract_valid and scientific_output_available else ("NOT_EVALUATED" if not scientific_output_available else "")),
        "top1_score": top1_score if scientific_output_available and final_valid else (0.0 if scientific_output_available else None),
        "ig_selected": ig_selected if scientific_output_available and final_valid else (0.0 if scientific_output_available else None),
        "ig_star": float(oracle["ig_star"]),
        "selected_hypothesis_pair": json.dumps(selected_pair, ensure_ascii=False),
        "predicted_gap": predicted_gap,
        "pair_discrimination_pass": bool(predicted_gap is not None and predicted_gap >= GAP_THRESHOLD),
        "prediction_text_structured": prediction_text_structured,
        "predicted_values": json.dumps((validation.data or {}).get("predicted_values", {}), ensure_ascii=False, sort_keys=True) if scientific_output_available else "",
        "prediction_max_abs_error": prediction_audit.get("prediction_max_abs_error"),
        "prediction_consistency": prediction_audit.get("prediction_consistency"),
        "prediction_errors": json.dumps(prediction_audit.get("prediction_errors", {}), ensure_ascii=False, sort_keys=True),
        "prediction_error_categories": json.dumps(prediction_audit.get("prediction_error_categories", {}), ensure_ascii=False, sort_keys=True),
        "numeric_prediction_correct_count": prediction_audit.get("numeric_correct_count"),
        "numeric_prediction_total_count": prediction_audit.get("numeric_total_count"),
        "numeric_prediction_accuracy": ((float(prediction_audit.get("numeric_correct_count")) / float(prediction_audit.get("numeric_total_count"))) if prediction_audit.get("numeric_total_count") else None),
        "shared_law_text": artifact.get("hypothesized_shared_law", "") if isinstance(artifact, dict) else "",
        "shared_law_judgment": shared_law_judgment,
        "candidate_law_id": candidate_law_id,
        "law_id_correct": law_id_correct,
        "shared_law_correct": shared_law_correct,
        "mapping_valid": mapping_valid,
        "transport_valid": transport_valid,
        "schema_valid": bool(validation.valid) if scientific_output_available else None,
        "evidence_valid": evidence_valid,
        "law_valid": law_valid,
        "stage1_relation_valid": bool(stage1 is None or relation in {"same", "different", "unknown"}),
        "stage1_relation_correct": stage1_relation_correct,
        "stage1_law_identification_correct": stage1_law_identification_correct,
        "stage1_mapping_correct": stage1_mapping_correct,
        "stage1_abstention_appropriate": stage1_abstention_appropriate,
        "model_numeric_valid": scientific_numeric_valid,
        "action_valid": action_valid,
        "top1_action_score": action_score,
        "ig_selected_action": ig_selected if action_valid else (0.0 if scientific_output_available else None),
        "selected_action": json.dumps(selected_action, ensure_ascii=False, sort_keys=True) if selected_action is not None else "",
        "action_parameter_mismatch": action_validation.reason == "selected_action_parameters_mismatch" if scientific_output_available else None,
        "fully_scientifically_valid": fully_scientifically_valid,
        "transfer_applied": transfer_applied if transfer_applied is not None else "",
        "stage1_artifact_sha256": stage1_artifact_sha256 or "",
        "forwarded_artifact_sha256": forwarded_artifact_sha256 or "",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": (input_tokens + output_tokens) if input_tokens is not None and output_tokens is not None else None,
        "api_calls": api_calls,
        "billed_cost": billed_cost,
        "attributed_full_workflow_cost": attributed_full_workflow_cost,
        "latency_ms": latency_ms,
        "run_status": run_status,
        "non_evidence": provider in {"mock", "behavioral-mock"},
    }
    if extra_fields:
        result.update(extra_fields)
    return result
