from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any


FORBIDDEN_PRIVATE_KEYS = {"true_law", "true_k", "hidden_truth", "oracle_results", "ig", "score", "oracle_best_experiment"}
PUBLIC_SOURCE_VARIABLES = ("source_state", "source_time")
PUBLIC_TARGET_VARIABLES = ("target_state", "target_time")
PUBLIC_VARIABLE_MAPPING = {"source_state": "target_state", "source_time": "target_time"}


@dataclass(frozen=True)
class WorldPublicView:
    world_id: str
    target_domain: str
    source_domain: str
    target_notes: str
    source_note: str
    candidate_models: tuple[str, ...]
    experiments: tuple[dict[str, Any], ...]
    measurement: str
    target_evidence_ids: tuple[str, ...]
    source_evidence_ids: tuple[str, ...]
    source_variable_ids: tuple[str, ...] = PUBLIC_SOURCE_VARIABLES
    target_variable_ids: tuple[str, ...] = PUBLIC_TARGET_VARIABLES

    @property
    def public_variable_schema(self) -> dict[str, tuple[str, ...]]:
        return {"source": self.source_variable_ids, "target": self.target_variable_ids}

    def prompt_payload(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "target_domain": self.target_domain,
            "source_domain": self.source_domain,
            "target_notes": self.target_notes,
            "source_note": self.source_note,
            "candidate_models": list(self.candidate_models),
            "experiments": [dict(item) for item in self.experiments],
            "measurement": self.measurement,
            "target_evidence_ids": list(self.target_evidence_ids),
            "source_evidence_ids": list(self.source_evidence_ids),
            "public_variable_schema": {
                "source": list(self.source_variable_ids),
                "target": list(self.target_variable_ids),
            },
        }


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str
    data: dict[str, Any] | None = None


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_json_object(raw: str) -> ValidationResult:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        return ValidationResult(False, f"invalid_json:{type(exc).__name__}")
    if not isinstance(value, dict):
        return ValidationResult(False, "json_not_object")
    return ValidationResult(True, "ok", value)


def validate_mapping(value: Any, view: WorldPublicView | None = None, *, relation: str = "same") -> ValidationResult:
    """Validate a public source-to-target mapping without judging its truth."""
    if relation in {"different", "unknown"} and value in ({}, None, "not_applicable"):
        return ValidationResult(True, "not_applicable", {"status": "not_applicable"})
    if not isinstance(value, dict):
        return ValidationResult(False, "invalid_variable_mapping")
    source_ids = tuple(view.source_variable_ids) if view is not None else PUBLIC_SOURCE_VARIABLES
    target_ids = tuple(view.target_variable_ids) if view is not None else PUBLIC_TARGET_VARIABLES
    if set(value) != set(source_ids):
        return ValidationResult(False, "variable_mapping_must_use_exact_public_fields")
    if any(not isinstance(key, str) or not isinstance(child, str) for key, child in value.items()):
        return ValidationResult(False, "variable_mapping_fields_must_be_strings")
    if any(child not in set(target_ids) for child in value.values()) or len(set(value.values())) != len(value):
        return ValidationResult(False, "variable_mapping_target_not_in_public_schema")
    return ValidationResult(True, "ok", dict(value))


def validate_selected_action(value: Any, view: WorldPublicView) -> ValidationResult:
    if not isinstance(value, dict):
        return ValidationResult(False, "missing_selected_action")
    if set(value) != {"experiment_id", "x0", "measure_t"}:
        return ValidationResult(False, "selected_action_must_have_exact_experiment_x0_measure_t")
    experiment = next((item for item in view.experiments if item.get("experiment_id") == value.get("experiment_id")), None)
    if experiment is None:
        return ValidationResult(False, "selected_action_experiment_not_in_menu")
    try:
        x0 = float(value["x0"])
        measure_t = float(value["measure_t"])
    except (TypeError, ValueError):
        return ValidationResult(False, "selected_action_parameters_not_numeric")
    if not math.isfinite(x0) or not math.isfinite(measure_t):
        return ValidationResult(False, "selected_action_parameters_not_finite")
    if abs(x0 - float(experiment["x0"])) > 1e-9 or abs(measure_t - float(experiment["measure_t"])) > 1e-9:
        return ValidationResult(False, "selected_action_parameters_mismatch")
    return ValidationResult(True, "ok", {"experiment_id": str(value["experiment_id"]), "x0": x0, "measure_t": measure_t})


def _has_forbidden_private_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_PRIVATE_KEYS:
                return True
            if _has_forbidden_private_key(child):
                return True
    elif isinstance(value, list):
        return any(_has_forbidden_private_key(child) for child in value)
    return False


def validate_shared_law(raw: str, view: WorldPublicView) -> ValidationResult:
    parsed = parse_json_object(raw)
    if not parsed.valid:
        return parsed
    assert parsed.data is not None
    value = parsed.data
    if _has_forbidden_private_key(value):
        return ValidationResult(False, "forbidden_private_field")
    if set(value).intersection({"experiment_id", "predicted_values", "ig", "ig_star", "oracle_best_experiment", "top1_score"}):
        return ValidationResult(False, "stage1_must_not_select_oracle_action")
    required = {"shared_law_judgment", "candidate_law_id", "hypothesized_shared_law", "source_evidence_ids", "target_evidence_ids", "variable_mapping", "status", "brief_justification"}
    missing = sorted(required - set(value))
    if missing:
        return ValidationResult(False, f"missing_fields:{','.join(missing)}")
    if value["shared_law_judgment"] not in {"same", "different", "unknown"}:
        return ValidationResult(False, "invalid_shared_law_judgment")
    if value["candidate_law_id"] != "UNKNOWN" and value["candidate_law_id"] not in view.candidate_models:
        return ValidationResult(False, "invalid_candidate_law_id")
    if not isinstance(value["source_evidence_ids"], list) or any(not isinstance(item, str) for item in value["source_evidence_ids"]) or not set(value["source_evidence_ids"]).issubset(set(view.source_evidence_ids)):
        return ValidationResult(False, "invalid_source_evidence_ids")
    if not isinstance(value["target_evidence_ids"], list) or any(not isinstance(item, str) for item in value["target_evidence_ids"]) or not set(value["target_evidence_ids"]).issubset(set(view.target_evidence_ids)):
        return ValidationResult(False, "invalid_target_evidence_ids")
    mapping_check = validate_mapping(value["variable_mapping"], view, relation=value["shared_law_judgment"])
    if not mapping_check.valid:
        return mapping_check
    return ValidationResult(True, "ok", value)


def validate_predicted_values(value: dict[str, Any], view: WorldPublicView) -> ValidationResult:
    predicted = value.get("predicted_values")
    if not isinstance(predicted, dict):
        return ValidationResult(False, "invalid_predicted_values")
    hypotheses = value.get("hypotheses_to_discriminate")
    if not isinstance(hypotheses, list) or len(hypotheses) < 2:
        return ValidationResult(False, "invalid_hypotheses_to_discriminate")
    candidate_models = set(view.candidate_models)
    if not set(predicted).issubset(candidate_models) or not set(hypotheses).issubset(set(predicted)):
        return ValidationResult(False, "predicted_values_missing_or_unknown_model")
    experiment = next((item for item in view.experiments if item.get("experiment_id") == value.get("experiment_id")), None)
    if experiment is None:
        return ValidationResult(False, "illegal_experiment_id")
    x0 = float(experiment["x0"])
    for model, number in predicted.items():
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(float(number)):
            return ValidationResult(False, f"invalid_predicted_value:{model}")
        if float(number) < 0.0 or float(number) > x0 + 1e-9:
            return ValidationResult(False, f"predicted_value_out_of_bounds:{model}")
    return ValidationResult(True, "ok", predicted)


def validate_final_question(raw: str, view: WorldPublicView, *, allowed_evidence_ids: set[str] | frozenset[str] | None = None, evidence_policy: Any | None = None, require_predicted_values: bool = False, require_selected_action: bool = False) -> ValidationResult:
    parsed = parse_json_object(raw)
    if not parsed.valid:
        return parsed
    assert parsed.data is not None
    value = parsed.data
    if _has_forbidden_private_key(value):
        return ValidationResult(False, "forbidden_private_field")
    required = {"experiment_id", "scientific_question", "hypotheses_to_discriminate", "measurement", "predicted_difference", "evidence_ids", "uncertainty"}
    missing = sorted(required - set(value))
    if missing:
        return ValidationResult(False, f"missing_fields:{','.join(missing)}")
    experiment_ids = {str(item["experiment_id"]) for item in view.experiments}
    if value["experiment_id"] not in experiment_ids:
        return ValidationResult(False, "illegal_experiment_id")
    if require_selected_action:
        action_check = validate_selected_action(value.get("selected_action"), view)
        if not action_check.valid:
            return action_check
    hypotheses = value["hypotheses_to_discriminate"]
    if not isinstance(hypotheses, list) or any(not isinstance(item, str) for item in hypotheses) or len(set(hypotheses)) < 2 or not set(hypotheses).issubset(set(view.candidate_models)):
        return ValidationResult(False, "invalid_hypotheses_to_discriminate")
    if value["measurement"] != view.measurement:
        return ValidationResult(False, "invalid_measurement")
    evidence = value["evidence_ids"]
    if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
        return ValidationResult(False, "invalid_evidence_ids")
    if evidence_policy is not None:
        allowed_evidence = set(evidence_policy.allowed_ids)
    elif allowed_evidence_ids is not None:
        allowed_evidence = set(allowed_evidence_ids)
    else:
        allowed_evidence = set(view.target_evidence_ids) | set(view.source_evidence_ids)
    if not set(evidence).issubset(allowed_evidence):
        if evidence_policy is not None:
            return ValidationResult(False, "unseen_evidence_reference")
        return ValidationResult(False, "invalid_evidence_ids")
    for field in ("scientific_question", "predicted_difference", "uncertainty"):
        if not isinstance(value[field], str) or not value[field].strip():
            return ValidationResult(False, f"invalid_{field}")
    if require_predicted_values:
        prediction_check = validate_predicted_values(value, view)
        if not prediction_check.valid:
            return prediction_check
    return ValidationResult(True, "ok", value)


def validate_judge_choice(raw: str, proposal_one: dict[str, Any], proposal_two: dict[str, Any], view: WorldPublicView, *, evidence_policy: Any | None = None) -> ValidationResult:
    parsed = parse_json_object(raw)
    if not parsed.valid or parsed.data is None:
        return parsed
    selected_proposer = parsed.data.get("selected_proposer_id")
    proposals = {"P1": proposal_one, "P2": proposal_two}
    if selected_proposer not in proposals:
        return ValidationResult(False, "invalid_selected_proposer_id", parsed.data)
    selected_experiment = parsed.data.get("experiment_id")
    if selected_experiment != proposals[selected_proposer].get("experiment_id"):
        return ValidationResult(False, "judge_selected_experiment_not_in_proposal", parsed.data)
    final_validation = validate_final_question(raw, view, evidence_policy=evidence_policy)
    if not final_validation.valid:
        return final_validation
    return ValidationResult(True, "ok", parsed.data)
