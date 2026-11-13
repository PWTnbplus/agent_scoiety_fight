from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


FORBIDDEN_PRIVATE_KEYS = {"true_law", "true_k", "hidden_truth", "oracle_results", "ig", "score", "oracle_best_experiment"}


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
    required = {"shared_law_judgment", "candidate_law_id", "hypothesized_shared_law", "source_evidence_ids", "target_evidence_ids", "variable_mapping", "status", "brief_justification"}
    missing = sorted(required - set(value))
    if missing:
        return ValidationResult(False, f"missing_fields:{','.join(missing)}")
    if value["shared_law_judgment"] not in {"same", "different", "unknown"}:
        return ValidationResult(False, "invalid_shared_law_judgment")
    if value["candidate_law_id"] != "UNKNOWN" and value["candidate_law_id"] not in view.candidate_models:
        return ValidationResult(False, "invalid_candidate_law_id")
    if not isinstance(value["source_evidence_ids"], list) or not set(value["source_evidence_ids"]).issubset(set(view.source_evidence_ids)):
        return ValidationResult(False, "invalid_source_evidence_ids")
    if not isinstance(value["target_evidence_ids"], list) or not set(value["target_evidence_ids"]).issubset(set(view.target_evidence_ids)):
        return ValidationResult(False, "invalid_target_evidence_ids")
    if not isinstance(value["variable_mapping"], dict):
        return ValidationResult(False, "invalid_variable_mapping")
    return ValidationResult(True, "ok", value)


def validate_final_question(raw: str, view: WorldPublicView) -> ValidationResult:
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
    hypotheses = value["hypotheses_to_discriminate"]
    if not isinstance(hypotheses, list) or len(set(hypotheses)) < 2 or not set(hypotheses).issubset(set(view.candidate_models)):
        return ValidationResult(False, "invalid_hypotheses_to_discriminate")
    if value["measurement"] != view.measurement:
        return ValidationResult(False, "invalid_measurement")
    evidence = value["evidence_ids"]
    allowed_evidence = set(view.target_evidence_ids) | set(view.source_evidence_ids)
    if not isinstance(evidence, list) or not set(evidence).issubset(allowed_evidence):
        return ValidationResult(False, "invalid_evidence_ids")
    for field in ("scientific_question", "predicted_difference", "uncertainty"):
        if not isinstance(value[field], str) or not value[field].strip():
            return ValidationResult(False, f"invalid_{field}")
    return ValidationResult(True, "ok", value)
