from __future__ import annotations

"""Offline-verifiable provider and role-output contract checks."""

import json
from typing import Any

from .schema import ValidationResult, parse_json_object, validate_final_question, validate_shared_law


def _returned_model(response: Any) -> str | None:
    metadata = getattr(response, "metadata", {}) or {}
    value = metadata.get("returned_model")
    return str(value) if value else None


def usage_source(response: Any) -> str:
    metadata = getattr(response, "metadata", {}) or {}
    if metadata.get("usage_verified") is True:
        return "provider_usage"
    if getattr(response, "input_tokens", None) is not None and getattr(response, "output_tokens", None) is not None:
        return "ESTIMATED"
    return "MISSING"


def billing_source(response: Any) -> str:
    metadata = getattr(response, "metadata", {}) or {}
    if metadata.get("provider_billing_verified"):
        return "PROVIDER_BILL"
    return "UNVERIFIED"


def response_is_truncated(response: Any) -> bool:
    metadata = getattr(response, "metadata", {}) or {}
    finish_reason = str(metadata.get("finish_reason") or "").lower()
    return finish_reason in {"length", "max_tokens", "truncated"} or bool(metadata.get("truncated"))


def check_api_response(response: Any, *, requested_model: str, request_attempts: int = 1) -> dict[str, Any]:
    raw = getattr(response, "text", "") or ""
    parsed = parse_json_object(raw)
    contract_json_valid = bool(parsed.valid and parsed.data and parsed.data.get("status") == "ok")
    returned_model = _returned_model(response)
    if returned_model is None:
        model_status = "MODEL_ID_UNVERIFIED"
    elif returned_model != requested_model:
        model_status = "MODEL_ID_MISMATCH"
    else:
        model_status = "MODEL_ID_VERIFIED"
    usage = usage_source(response)
    truncated = response_is_truncated(response)
    if not contract_json_valid or model_status == "MODEL_ID_MISMATCH" or truncated:
        gate_result = "FAIL"
    elif model_status != "MODEL_ID_VERIFIED" or usage != "provider_usage":
        gate_result = "UNVERIFIED"
    else:
        gate_result = "PASS"
    return {
        "provider": (getattr(response, "metadata", {}) or {}).get("provider"),
        "requested_model": requested_model,
        "returned_model": returned_model,
        "contract_json_valid": contract_json_valid,
        "response_status_ok": bool(parsed.valid and parsed.data and parsed.data.get("status") == "ok"),
        "model_status": model_status,
        "usage_source": usage,
        "billing_source": billing_source(response),
        "request_attempts": request_attempts,
        "truncated": truncated,
        "response_hash": __import__("hashlib").sha256(raw.encode("utf-8")).hexdigest(),
        "gate_result": gate_result,
        "error_code": "TRUNCATED_OUTPUT" if truncated else ("" if parsed.valid else parsed.reason),
    }


def role_response_check(response: Any, *, role: str, view: Any, requested_model: str) -> dict[str, Any]:
    raw = getattr(response, "text", "") or ""
    if role == "pattern_extractor":
        validation: ValidationResult = validate_shared_law(raw, view)
    else:
        validation = validate_final_question(raw, view)
    truncated = response_is_truncated(response)
    status = "TRUNCATED_OUTPUT" if truncated else ("PASS" if validation.valid else "FAIL")
    data = validation.data or {}
    return {
        "role": role,
        "requested_model": requested_model,
        "returned_model": _returned_model(response),
        "json_valid": parse_json_object(raw).valid,
        "schema_valid": validation.valid,
        "validation_reason": validation.reason,
        "gate_result": status,
        "truncated": truncated,
        "usage_source": usage_source(response),
        "billing_source": billing_source(response),
        "candidate_law_id": data.get("candidate_law_id") if role == "pattern_extractor" else None,
        "shared_law_judgment": data.get("shared_law_judgment") if role == "pattern_extractor" else None,
        "selected_experiment_id": data.get("experiment_id") if role != "pattern_extractor" else None,
        "response_hash": __import__("hashlib").sha256(raw.encode("utf-8")).hexdigest(),
    }
