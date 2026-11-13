from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import random
from typing import Any

from .adapters.base import LLMResponse, ProviderAdapter
from .adapters.behavioral_mock import BehavioralMockAdapter
from .adapters.existing_project import ExistingProjectAdapter
from .adapters.kimi26 import Kimi26Adapter
from .adapters.mock import MockAdapter
from .analysis import read_results, write_report, write_results
from .budget import BudgetExceeded, BudgetTracker, estimate_tokens
from .budget_plan import pilot_request_plan, probe_request_plan
from .config import ExperimentConfig
from .evidence_policy import EvidencePolicy, policy_for_route
from .experiment_plan import build_plan, fingerprint_hash, read_plan, run_fingerprint, write_plan
from .public_loader import load_world
from .prompts import seq2_stage1_messages, seq2_stage2_messages, single_messages
from .prompt_audit import assert_prompt_blinded
from .protocol_checks import response_is_truncated, role_response_check
from .real_gate import PersistentRealGate, V4SessionGate, V5P4SessionGate, V5P8SessionGate, V5P11SessionGate, GateReservation
from .real_reports import write_g2_report, write_g3_report
from .schema import parse_json_object, sha256_json, validate_mapping
from .security import redact_for_log
from .scoring import evaluate_final
from .societies import collab3, compete3, seq2, single


SEQ2_CONDITIONS = frozenset({"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK", "E_SEQ2_IRRELEVANT_TRANSFER", "F_SEQ2_MISALIGNED_TRANSFER"})


def _is_v5_contract(config: ExperimentConfig) -> bool:
    return str(config.score_version).startswith(("v5p2", "v5p3", "v5p4", "v5p8", "v5p11"))


def _should_write_legacy_g3_report(config: ExperimentConfig, provider: str) -> bool:
    """Keep the V3 report writer away from versioned V5 evidence trees."""
    return provider in {"existing", "kimi26"} and not _is_v5_contract(config)


def _protocol_version(config: ExperimentConfig) -> str:
    score_version = str(config.score_version)
    if score_version.startswith("v5p11"):
        return "v5p11"
    if score_version.startswith("v5p8"):
        return "v5p8"
    if score_version.startswith("v5p4"):
        return "v5p4"
    if score_version.startswith("v5p3"):
        return "v5p3"
    if score_version.startswith("v5p2"):
        return "v5p2"
    return "v4"


def _response_meta(response: LLMResponse | None) -> dict[str, Any]:
    if response is None:
        return {}
    return {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
        "cost_usd": response.cost_usd,
        "metadata": response.metadata,
    }


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact_for_log(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_for_log(value), ensure_ascii=False, sort_keys=True) + "\n")


def _numeric(response: LLMResponse | None, field: str) -> int | None:
    if response is None:
        return None
    value = getattr(response, field, None)
    return int(value) if value is not None else None


def _sum_known(responses: list[LLMResponse | None], field: str) -> int | None:
    values = [_numeric(response, field) for response in responses if response is not None]
    if not values or any(value is None for value in values):
        return None
    return sum(int(value) for value in values if value is not None)


def _estimated_cost(responses: list[LLMResponse | None]) -> float | None:
    values = [response.cost_usd for response in responses if response is not None and response.cost_usd is not None]
    return sum(float(value) for value in values) if values else None


def _provider_billed_cost(responses: list[LLMResponse | None]) -> float | None:
    values: list[float] = []
    for response in responses:
        if response is None:
            continue
        metadata = response.metadata or {}
        if metadata.get("provider_billing_verified") and metadata.get("provider_billed_cost_usd") is not None:
            values.append(float(metadata["provider_billed_cost_usd"]))
    return sum(values) if values else None


class CallRecorder:
    """Record every provider attempt without exposing authentication data."""

    def __init__(
        self,
        adapter: ProviderAdapter,
        tracker: BudgetTracker,
        events_path: Path,
        *,
        ledger_path: Path,
        run_id: str,
        world_id: str,
        condition: str,
        replicate: int,
        pair_id: str,
        stage: str,
        attempt_counts: dict[str, int],
        shared_call_id: str | None = None,
        global_gate: Any = None,
        global_provider: str | None = None,
        global_stage: str | None = None,
        enforce_prompt_blinding: bool = False,
    ) -> None:
        self.adapter = adapter
        self.tracker = tracker
        self.events_path = events_path
        self.ledger_path = ledger_path
        self.run_id = run_id
        self.world_id = world_id
        self.condition = condition
        self.replicate = replicate
        self.pair_id = pair_id
        self.stage = stage
        self.attempt_counts = attempt_counts
        self.shared_call_id = shared_call_id
        self.global_gate = global_gate
        self.global_provider = global_provider
        self.global_stage = global_stage
        self.enforce_prompt_blinding = enforce_prompt_blinding

    def event(self, event_type: str, **values: Any) -> None:
        _append_jsonl(self.events_path, {
            "event_type": event_type,
            "run_id": self.run_id,
            "world_id": self.world_id,
            "condition": self.condition,
            "replicate": self.replicate,
            "pair_id": self.pair_id,
            **values,
        })

    def __call__(self, agent_name: str, messages: list[dict[str, str]], max_output_tokens: int) -> LLMResponse:
        if self.enforce_prompt_blinding:
            assert_prompt_blinded(messages, stage=self.stage)
        request_hash = sha256_json(messages)
        request_id = f"{self.pair_id}:{self.condition}:{self.stage}:{agent_name}"
        attempt_number = self.attempt_counts.get(request_id, 0) + 1
        self.attempt_counts[request_id] = attempt_number
        call_id = f"{request_id}:attempt{attempt_number}"
        estimated_input = estimate_tokens(json.dumps(messages, ensure_ascii=False))
        self.tracker.before_call(estimated_input, max_output_tokens)
        reservation: GateReservation | None = None
        estimated_cost = None
        if self.global_gate is not None:
            input_rate = float(getattr(self.adapter, "input_cost_per_1k", 0.00095))
            output_rate = float(getattr(self.adapter, "output_cost_per_1k", 0.004))
            estimated_cost = (estimated_input / 1000.0) * input_rate + (max_output_tokens / 1000.0) * output_rate
            gate_stage = self.stage if isinstance(self.global_gate, V5P4SessionGate) else (self.global_stage or self.stage)
            reserve_kwargs = {"request_id": call_id, "provider": self.global_provider or "unknown", "model": getattr(self.adapter, "model_name", "unknown"), "stage": gate_stage, "estimated_cost_usd": estimated_cost, "world_id": self.world_id, "condition": self.condition}
            if isinstance(self.global_gate, V5P4SessionGate):
                reserve_kwargs["max_output_tokens"] = max_output_tokens
            reservation = self.global_gate.reserve(**reserve_kwargs)
        started = datetime.now(timezone.utc)
        self.event("STAGE1_REQUEST" if self.stage == "stage1" else "STAGE2_REQUEST", agent_name=agent_name, request_hash=request_hash, request_id=request_id, call_id=call_id, max_output_tokens=max_output_tokens, request=messages, status="started")
        try:
            response = self.adapter.complete(messages, max_output_tokens)
            if self.global_gate is not None:
                metadata = response.metadata or {}
                if metadata.get("returned_model") != getattr(self.adapter, "model_name", None):
                    raise RuntimeError("MODEL_ID_UNVERIFIED_OR_MISMATCH")
                if metadata.get("usage_verified") is not True or response.input_tokens is None or response.output_tokens is None:
                    raise RuntimeError("USAGE_UNVERIFIED")
                if response_is_truncated(response):
                    raise RuntimeError("TRUNCATED_OUTPUT")
            self.tracker.record(response)
            provider_billed = _provider_billed_cost([response])
            status = "completed"
            record = {
                "call_id": call_id,
                "attempt_id": f"{call_id}",
                "request_id": request_id,
                "run_id": self.run_id,
                "pair_id": self.pair_id,
                "world_id": self.world_id,
                "replicate": self.replicate,
                "condition": self.condition,
                "stage": self.stage,
                "agent_name": agent_name,
                "model_snapshot": response.model,
                "model_requested": getattr(self.adapter, "model_name", response.model),
                "returned_model": (response.metadata or {}).get("returned_model"),
                "finish_reason": (response.metadata or {}).get("finish_reason"),
                "request_hash": request_hash,
                "response_hash": sha256_json(response.text),
                "actual_input_tokens": response.input_tokens,
                "actual_output_tokens": response.output_tokens,
                "request_input_token_estimate": estimated_input,
                "max_output_tokens": max_output_tokens,
                "usage_source": "provider_usage" if response.input_tokens is not None and response.output_tokens is not None else "USAGE_UNVERIFIED",
                "price_source": (response.metadata or {}).get("cost_basis", "LOCAL_ESTIMATE"),
                "billing_source": "PROVIDER_BILL" if provider_billed is not None else "UNVERIFIED",
                "estimated_cost_usd": estimated_cost,
                "reserved_estimated_cost_usd": estimated_cost,
                "local_response_estimate_usd": response.cost_usd,
                "provider_billed_cost_usd": provider_billed,
                "unique_billable_call": True,
                "shared_call_id": self.shared_call_id,
                "latency_ms": response.latency_ms,
                "request_status": status,
                "http_status": (response.metadata or {}).get("http_status"),
                "failure_kind": None,
                "budget_verified": self.tracker.budget_verified,
                "over_budget": self.tracker.over_budget,
                "started_at": started.isoformat(),
            }
            _append_jsonl(self.ledger_path, record)
            if reservation is not None:
                self.global_gate.finish(reservation, status="COMPLETED", actual_cost_usd=provider_billed, billing_verified=provider_billed is not None, returned_model=(response.metadata or {}).get("returned_model"))
            self.event("STAGE1_RESPONSE" if self.stage == "stage1" else "STAGE2_RESPONSE", agent_name=agent_name, request_hash=request_hash, response_hash=sha256_json(response.text), call_id=call_id, model_snapshot=response.model, input_tokens=response.input_tokens, output_tokens=response.output_tokens, usage_source=record["usage_source"], response=response.text, status=status, latency_ms=response.latency_ms)
            return response
        except Exception as exc:
            self.tracker.record_failure()
            record = {
                "call_id": call_id,
                "attempt_id": call_id,
                "request_id": request_id,
                "run_id": self.run_id,
                "pair_id": self.pair_id,
                "world_id": self.world_id,
                "replicate": self.replicate,
                "condition": self.condition,
                "stage": self.stage,
                "agent_name": agent_name,
                "model_snapshot": getattr(self.adapter, "model_name", "unknown"),
                "model_requested": getattr(self.adapter, "model_name", "unknown"),
                "returned_model": None,
                "finish_reason": None,
                "request_hash": request_hash,
                "response_hash": None,
                "actual_input_tokens": None,
                "actual_output_tokens": None,
                "request_input_token_estimate": estimated_input,
                "max_output_tokens": max_output_tokens,
                "usage_source": "USAGE_UNVERIFIED",
                "price_source": None,
                "billing_source": "UNVERIFIED",
                "estimated_cost_usd": estimated_cost,
                "provider_billed_cost_usd": None,
                "unique_billable_call": True,
                "shared_call_id": self.shared_call_id,
                "latency_ms": None,
                "request_status": f"failed:{type(exc).__name__}",
                "http_status": getattr(exc, "http_status", None),
                "failure_kind": getattr(exc, "failure_kind", type(exc).__name__),
                "reason_type": getattr(exc, "reason_type", ""),
                "detail_code": getattr(exc, "detail_code", ""),
                "error_elapsed_ms": getattr(exc, "elapsed_ms", None),
                "budget_verified": False,
                "over_budget": isinstance(exc, BudgetExceeded),
                "error": str(exc)[:500],
                "started_at": started.isoformat(),
            }
            _append_jsonl(self.ledger_path, record)
            if reservation is not None:
                gate_status = "FAILED"
                if isinstance(self.global_gate, V5P4SessionGate) and getattr(exc, "failure_kind", "") in {"TIMEOUT", "AMBIGUOUS_POST_OUTCOME"}:
                    gate_status = "UNKNOWN_BILLING_OUTCOME"
                self.global_gate.finish(reservation, status=gate_status, actual_cost_usd=None, billing_verified=False, returned_model=None, error=str(exc)[:500])
            self.event("STAGE1_RESPONSE" if self.stage == "stage1" else "STAGE2_RESPONSE", agent_name=agent_name, request_hash=request_hash, call_id=call_id, status="failed", error_or_status=f"{type(exc).__name__}:{str(exc)[:500]}")
            raise


def make_adapter(provider: str, allow_paid_api: bool, *, config: ExperimentConfig | None = None, key_file: str | Path | None = None, base_url: str | None = None, timeout: float | None = None, max_cost_usd: float | None = None, max_output_tokens: int = 1200, behavioral_scenario: str = "constant") -> ProviderAdapter:
    if provider == "mock":
        return MockAdapter()
    if provider == "behavioral-mock":
        return BehavioralMockAdapter(behavioral_scenario)
    if provider == "existing":
        return ExistingProjectAdapter(allow_paid_api=allow_paid_api)
    if provider == "kimi26":
        source_project = config.api_source_project if config and config.api_source_project else None
        return Kimi26Adapter(allow_paid_api=allow_paid_api, key_file=key_file, source_project=source_project, base_url=base_url, timeout=timeout, max_cost_usd=max_cost_usd, max_output_tokens=max_output_tokens)
    raise ValueError(f"unknown provider: {provider}")


def _condition_view(project_root: Path, world_id: str, condition: str, config: ExperimentConfig):
    source_variant = "irrelevant" if condition == "A_TARGET_ONLY" else "related"
    return load_world(project_root, world_id, source_variant=source_variant, worlds_subdir=config.worlds_subdir)


def _artifact_dir(run_dir: Path, world_id: str, condition: str, replicate: int) -> Path:
    path = run_dir / "agent_artifacts" / world_id / f"replicate_{replicate}" / condition
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_response(path: Path, response: LLMResponse | None, extra: dict[str, Any] | None = None) -> None:
    value = {"raw_text": response.text if response else None, "response": _response_meta(response)}
    if extra:
        value.update(extra)
    _json_write(path, value)


def _response_from_payload(payload: dict[str, Any]) -> LLMResponse | None:
    raw_text = payload.get("raw_text") or ""
    if not raw_text:
        return None
    meta = payload.get("response") or {}
    return LLMResponse(
        text=raw_text,
        model=str(meta.get("model", "unknown")),
        input_tokens=meta.get("input_tokens"),
        output_tokens=meta.get("output_tokens"),
        latency_ms=int(meta.get("latency_ms", 0) or 0),
        cost_usd=meta.get("cost_usd"),
        metadata=meta.get("metadata") or {},
    )


def _load_cached_stage1(run_dir: Path, world_id: str, replicate: int, owner_condition: str) -> dict[str, Any] | None:
    path = _artifact_dir(run_dir, world_id, owner_condition, replicate) / "stage1.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "raw_text": payload.get("raw_text") or "",
        "parsed_artifact": payload.get("parsed_artifact") or {},
        "valid": bool(payload.get("valid", False)),
        "reason": str(payload.get("reason", "cached")),
        "response": _response_from_payload(payload),
        "owner_condition": owner_condition,
        "stage1_artifact_sha256": payload.get("stage1_artifact_sha256") or sha256_json(payload.get("parsed_artifact") or {}),
    }


def _emit(path: Path, event_type: str, **values: Any) -> None:
    _append_jsonl(path, {"event_type": event_type, **values})


def _route_for_condition(condition: str) -> tuple[bool, str]:
    if condition == "D_SEQ2_BLOCK":
        return False, "blocked"
    if condition == "E_SEQ2_IRRELEVANT_TRANSFER":
        return True, "irrelevant"
    if condition == "F_SEQ2_MISALIGNED_TRANSFER":
        return True, "misaligned"
    return True, "real"


def _analysis_key(row: dict[str, Any], config_hash: str) -> tuple[str, str, str, str, str]:
    return (str(row.get("world_id")), str(row.get("replicate")), str(row.get("model_snapshot")), config_hash, str(row.get("condition")))


def _append_attempt_result(path: Path, row: dict[str, Any]) -> None:
    _append_jsonl(path, {"attempt_type": "primary_or_retry", "recorded_at": datetime.now(timezone.utc).isoformat(), "row": row})


def _upsert_primary(rows: list[dict[str, Any]], row: dict[str, Any], config_hash: str, *, retry_failed: bool) -> None:
    key = _analysis_key(row, config_hash)
    for index, existing in enumerate(rows):
        if _analysis_key(existing, config_hash) != key:
            continue
        if retry_failed and str(existing.get("run_status")) != "COMPLETED":
            rows[index] = row
            return
        return
    rows.append(row)


def _real_result_failure_reason(row: dict[str, Any], *, require_stage1_mapping: bool = False) -> str | None:
    """Apply the hard scientific gates required before another paid call."""
    if not bool(row.get("valid")):
        return f"stage2_result_invalid:{row.get('invalid_reason', 'invalid_result')}"
    if str(row.get("prediction_consistency", "")).upper() != "PASS":
        return "stage2_numeric_consistency_failure"
    if require_stage1_mapping and not bool(row.get("mapping_valid")):
        return "stage1_mapping_check_failed"
    return None


def _stage1_has_action_oracle_leak(artifact: dict[str, Any]) -> bool:
    serialized = json.dumps(artifact, ensure_ascii=False).lower()
    forbidden_action_markers = tuple(f"e0{index}" for index in range(1, 9))
    forbidden_private_markers = ("oracle", "ig_star", "best_experiment", "predicted_values")
    return any(marker.lower() in serialized for marker in forbidden_action_markers + forbidden_private_markers)


def stage1_truth_checks(artifact: dict[str, Any], truth: dict[str, Any], view: Any) -> dict[str, Any]:
    """Compare a valid public Stage1 artifact with private relation metadata."""
    relation = str(artifact.get("shared_law_judgment", ""))
    expected_relation = str(truth.get("expected_relation", "same"))
    expected_law = str(truth.get("expected_candidate_law_id", truth.get("true_law", "UNKNOWN")))
    mapping_check = validate_mapping(artifact.get("variable_mapping"), view, relation=relation)
    expected_mapping = truth.get("oracle_mapping")
    mapping_correct = bool(truth.get("mapping_identifiable", False) and isinstance(expected_mapping, dict) and artifact.get("variable_mapping") == expected_mapping)
    relation_correct = relation == expected_relation
    law_correct = relation == "same" and artifact.get("candidate_law_id") == expected_law
    abstention_appropriate = expected_relation != "same" and relation in {"different", "unknown"} and artifact.get("candidate_law_id") in {"UNKNOWN", expected_law}
    return {
        "mapping_schema_valid": mapping_check.valid,
        "stage1_relation_correct": relation_correct,
        "stage1_law_identification_correct": law_correct,
        "stage1_mapping_correct": mapping_correct,
        "stage1_abstention_appropriate": abstention_appropriate,
        "expected_relation": expected_relation,
        "expected_candidate_law_id": expected_law,
        "mapping_identifiable": bool(truth.get("mapping_identifiable", False)),
    }


def _execute_stage1(
    *,
    project_root: Path,
    config: ExperimentConfig,
    run_dir_path: Path,
    adapter: ProviderAdapter,
    events_path: Path,
    ledger_path: Path,
    run_id: str,
    world_id: str,
    replicate: int,
    owner: str,
    pair_id: str,
    attempt_counts: dict[str, int],
    real_gate: Any,
    provider: str,
    is_real_provider: bool,
) -> tuple[dict[str, Any], LLMResponse | None, str | None]:
    cached = _load_cached_stage1(run_dir_path, world_id, replicate, owner)
    if cached is not None:
        return cached, cached.get("response"), None
    view = load_world(project_root, world_id, "related", worlds_subdir=config.worlds_subdir)
    tracker = BudgetTracker(config.max_total_tokens_per_condition, max(1, config.max_agent_model_calls))
    recorder = CallRecorder(adapter, tracker, events_path, ledger_path=ledger_path, run_id=run_id, world_id=world_id, condition=owner, replicate=replicate, pair_id=pair_id, stage="stage1", attempt_counts=attempt_counts, global_gate=real_gate, global_provider=provider, global_stage="pilot", enforce_prompt_blinding=str(config.score_version).startswith(("v5p4", "v5p8", "v5p11")))
    try:
        protocol_version = _protocol_version(config)
        response, validation = seq2.extract_stage1(view, recorder, max_output_tokens=600 if str(config.score_version).startswith(("v4", "v5p")) else 450, protocol_version=protocol_version)
        artifact = validation.data or {}
        cache = {"raw_text": response.text, "parsed_artifact": artifact, "valid": validation.valid, "reason": validation.reason, "response": response, "owner_condition": owner, "stage1_artifact_sha256": sha256_json(artifact), "truth_checks": {}}
        _save_response(_artifact_dir(run_dir_path, world_id, owner, replicate) / "stage1.json", response, {"parsed_artifact": artifact, "valid": validation.valid, "reason": validation.reason, "stage1_artifact_sha256": sha256_json(artifact)})
        _emit(events_path, "STAGE1_PARSE", run_id=run_id, world_id=world_id, replicate=replicate, pair_id=pair_id, stage1_artifact_sha256=sha256_json(artifact), status="parsed")
        _emit(events_path, "STAGE1_VALIDATION", run_id=run_id, world_id=world_id, replicate=replicate, pair_id=pair_id, valid=validation.valid, reason=validation.reason, status="completed")
    except Exception as exc:
        cache = {"raw_text": "", "parsed_artifact": {}, "valid": False, "reason": f"{type(exc).__name__}:{str(exc)[:500]}", "response": None, "owner_condition": owner, "stage1_artifact_sha256": sha256_json({})}
        _save_response(_artifact_dir(run_dir_path, world_id, owner, replicate) / "stage1.json", None, {"parsed_artifact": {}, "valid": False, "reason": cache["reason"], "stage1_artifact_sha256": sha256_json({})})
        _emit(events_path, "STAGE1_VALIDATION", run_id=run_id, world_id=world_id, replicate=replicate, pair_id=pair_id, valid=False, reason=cache["reason"], status="failed")
        return cache, None, f"stage1_provider_failure:{cache['reason']}" if is_real_provider else None
    if is_real_provider:
        if not bool(cache.get("valid")):
            # V5-P4: an invalid scientific output is part of the experiment,
            # not a network, budget or identity failure. Retain neutral Stage1
            # and collect the paired C/D experimental outcomes.
            if str(config.score_version).startswith(("v5p4", "v5p8", "v5p11")):
                _emit(events_path, "STAGE1_SCIENTIFIC_INVALID", run_id=run_id,
                      world_id=world_id, replicate=replicate, pair_id=pair_id,
                      reason=cache.get("reason", "invalid_stage1"), status="recorded")
                return cache, response, None
            return cache, response, f"stage1_schema_failure:{cache.get('reason', 'invalid_stage1')}"
        truth_path = project_root / "private" / config.private_worlds_subdir / world_id / "hidden_truth.json"
        if not truth_path.exists():
            return cache, response, "stage1_oracle_unavailable"
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        artifact = cache.get("parsed_artifact") or {}
        truth_checks = stage1_truth_checks(artifact, truth, view)
        if not truth_checks["mapping_schema_valid"]:
            if str(config.score_version).startswith(("v5p4", "v5p8", "v5p11")):
                _emit(events_path, "STAGE1_SCIENTIFIC_INVALID", run_id=run_id,
                      world_id=world_id, replicate=replicate, pair_id=pair_id,
                      reason="stage1_mapping_check_failed", status="recorded")
            else:
                return cache, response, "stage1_mapping_check_failed"
        cache["truth_checks"] = truth_checks
        if str(config.score_version).startswith(("v5p3", "v5p4", "v5p8", "v5p11")):
            # A valid but scientifically wrong judgment is retained as a
            # scientific failure; only protocol/security failures stop calls.
            pass
        elif artifact.get("candidate_law_id") != truth.get("true_law") or artifact.get("shared_law_judgment") != "same":
            return cache, response, "stage1_key_law_check_failed"
        if str(config.score_version).startswith(("v5p2", "v5p3", "v5p4", "v5p8", "v5p11")) and _stage1_has_action_oracle_leak(artifact):
            return cache, response, "stage1_action_oracle_leak"
    return cache, response, None


def _manifest_for_run(project_root: Path, run_dir: Path, config: ExperimentConfig, *, provider: str, adapter: ProviderAdapter, worlds: list[str], conditions: list[str], repeats: int, request_namespace: str | None = None, replicate_indices: list[int] | None = None, allow_paid_api: bool = False, gate: PersistentRealGate | None = None) -> tuple[dict[str, Any], str]:
    fingerprint = run_fingerprint(project_root, config, provider=provider, model_snapshot=adapter.model_name, worlds=worlds, conditions=conditions, repeats=repeats, request_namespace=request_namespace, replicate_indices=replicate_indices)
    fingerprint_digest = fingerprint_hash(fingerprint)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_digest = manifest.get("fingerprint_hash")
        if old_digest and old_digest != fingerprint_digest:
            raise RuntimeError("manifest mismatch: configuration, worlds, provider, model, or source code changed; create a new run")
        return manifest, fingerprint_digest
    run_id = run_dir.name
    manifest = {
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "provider": provider,
        "model_snapshot": adapter.model_name,
        "worlds": worlds,
        "conditions": conditions,
        "repeats": repeats,
        "replicate_indices": list(range(repeats)) if replicate_indices is None else list(replicate_indices),
        "config": config.to_dict(),
        "config_hash": fingerprint["config_hash"],
        "world_hashes": fingerprint["world_hashes"],
        "source_tree_hash": fingerprint["source_tree_hash"],
        "fingerprint": fingerprint,
        "fingerprint_hash": fingerprint_digest,
        "call_policy": {
            "allow_paid_api": bool(allow_paid_api),
            "authorization_status": config.authorization_status,
            "authorized_provider": config.authorized_provider,
            "authorized_model": config.authorized_model,
            "max_unique_calls": config.max_unique_calls,
            "max_estimated_cost_usd": config.max_estimated_cost_usd,
            "max_tokens": config.max_tokens,
            "real_api_status": "NOT_RUN",
            "gate_state_path": str(gate.state_path) if gate is not None else None,
        },
        "score_version": config.score_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "planned_primary_units": len(worlds) * (len(replicate_indices) if replicate_indices is not None else repeats) * len(conditions),
        "scientific_status": "ENGINEERING_PILOT_ONLY" if provider in {"mock", "behavioral-mock"} else "REAL_PROVIDER_PILOT_NON_CONFIRMATORY",
    }
    if request_namespace:
        manifest["request_namespace"] = request_namespace
    _json_write(manifest_path, manifest)
    _json_write(run_dir / "config_frozen.json", config.to_dict())
    return manifest, fingerprint_digest


def _write_plan_for_run(project_root: Path, run_dir: Path, config: ExperimentConfig, *, run_id: str, worlds: list[str], conditions: list[str], repeats: int, model_snapshot: str, request_namespace: str | None = None, replicate_indices: list[int] | None = None) -> list[dict[str, Any]]:
    rows = build_plan(project_root, config, run_id=run_id, worlds=worlds, conditions=conditions, repeats=repeats, request_namespace=request_namespace, replicate_indices=replicate_indices)
    for row in rows:
        row["model_snapshot"] = model_snapshot
    path = run_dir / "run_plan.jsonl"
    existing = read_plan(path)
    if existing and existing != rows:
        raise RuntimeError("run plan mismatch: existing plan is immutable; create a new run")
    if not existing:
        write_plan(path, rows)
    return rows


def run_pilot(
    project_root: str | Path,
    config: ExperimentConfig,
    *,
    provider: str,
    worlds: list[str],
    conditions: list[str],
    repeats: int,
    replicate_indices: list[int] | None = None,
    request_namespace: str | None = None,
    allow_paid_api: bool = False,
    run_dir: str | Path | None = None,
    retry_failed: bool = False,
    kimi26_key_file: str | Path | None = None,
    kimi26_base_url: str | None = None,
    kimi26_timeout: float | None = None,
    kimi26_max_cost_usd: float | None = None,
    kimi26_max_output_tokens: int = 1200,
    behavioral_scenario: str = "constant",
    global_max_calls: int | None = None,
    global_max_cost_usd: float | None = None,
    v4_session_dir: str | Path | None = None,
    session_dir: str | Path | None = None,
) -> Path:
    project_root = Path(project_root).resolve()
    if provider in {"existing", "kimi26"} and not allow_paid_api:
        raise PermissionError(f"{provider} provider requires --allow-paid-api; no network request was attempted")
    if provider in {"existing", "kimi26"} and (global_max_calls is None or global_max_cost_usd is None):
        raise PermissionError("real pilot requires explicit --max-calls and --max-estimated-cost-usd run caps")
    adapter = make_adapter(provider, allow_paid_api, config=config, key_file=kimi26_key_file, base_url=kimi26_base_url, timeout=kimi26_timeout, max_cost_usd=kimi26_max_cost_usd, max_output_tokens=kimi26_max_output_tokens, behavioral_scenario=behavioral_scenario)
    if run_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir_path = project_root / "runs" / f"{provider}_{stamp}"
    else:
        run_dir_path = Path(run_dir).resolve()
    run_dir_path.mkdir(parents=True, exist_ok=True)
    real_gate: Any = None
    if provider in {"existing", "kimi26"}:
        if str(config.score_version).startswith("v5p11"):
            if session_dir is None:
                raise PermissionError("V5-P11 real pilot requires an explicit independent --session-dir")
            real_gate = V5P11SessionGate(project_root, session_dir)
            real_gate.assert_authorized(provider=provider, model=adapter.model_name, worlds=worlds, conditions=conditions)
        elif str(config.score_version).startswith("v5p8"):
            if session_dir is None:
                raise PermissionError("V5-P8 real pilot requires an explicit independent --session-dir")
            real_gate = V5P8SessionGate(project_root, session_dir)
            real_gate.assert_authorized(provider=provider, model=adapter.model_name, worlds=worlds, conditions=conditions)
        elif str(config.score_version).startswith("v5p4"):
            if session_dir is None:
                raise PermissionError("V5-P4 real pilot requires an explicit independent --session-dir")
            real_gate = V5P4SessionGate(project_root, session_dir)
            real_gate.assert_authorized(provider=provider, model=adapter.model_name, worlds=worlds, conditions=conditions)
        elif str(config.score_version).startswith("v4"):
            if v4_session_dir is None:
                raise PermissionError("V4 real pilot requires an explicit independent --v4-session-dir")
            real_gate = V4SessionGate(project_root, v4_session_dir)
            real_gate.assert_authorized(provider=provider, model=adapter.model_name, worlds=worlds, conditions=conditions)
        else:
            run_cost_cap = global_max_cost_usd
            if kimi26_max_cost_usd is not None:
                run_cost_cap = kimi26_max_cost_usd if run_cost_cap is None else min(run_cost_cap, kimi26_max_cost_usd)
            real_gate = PersistentRealGate(project_root, config, run_max_calls=global_max_calls, run_max_cost_usd=run_cost_cap)
            real_gate.assert_authorized(
                provider=provider,
                model=adapter.model_name,
                allow_paid_api=allow_paid_api,
                stage="pilot",
                worlds=worlds,
                conditions=conditions,
            )
    manifest, config_digest = _manifest_for_run(project_root, run_dir_path, config, provider=provider, adapter=adapter, worlds=worlds, conditions=conditions, repeats=repeats, request_namespace=request_namespace, replicate_indices=replicate_indices, allow_paid_api=allow_paid_api, gate=real_gate)
    run_id = str(manifest.get("run_id", run_dir_path.name))
    plan_rows = _write_plan_for_run(project_root, run_dir_path, config, run_id=run_id, worlds=worlds, conditions=conditions, repeats=repeats, model_snapshot=adapter.model_name, request_namespace=request_namespace, replicate_indices=replicate_indices)
    if real_gate is not None:
        input_rate = float(getattr(adapter, "input_cost_per_1k", 0.00095))
        output_rate = float(getattr(adapter, "output_cost_per_1k", 0.004))
        budget_plan = pilot_request_plan(project_root, config, worlds=worlds, conditions=conditions, repeats=repeats, request_namespace=request_namespace, replicate_indices=replicate_indices, input_rate=input_rate, output_rate=output_rate)
        if isinstance(real_gate, (V4SessionGate, V5P4SessionGate)):
            preflight = real_gate.preflight(provider=provider, model=adapter.model_name, request_plan=budget_plan, worlds=worlds, conditions=conditions)
        else:
            preflight = real_gate.preflight(provider=provider, model=adapter.model_name, allow_paid_api=allow_paid_api, stage="pilot", request_plan=budget_plan, worlds=worlds, conditions=conditions)
        manifest["call_policy"]["preflight"] = preflight
        manifest["call_policy"]["budget_plan"] = budget_plan
        gate_summary = real_gate.summary()
        manifest["call_policy"].update({
            "authorization_status": gate_summary.get("authorization_status"),
            "authorization_id": gate_summary.get("authorization_id"),
            "max_unique_calls": gate_summary.get("max_unique_calls"),
            "max_estimated_cost_usd": gate_summary.get("max_estimated_cost_usd"),
        })
        manifest["call_policy"]["real_api_status"] = "REQUESTED"
        _json_write(run_dir_path / "manifest.json", manifest)
    events_path = run_dir_path / "events.jsonl"
    ledger_path = run_dir_path / "call_ledger.jsonl"
    attempt_results_path = run_dir_path / "attempt_results.jsonl"
    events_path.touch(exist_ok=True)
    rows = [dict(row) for row in read_results(run_dir_path)]
    existing_primary = {_analysis_key(row, config_digest): row for row in rows}
    attempt_counts: dict[str, int] = {}
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                request_id = str(record.get("request_id", ""))
                attempt_counts[request_id] = max(attempt_counts.get(request_id, 0), int(str(record.get("call_id", "attempt0")).rsplit("attempt", 1)[-1]) if "attempt" in str(record.get("call_id", "")) else 0)

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for plan_row in plan_rows:
        grouped.setdefault((str(plan_row["world_id"]), int(plan_row["replicate"])), []).append(plan_row)
    is_real_provider = provider in {"existing", "kimi26"}
    v5_protocol = str(config.score_version).startswith("v5p")
    protocol_version = _protocol_version(config)
    require_predicted_values = str(config.score_version).startswith(("v4", "v5p2", "v5p3", "v5p4", "v5p8", "v5p11"))
    stop_reason: str | None = None
    processed_stage2: set[tuple[str, int, str]] = set()
    for (world_id, replicate), pair_rows in grouped.items():
        if stop_reason is not None:
            break
        pair_id = str(pair_rows[0].get("pair_id", f"{world_id}_R{replicate}"))
        stage1_plan = next((item for item in pair_rows if item["stage"] == "stage1"), None)
        stage1_cache: dict[str, Any] | None = None
        stage1_response: LLMResponse | None = None
        if stage1_plan and not require_predicted_values:
            owner = str(stage1_plan["condition"])
            stage1_cache, stage1_response, stop_reason = _execute_stage1(project_root=project_root, config=config, run_dir_path=run_dir_path, adapter=adapter, events_path=events_path, ledger_path=ledger_path, run_id=run_id, world_id=world_id, replicate=replicate, owner=owner, pair_id=pair_id, attempt_counts=attempt_counts, real_gate=real_gate, provider=provider, is_real_provider=is_real_provider)

        if stop_reason is not None:
            break

        if require_predicted_values:
            v4_order = {"A_TARGET_ONLY": 0, "B_SINGLE_RELATED": 1, "stage1": 2, "C_SEQ2_TRANSFER": 3, "D_SEQ2_BLOCK": 4}
            ordered_pair_rows = sorted(pair_rows, key=lambda item: v4_order.get(str(item["condition"]) if item["stage"] == "stage2" else "stage1", 99))
        else:
            ordered_pair_rows = sorted(pair_rows, key=lambda item: int(item["order_index"]))
        for plan_row in ordered_pair_rows:
            if stop_reason is not None:
                break
            if plan_row["stage"] == "stage1" and require_predicted_values:
                owner = str(plan_row["condition"])
                stage1_cache, stage1_response, stop_reason = _execute_stage1(project_root=project_root, config=config, run_dir_path=run_dir_path, adapter=adapter, events_path=events_path, ledger_path=ledger_path, run_id=run_id, world_id=world_id, replicate=replicate, owner=owner, pair_id=pair_id, attempt_counts=attempt_counts, real_gate=real_gate, provider=provider, is_real_provider=is_real_provider)
                continue
            if plan_row["stage"] != "stage2":
                continue
            condition = str(plan_row["condition"])
            view = _condition_view(project_root, world_id, condition, config)
            preview_key = (world_id, str(replicate), adapter.model_name, config_digest, condition)
            old_row = existing_primary.get(preview_key)
            if old_row is not None and (not retry_failed or str(old_row.get("run_status")) == "COMPLETED"):
                continue
            policy: EvidencePolicy = policy_for_route(view, condition=condition)
            final_response: LLMResponse | None = None
            route: dict[str, Any] | None = None
            contract_valid = True
            contract_invalid_reason = ""
            workflow_tracker = BudgetTracker(config.max_total_tokens_per_condition, config.max_agent_model_calls)
            try:
                if condition in SEQ2_CONDITIONS:
                    stage1_info = stage1_cache or {"parsed_artifact": {}, "valid": False, "reason": "stage1_unavailable", "response": None, "stage1_artifact_sha256": sha256_json({})}
                    stage1_response = stage1_info.get("response")
                    workflow_tracker.seed_usage(stage1_response)
                    transfer, intervention = _route_for_condition(condition)
                    recorder = CallRecorder(adapter, workflow_tracker, events_path, ledger_path=ledger_path, run_id=run_id, world_id=world_id, condition=condition, replicate=replicate, pair_id=pair_id, stage="stage2", attempt_counts=attempt_counts, shared_call_id=f"{pair_id}:{stage1_info.get('owner_condition', 'stage1')}:stage1", global_gate=real_gate, global_provider=provider, global_stage="pilot", enforce_prompt_blinding=str(config.score_version).startswith(("v5p4", "v5p8", "v5p11")))
                    final_response, route = seq2.run_stage2(view, condition, stage1_info.get("parsed_artifact") or {}, transfer, recorder, intervention=intervention, max_output_tokens=600 if require_predicted_values else 450, protocol_version=protocol_version)
                    policy = policy_for_route(view, route=route, condition=condition)
                    _save_response(_artifact_dir(run_dir_path, world_id, condition, replicate) / "stage2.json", final_response, {"route": route, "stage1_artifact_sha256": route["stage1_artifact_sha256"], "forwarded_artifact_sha256": route["forwarded_artifact_sha256"]})
                    _emit(events_path, "ARTIFACT_CREATED", run_id=run_id, world_id=world_id, replicate=replicate, pair_id=pair_id, condition=condition, stage1_artifact_sha256=route["stage1_artifact_sha256"], valid=bool(stage1_info.get("valid")))
                    _emit(events_path, "ROUTE_APPLIED", run_id=run_id, world_id=world_id, replicate=replicate, pair_id=pair_id, condition=condition, transfer_applied=transfer, intervention=intervention, stage1_artifact_sha256=route["stage1_artifact_sha256"], forwarded_artifact_sha256=route["forwarded_artifact_sha256"])
                else:
                    recorder = CallRecorder(adapter, workflow_tracker, events_path, ledger_path=ledger_path, run_id=run_id, world_id=world_id, condition=condition, replicate=replicate, pair_id=pair_id, stage="stage2", attempt_counts=attempt_counts, global_gate=real_gate, global_provider=provider, global_stage="pilot", enforce_prompt_blinding=str(config.score_version).startswith(("v5p4", "v5p8", "v5p11")))
                    if condition in {"A_TARGET_ONLY", "B_SINGLE_RELATED"}:
                        output = single.run(view, condition, recorder, protocol_version=protocol_version)
                    elif condition == "S_COLLAB3":
                        output = collab3.run(view, recorder)
                    elif condition == "S_COMPETE3":
                        output = compete3.run(view, recorder)
                    else:
                        raise ValueError(f"unsupported condition: {condition}")
                    final_response = output["final_response"]
                    assert isinstance(final_response, LLMResponse)
                    _save_response(_artifact_dir(run_dir_path, world_id, condition, replicate) / "final.json", final_response, {"condition": condition})
                    for name, value in output.items():
                        if name.endswith("_response") and isinstance(value, LLMResponse):
                            _save_response(_artifact_dir(run_dir_path, world_id, condition, replicate) / f"{name}.json", value, {"agent_name": name})
                    if condition == "S_COMPETE3" and output.get("judge_contract") is not None:
                        contract = output["judge_contract"]
                        contract_valid = bool(getattr(contract, "valid", False))
                        contract_invalid_reason = str(getattr(contract, "reason", "invalid_judge_contract"))
                    intermediate = []
                    for key in ("source_artifact", "target_artifact", "proposal_one", "proposal_two"):
                        if isinstance(output.get(key), dict):
                            intermediate.append(output[key])
                    policy = policy_for_route(view, condition=condition, intermediate_records=intermediate)
                responses = [stage1_response, final_response] if condition in SEQ2_CONDITIONS else [final_response]
                input_tokens = _sum_known(responses, "input_tokens")
                output_tokens = _sum_known(responses, "output_tokens")
                estimate_cost = _estimated_cost(responses)
                provider_cost = _provider_billed_cost(responses)
                artifact = (stage1_cache or {}).get("parsed_artifact") if condition in SEQ2_CONDITIONS else None
                row = evaluate_final(project_root, world_id, view, final_response.text if final_response else "", condition=condition, provider=provider, model_snapshot=adapter.model_name, replicate=replicate, input_tokens=input_tokens, output_tokens=output_tokens, api_calls=workflow_tracker.calls, latency_ms=workflow_tracker.latency_ms, billed_cost=provider_cost, attributed_full_workflow_cost=estimate_cost, stage1={"parsed_artifact": artifact or {}, "truth_checks": (stage1_cache or {}).get("truth_checks", {})} if condition in SEQ2_CONDITIONS else None, transfer_applied=(route or {}).get("transfer_applied") if route else None, stage1_artifact_sha256=(route or {}).get("stage1_artifact_sha256"), forwarded_artifact_sha256=(route or {}).get("forwarded_artifact_sha256"), evidence_policy=policy, worlds_subdir=config.worlds_subdir, private_worlds_subdir=config.private_worlds_subdir, contract_valid=contract_valid, contract_invalid_reason=contract_invalid_reason, require_predicted_values=require_predicted_values, require_selected_action=v5_protocol, separate_scientific_validity=v5_protocol, extra_fields={"stage1_valid": bool((stage1_cache or {}).get("valid", True)) if condition in SEQ2_CONDITIONS else "", "stage1_json_valid": bool((stage1_cache or {}).get("valid", True)) if condition in SEQ2_CONDITIONS else "", "stage1_transfer_eligible": bool((stage1_cache or {}).get("valid", False)) if condition in SEQ2_CONDITIONS else "", "route_intervention": (route or {}).get("intervention", "") if route else "", "estimated_cost_usd": estimate_cost, "provider_billed_cost_usd": provider_cost, "full_workflow_calls": workflow_tracker.calls, "full_workflow_tokens": workflow_tracker.total_tokens if workflow_tracker.usage_verified else None, "full_workflow_estimated_cost": estimate_cost, "budget_verified": workflow_tracker.budget_verified, "usage_source": "provider_usage" if workflow_tracker.usage_verified else "USAGE_UNVERIFIED", "unique_provider_calls": workflow_tracker.calls, "judge_contract_valid": contract_valid})
                row["experiment_id"] = config.experiment_id
                row["pair_id"] = pair_id
                row["config_hash"] = config_digest
                _emit(events_path, "FINAL_VALIDATION", run_id=run_id, world_id=world_id, replicate=replicate, pair_id=pair_id, condition=condition, valid=row.get("valid"), invalid_reason=row.get("invalid_reason", ""), status="completed")
                _emit(events_path, "ORACLE_EVALUATION", run_id=run_id, world_id=world_id, replicate=replicate, pair_id=pair_id, condition=condition, top1_score=row.get("top1_score", 0.0), status="completed")
                _emit(events_path, "BUDGET_ACCOUNTING", run_id=run_id, world_id=world_id, replicate=replicate, pair_id=pair_id, condition=condition, **workflow_tracker.snapshot())
                if is_real_provider:
                    scientific_issue = _real_result_failure_reason(row, require_stage1_mapping=condition in SEQ2_CONDITIONS)
                    if str(config.score_version).startswith(("v5p4", "v5p8", "v5p11")):
                        # Keep scientific failures, continue with next experiment
                        # arm. Network, budget, identity and credential failures
                        # still abort via the technical exception paths.
                        if scientific_issue:
                            _emit(events_path, "SCIENTIFIC_OUTPUT_INVALID", run_id=run_id,
                                  world_id=world_id, replicate=replicate, pair_id=pair_id,
                                  condition=condition, reason=scientific_issue,
                                  status="recorded_continue")
                    else:
                        stop_reason = scientific_issue
            except Exception as exc:
                failure_kind = getattr(exc, "failure_kind", "")
                row = evaluate_final(project_root, world_id, view, final_response.text if final_response else "", condition=condition, provider=provider, model_snapshot=adapter.model_name, replicate=replicate, input_tokens=workflow_tracker.total_input_tokens, output_tokens=workflow_tracker.total_output_tokens, api_calls=workflow_tracker.calls, latency_ms=workflow_tracker.latency_ms, billed_cost=None, attributed_full_workflow_cost=None, run_status="FAILED_TRANSPORT" if failure_kind else "FAILED", invalid_reason=f"{type(exc).__name__}:{str(exc)[:500]}", stage1={"parsed_artifact": (stage1_cache or {}).get("parsed_artifact", {}), "truth_checks": (stage1_cache or {}).get("truth_checks", {})} if condition in SEQ2_CONDITIONS else None, transfer_applied=(route or {}).get("transfer_applied") if route else None, stage1_artifact_sha256=(route or {}).get("stage1_artifact_sha256"), forwarded_artifact_sha256=(route or {}).get("forwarded_artifact_sha256"), evidence_policy=policy, worlds_subdir=config.worlds_subdir, private_worlds_subdir=config.private_worlds_subdir, require_predicted_values=require_predicted_values, extra_fields={"budget_verified": False, "usage_source": "USAGE_UNVERIFIED", "full_workflow_calls": workflow_tracker.calls, "route_intervention": (route or {}).get("intervention", "") if route else "", "failure_kind": failure_kind or type(exc).__name__, "reason_type": getattr(exc, "reason_type", ""), "detail_code": getattr(exc, "detail_code", ""), "error_elapsed_ms": getattr(exc, "elapsed_ms", None), "scientific_output_available": False})
                row["experiment_id"] = config.experiment_id
                row["pair_id"] = pair_id
                row["config_hash"] = config_digest
                _emit(events_path, "FINAL_VALIDATION", run_id=run_id, world_id=world_id, replicate=replicate, pair_id=pair_id, condition=condition, valid=False, invalid_reason=row.get("invalid_reason", ""), status="failed")
                if is_real_provider:
                    stop_reason = f"stage2_provider_failure:{type(exc).__name__}:{str(exc)[:500]}"
            _append_attempt_result(attempt_results_path, row)
            _upsert_primary(rows, row, config_digest, retry_failed=retry_failed)
            existing_primary[_analysis_key(row, config_digest)] = row
            processed_stage2.add((world_id, replicate, condition))
    if stop_reason is not None:
        for plan_row in plan_rows:
            if plan_row.get("stage") != "stage2":
                continue
            key = (str(plan_row["world_id"]), int(plan_row["replicate"]), str(plan_row["condition"]))
            if key in processed_stage2:
                continue
            missing_condition = str(plan_row["condition"])
            missing_world = str(plan_row["world_id"])
            missing_replicate = int(plan_row["replicate"])
            missing_view = _condition_view(project_root, missing_world, missing_condition, config)
            missing_row = evaluate_final(project_root, missing_world, missing_view, "", condition=missing_condition, provider=provider, model_snapshot=adapter.model_name, replicate=missing_replicate, input_tokens=None, output_tokens=None, api_calls=0, latency_ms=0, billed_cost=None, attributed_full_workflow_cost=None, run_status="UPSTREAM_FAIL_FAST", invalid_reason="UPSTREAM_FAIL_FAST", evidence_policy=policy_for_route(missing_view, condition=missing_condition), worlds_subdir=config.worlds_subdir, private_worlds_subdir=config.private_worlds_subdir, require_predicted_values=require_predicted_values, extra_fields={"route_intervention": "not_executed", "scientific_output_available": False})
            missing_row["experiment_id"] = config.experiment_id
            missing_row["pair_id"] = str(plan_row.get("pair_id", f"{missing_world}_R{missing_replicate}"))
            missing_row["config_hash"] = config_digest
            _append_attempt_result(attempt_results_path, missing_row)
            _upsert_primary(rows, missing_row, config_digest, retry_failed=retry_failed)
    write_results(run_dir_path, rows)
    write_report(run_dir_path)
    manifest["primary_rows"] = len(rows)
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    if real_gate is not None:
        manifest["call_policy"]["gate_summary"] = real_gate.summary()
        manifest["call_policy"]["stop_reason"] = stop_reason
        manifest["call_policy"]["real_api_status"] = "FAILED" if stop_reason else manifest["call_policy"]["gate_summary"]["real_api_status"]
    _json_write(run_dir_path / "manifest.json", manifest)
    if _should_write_legacy_g3_report(config, provider):
        write_g3_report(project_root, run_dir_path)
    return run_dir_path


def probe_role(
    project_root: str | Path,
    config: ExperimentConfig,
    *,
    provider: str,
    world_id: str,
    role: str,
    allow_paid_api: bool = False,
    max_calls: int = 1,
    kimi26_key_file: str | Path | None = None,
    kimi26_base_url: str | None = None,
    kimi26_timeout: float | None = None,
    kimi26_max_cost_usd: float | None = None,
    kimi26_max_output_tokens: int = 800,
    behavioral_scenario: str = "constant",
) -> Path:
    if provider in {"existing", "kimi26"} and not allow_paid_api:
        raise PermissionError(f"{provider} provider requires --allow-paid-api; no network request was attempted")
    if max_calls != 1:
        raise ValueError("probe-role requires --max-calls 1")
    root = Path(project_root).resolve()
    adapter = make_adapter(provider, allow_paid_api, config=config, key_file=kimi26_key_file, base_url=kimi26_base_url, timeout=kimi26_timeout, max_cost_usd=kimi26_max_cost_usd, max_output_tokens=kimi26_max_output_tokens, behavioral_scenario=behavioral_scenario)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_prefix = "real_kimi26_probe" if provider in {"existing", "kimi26"} else "probe"
    run_dir = root / "runs" / f"{run_prefix}_{role}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.jsonl"
    ledger_path = run_dir / "call_ledger.jsonl"
    real_gate: PersistentRealGate | None = None
    budget_plan = None
    if provider in {"existing", "kimi26"}:
        input_rate = float(getattr(adapter, "input_cost_per_1k", 0.00095))
        output_rate = float(getattr(adapter, "output_cost_per_1k", 0.004))
        budget_plan = probe_request_plan(root, config, world_id=world_id, role=role, max_output_tokens=kimi26_max_output_tokens, input_rate=input_rate, output_rate=output_rate)
        real_gate = PersistentRealGate(root, config, run_max_calls=1, run_max_cost_usd=kimi26_max_cost_usd)
        real_gate.preflight(
            provider=provider,
            model=adapter.model_name,
            allow_paid_api=allow_paid_api,
            stage="probe-role",
            request_plan=budget_plan,
            worlds=[world_id],
        )
    tracker = BudgetTracker(config.max_total_tokens_per_condition, 1)
    pair_id = f"{world_id}_PROBE"
    recorder = CallRecorder(adapter, tracker, events_path, ledger_path=ledger_path, run_id=run_dir.name, world_id=world_id, condition="PROBE", replicate=0, pair_id=pair_id, stage="stage1" if role == "pattern_extractor" else "stage2", attempt_counts={}, global_gate=real_gate, global_provider=provider, global_stage="probe-role")
    view = load_world(root, world_id, "related", worlds_subdir=config.worlds_subdir)
    if role == "single_question_designer":
        messages = single_messages(view)
    elif role == "pattern_extractor":
        messages = seq2_stage1_messages(view)
    elif role == "question_designer":
        messages = seq2_stage2_messages(view, {"status": "not_available", "source_evidence_ids": [], "target_evidence_ids": []})
    else:
        raise ValueError("role must be single_question_designer, pattern_extractor, or question_designer")
    try:
        response = recorder(role, messages, kimi26_max_output_tokens)
    except Exception as exc:
        gate_summary = real_gate.summary() if real_gate is not None else None
        _json_write(run_dir / "manifest.json", {"run_id": run_dir.name, "provider": provider, "model_snapshot": adapter.model_name, "world_id": world_id, "role": role, "max_calls": 1, "real_api_status": (gate_summary or {}).get("real_api_status", "FAILED"), "budget": tracker.snapshot(), "budget_plan": budget_plan or [], "error": f"{type(exc).__name__}:{str(exc)[:500]}", "gate_summary": gate_summary})
        (run_dir / "role_probe_report.md").write_text("# V3 role probe report\n\n- gate_result: `FAILED`\n- real_api_status: `FAILED`\n\nThe provider attempt failed; the raw response was unavailable.\n", encoding="utf-8")
        raise
    role_check = role_response_check(response, role=role, view=view, requested_model=adapter.model_name)
    if role == "pattern_extractor":
        truth_path = root / "private" / config.private_worlds_subdir / world_id / "hidden_truth.json"
        if truth_path.exists():
            truth = json.loads(truth_path.read_text(encoding="utf-8"))
            parsed_role = parse_json_object(response.text).data or {}
            role_check["law_id_correct"] = parsed_role.get("candidate_law_id") == truth.get("true_law")
            role_check["shared_law_correct"] = parsed_role.get("shared_law_judgment") == "same"
    _save_response(run_dir / "probe_response.json", response, {"role": role, "valid": role_check["schema_valid"], "reason": role_check["validation_reason"], "parsed": parse_json_object(response.text).data, "contract_check": role_check})
    report_lines = [
        "# V3 role probe report",
        "",
        f"- role: `{role}`",
        f"- provider: `{provider}`",
        f"- requested_model: `{adapter.model_name}`",
        f"- gate_result: `{role_check['gate_result']}`",
        f"- json_valid: `{role_check['json_valid']}`",
        f"- schema_valid: `{role_check['schema_valid']}`",
        f"- truncated: `{role_check['truncated']}`",
        f"- usage_source: `{role_check['usage_source']}`",
        "",
        "This probe is diagnostic only; it does not establish a scientific result.",
    ]
    (run_dir / "role_probe_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    gate_summary = real_gate.summary() if real_gate is not None else None
    manifest = {"run_id": run_dir.name, "provider": provider, "model_snapshot": adapter.model_name, "world_id": world_id, "role": role, "max_calls": 1, "real_api_status": "NOT_RUN" if provider in {"mock", "behavioral-mock"} else (gate_summary or {}).get("real_api_status", "COMPLETED"), "budget": tracker.snapshot(), "budget_plan": budget_plan or [], "contract_check": role_check}
    if real_gate is not None:
        manifest["gate_summary"] = gate_summary
    _json_write(run_dir / "manifest.json", manifest)
    if provider in {"existing", "kimi26"}:
        write_g2_report(root)
        if role_check.get("gate_result") != "PASS" or role_check.get("returned_model") != adapter.model_name or role_check.get("usage_source") != "provider_usage":
            raise RuntimeError(f"G2 role contract failed: {role_check.get('gate_result')}")
        if role == "pattern_extractor" and role_check.get("law_id_correct") is not True:
            raise RuntimeError("G2 pattern extractor did not identify the private reference law")
    return run_dir
