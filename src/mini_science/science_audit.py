from __future__ import annotations

"""Offline scientific-validity diagnostics for completed V5-P9/V5-P10 runs.

This module deliberately has two separate input boundaries:

* ``public_identifiability`` reads only ``data/worlds_*`` public files and the
  public simulator equations.
* run diagnostics read already-recorded outputs and ledgers; they never use
  private truth to alter a prompt or to repair an agent response.

The outputs are derived audits.  They do not rewrite historical results.
"""

import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from .analysis import paired_metrics
from .simulators import MODELS, predict


SOURCE_RE = re.compile(
    r"-\s*S(?P<id>\d+):\s*"
    r"(?P<value_name>source_state|source_concentration)=(?P<value>[0-9.]+),\s*"
    r"(?P<time_name>source_time|source_minutes)=(?P<time>[0-9.]+)"
)
TARGET_K_RE = re.compile(r"Nominal candidate-rate k=([0-9]+(?:\.[0-9]+)?)")
TARGET_SIGMA_RE = re.compile(r"observation noise sigma=([0-9]+(?:\.[0-9]+)?)")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _parse_public_world(project_root: str | Path, world_id: str, *, worlds_subdir: str = "worlds_v5p4_dev") -> dict[str, Any]:
    """Load only public files; this function never opens ``private/``."""

    public = Path(project_root) / "data" / worlds_subdir / world_id
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    source_text = (public / "source_related.md").read_text(encoding="utf-8")
    target_text = (public / "target_notes.md").read_text(encoding="utf-8")
    source_rows = []
    for match in SOURCE_RE.finditer(source_text):
        raw_value = float(match.group("value"))
        raw_time = float(match.group("time"))
        conversion = manifest.get("public_unit_conversion") or {}
        value_scale = 1.0 if match.group("value_name") == "source_state" else 0.01
        time_scale = 1.0 if match.group("time_name") == "source_time" else 1.0 / 60.0
        if match.group("value_name") == "source_concentration":
            value_scale = 0.01 if conversion.get("source_concentration_to_target_state") == "divide_by_100" else 1.0
        if match.group("time_name") == "source_minutes":
            time_scale = 1.0 / 60.0 if conversion.get("source_minutes_to_target_time") == "divide_by_60" else 1.0
        source_rows.append({
            "evidence_id": f"S{int(match.group('id')):02d}",
            "raw_value": raw_value,
            "raw_time": raw_time,
            "value": raw_value * value_scale,
            "time": raw_time * time_scale,
            "value_field": match.group("value_name"),
            "time_field": match.group("time_name"),
        })
    if not source_rows:
        raise ValueError(f"no public source observations found for {world_id}")
    k_match = TARGET_K_RE.search(target_text)
    sigma_match = TARGET_SIGMA_RE.search(target_text)
    metadata = manifest.get("public_variable_schema") or {}
    conversion = manifest.get("public_unit_conversion") or {}
    return {
        "world_id": world_id,
        "manifest": manifest,
        "source_rows": source_rows,
        "target_nominal_k": float(k_match.group(1)) if k_match else None,
        "target_sigma": float(sigma_match.group(1)) if sigma_match else None,
        "source_initial_state_status": "UNIDENTIFIED",
        "source_rate_status": "UNIDENTIFIED",
        "source_noise_status": "UNIDENTIFIED",
        "source_time_unit_status": "EXPLICIT_CONVERSION" if conversion else "UNIDENTIFIED",
        "mapping_status": "EXPLICIT_PUBLIC_SCHEMA" if metadata else "UNIDENTIFIED",
        "unit_conversion": conversion,
        "target_notes": target_text,
        "source_notes": source_text,
    }


def _rss(model: str, observations: list[dict[str, float]], x0: float, k: float) -> float:
    return sum((float(row["value"]) - predict(model, x0, float(row["time"]), k)) ** 2 for row in observations)


def _fit_s2(model: str, observations: list[dict[str, float]]) -> tuple[float, float, float]:
    """Deterministic bounded fit using only public observations.

    A coarse grid plus coordinate refinement keeps the audit dependency-free and
    makes its result stable across machines.  These are source-shape fits, not
    claims that the source and target parameters are physically identical.
    """

    best = (float("inf"), 1.0, 0.5)
    for i in range(61):
        x0 = 0.10 + i * (1.50 - 0.10) / 60.0
        for j in range(81):
            k = 0.01 + j * (2.00 - 0.01) / 80.0
            value = _rss(model, observations, x0, k)
            if value < best[0]:
                best = (value, x0, k)
    rss, x0, k = best
    steps = (0.05, 0.02, 0.01, 0.005, 0.001)
    k_steps = (0.10, 0.05, 0.02, 0.01, 0.005)
    for x_step, k_step in zip(steps, k_steps):
        improved = True
        while improved:
            improved = False
            candidates = [(x0 + dx, k + dk) for dx in (-x_step, 0.0, x_step) for dk in (-k_step, 0.0, k_step)]
            for candidate_x0, candidate_k in candidates:
                if not (0.10 <= candidate_x0 <= 1.50 and 0.01 <= candidate_k <= 2.00):
                    continue
                candidate_rss = _rss(model, observations, candidate_x0, candidate_k)
                if candidate_rss + 1e-15 < rss:
                    rss, x0, k = candidate_rss, candidate_x0, candidate_k
                    improved = True
    return rss, x0, k


def public_identifiability(project_root: str | Path, world_ids: Iterable[str] = ("CV001", "CV002", "CV003", "CV004")) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return row-level fit diagnostics and one public metadata summary per world."""

    fit_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for world_id in world_ids:
        data = _parse_public_world(project_root, world_id)
        observations = data["source_rows"]
        models = tuple(data["manifest"].get("candidate_models") or MODELS)
        scenario_results: dict[str, dict[str, dict[str, Any]]] = {"S0": {}, "S1": {}, "S2": {}}
        for model in models:
            s0 = {
                "status": "UNIDENTIFIED",
                "assumptions": "source_x0=UNIDENTIFIED;source_k=UNIDENTIFIED;source_sigma=UNIDENTIFIED",
                "fitted_x0": "UNIDENTIFIED",
                "fitted_k": "UNIDENTIFIED",
                "rss": "UNIDENTIFIED",
                "rmse": "UNIDENTIFIED",
                "valid_parameter_bounds": "UNIDENTIFIED",
            }
            scenario_results["S0"][model] = s0
            s1_k = data["target_nominal_k"]
            s1_rss = _rss(model, observations, 1.0, float(s1_k)) if s1_k is not None else None
            scenario_results["S1"][model] = {
                "status": "ASSUMPTION_S1",
                "assumptions": "source_x0=1.0;source_k=target_nominal_k;source_time_uses_public_conversion_or_raw_units;source_sigma_not_verified",
                "fitted_x0": 1.0,
                "fitted_k": s1_k,
                "rss": s1_rss,
                "rmse": math.sqrt(s1_rss / len(observations)) if s1_rss is not None else None,
                "valid_parameter_bounds": True,
            }
            s2_rss, s2_x0, s2_k = _fit_s2(model, observations)
            scenario_results["S2"][model] = {
                "status": "FIT_WITH_UNVERIFIED_SOURCE_NOISE",
                "assumptions": "source_x0_and_source_k_fitted_in_bounds;source_sigma=target_sigma_only_for_diagnostic_scale;time_units_follow_public_conversion_else_raw_source_units",
                "fitted_x0": s2_x0,
                "fitted_k": s2_k,
                "rss": s2_rss,
                "rmse": math.sqrt(s2_rss / len(observations)),
                "valid_parameter_bounds": 0.10 <= s2_x0 <= 1.50 and 0.01 <= s2_k <= 2.00,
            }
        for scenario, result_map in scenario_results.items():
            numeric_rss = {model: _finite(values.get("rss")) for model, values in result_map.items()}
            ordered = sorted((rss, model) for model, rss in numeric_rss.items() if rss is not None)
            ranks = {model: index + 1 for index, (_, model) in enumerate(ordered)}
            best_rss = ordered[0][0] if ordered else None
            second_rss = ordered[1][0] if len(ordered) > 1 else None
            global_gap = (second_rss - best_rss) if best_rss is not None and second_rss is not None else None
            sigma = float(data["target_sigma"] or 0.0)
            scale = max(len(observations) * sigma * sigma, 1e-12)
            margin = global_gap / scale if global_gap is not None else None
            for model, values in result_map.items():
                rss = _finite(values.get("rss"))
                row = {
                    "world_id": world_id,
                    "scenario": scenario,
                    "law_id": model,
                    "n_observations": len(observations),
                    "assumptions": values["assumptions"],
                    "fitted_x0": values["fitted_x0"],
                    "fitted_k": values["fitted_k"],
                    "rss": values["rss"],
                    "rmse": values["rmse"],
                    "valid_parameter_bounds": values["valid_parameter_bounds"],
                    "uncertainty_assumption": "source_noise_not_public;target_sigma_used_only_as_diagnostic_scale",
                    "selection_rank": ranks.get(model, "UNIDENTIFIED"),
                    "separability_margin_rss": global_gap,
                    "separability_margin_sigma2": margin,
                    "source_initial_state_status": data["source_initial_state_status"],
                    "source_rate_status": data["source_rate_status"],
                    "source_noise_status": data["source_noise_status"],
                    "source_time_unit_status": data["source_time_unit_status"],
                    "mapping_status": data["mapping_status"],
                }
                fit_rows.append(row)
        s2_ordered = sorted((float(result_map["rss"]), model) for model, result_map in scenario_results["S2"].items())
        best_model = s2_ordered[0][1] if s2_ordered else "UNIDENTIFIED"
        gap = (s2_ordered[1][0] - s2_ordered[0][0]) if len(s2_ordered) > 1 else None
        sigma_scale = max(len(observations) * float(data["target_sigma"] or 0.0) ** 2, 1e-12)
        gap_sigma = gap / sigma_scale if gap is not None else None
        if data["source_initial_state_status"] == "UNIDENTIFIED" or data["source_rate_status"] == "UNIDENTIFIED" or data["source_noise_status"] == "UNIDENTIFIED":
            decision = "NOT_IDENTIFIABLE_WITHOUT_ADDITIONAL_PUBLIC_METADATA"
        elif gap_sigma is not None and gap_sigma >= 1.0:
            decision = "POTENTIALLY_IDENTIFIABLE_UNDER_EXPLICIT_ASSUMPTIONS"
        else:
            decision = "AMBIGUOUS_UNDER_EXPLICIT_ASSUMPTIONS"
        summaries.append({
            "world_id": world_id,
            "n_source_observations": len(observations),
            "source_initial_state_status": data["source_initial_state_status"],
            "source_rate_status": data["source_rate_status"],
            "source_noise_status": data["source_noise_status"],
            "source_time_unit_status": data["source_time_unit_status"],
            "mapping_status": data["mapping_status"],
            "target_nominal_k_public": data["target_nominal_k"],
            "target_sigma_public": data["target_sigma"],
            "s2_best_model": best_model,
            "s2_best_rss_gap": gap,
            "s2_gap_in_target_sigma2_units": gap_sigma,
            "identifiability_status": decision,
            "public_source_files": "manifest.json;source_related.md;target_notes.md;candidate_experiments.json",
        })
    return fit_rows, summaries


def _event_prompt_stats(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event_type") != "STAGE2_REQUEST":
            continue
        condition = str(event.get("condition", ""))
        messages = event.get("request") or []
        chars = sum(len(str(message.get("content", ""))) for message in messages if isinstance(message, dict))
        result[condition] = {"prompt_chars": chars, "message_count": len(messages), "request_id": event.get("request_id", "")}
    return result


def audit_transfer_and_context(run_dir: str | Path) -> list[dict[str, Any]]:
    run = Path(run_dir)
    results = _read_csv(run / "results.csv")
    events = _read_jsonl(run / "events.jsonl")
    prompt_stats = _event_prompt_stats(events)
    by_condition = {str(row.get("condition")): row for row in results}
    stage1 = next((event for event in events if event.get("event_type") == "STAGE1_RESPONSE"), {})
    stage1_artifact = stage1.get("response", "")
    stage1_data: dict[str, Any] = {}
    if stage1_artifact:
        try:
            stage1_data = json.loads(stage1_artifact)
        except json.JSONDecodeError:
            stage1_data = {}
    rows: list[dict[str, Any]] = []
    for condition in ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"):
        row = by_condition.get(condition, {})
        is_seq2 = condition in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}
        candidate = str(row.get("candidate_law_id", "")) if is_seq2 else ""
        judgment = str(row.get("shared_law_judgment", "")) if is_seq2 else ""
        abstained: bool | str = (candidate.upper() == "UNKNOWN" or judgment.lower() == "unknown" or not candidate) if is_seq2 else "NOT_APPLICABLE"
        specific = bool(is_seq2 and not abstained)
        transfer_applied = str(row.get("transfer_applied", "")).lower() == "true"
        law_id_correct = str(row.get("stage1_law_identification_correct", "")).lower() == "true"
        relation_correct = str(row.get("stage1_relation_correct", "")).lower() == "true"
        mapping_correct = str(row.get("stage1_mapping_correct", "")).lower() == "true"
        pair = None
        if condition == "C_SEQ2_TRANSFER":
            pair = paired_metrics(row, by_condition.get("D_SEQ2_BLOCK"))
        elif condition == "D_SEQ2_BLOCK":
            pair = paired_metrics(by_condition.get("C_SEQ2_TRANSFER"), row)
        rows.append({
            "world_id": row.get("world_id", "CV001"),
            "replicate": row.get("replicate", "0"),
            "condition": condition,
            "actual_context": "target_plus_irrelevant_source" if condition == "A_TARGET_ONLY" else ("target_plus_related_source" if condition == "B_SINGLE_RELATED" else "target_plus_routed_stage1"),
            "candidate_law_id": candidate or (stage1_data.get("candidate_law_id", "") if is_seq2 else ""),
            "stage1_judgment": judgment or (stage1_data.get("shared_law_judgment", "") if is_seq2 else ""),
            "stage1_schema_valid": row.get("stage1_valid", ""),
            "stage1_abstained": abstained,
            "routing_transfer_applied": transfer_applied,
            "law_content_specific": specific,
            "law_content_correct_after_scoring": bool(law_id_correct and relation_correct and mapping_correct and specific),
            "informative_transfer_observed": bool(transfer_applied and specific),
            "informative_correct_transfer_observed": bool(transfer_applied and specific and law_id_correct and relation_correct and mapping_correct),
            "stage1_mapping_correct": mapping_correct,
            "stage1_relation_correct": relation_correct,
            "stage1_law_identification_correct": law_id_correct,
            "transfer_applied": row.get("transfer_applied", ""),
            "route_intervention": row.get("route_intervention", ""),
            "stage1_artifact_sha256": row.get("stage1_artifact_sha256", ""),
            "forwarded_artifact_sha256": row.get("forwarded_artifact_sha256", ""),
            "prompt_chars": prompt_stats.get(condition, {}).get("prompt_chars", ""),
            "prompt_input_tokens": row.get("input_tokens", ""),
            "paired_action_eligible": "" if pair is None else pair.get("action_pair_eligible"),
            "paired_strict_eligible": "" if pair is None else pair.get("strict_pair_eligible"),
        })
    return rows


def audit_numeric_predictions(project_root: str | Path, run_dir: str | Path, *, worlds_subdir: str = "worlds_v5p4_dev") -> list[dict[str, Any]]:
    run = Path(run_dir)
    rows = _read_csv(run / "results.csv")
    output: list[dict[str, Any]] = []
    for row in rows:
        world_id = str(row.get("world_id"))
        public = _parse_public_world(project_root, world_id, worlds_subdir=worlds_subdir)
        menu_path = Path(project_root) / "data" / worlds_subdir / world_id / "candidate_experiments.json"
        menu = json.loads(menu_path.read_text(encoding="utf-8"))["experiments"]
        selected_id = str(row.get("experiment_id_selected", ""))
        selected = next((item for item in menu if str(item.get("experiment_id")) == selected_id), None)
        selected_action = json.loads(row.get("selected_action") or "{}")
        action_consistent = bool(selected and all(abs(float(selected_action.get(key)) - float(selected[key])) <= 1e-9 for key in ("x0", "measure_t"))) if selected_action and selected else False
        try:
            predicted = json.loads(row.get("predicted_values") or "{}")
        except json.JSONDecodeError:
            predicted = {}
        expected_by_model = {}
        if selected:
            expected_by_model = {model: predict(model, float(selected["x0"]), float(selected["measure_t"]), float(public["target_nominal_k"])) for model in public["manifest"].get("candidate_models", MODELS)}
        errors = {model: abs(float(predicted[model]) - expected) if model in predicted and _finite(predicted[model]) is not None else None for model, expected in expected_by_model.items()}
        categories = {model: ("pass" if error is not None and error <= 0.02 else ("missing_or_non_numeric" if error is None else "formula_or_parameter_error")) for model, error in errors.items()}
        valid = [error for error in errors.values() if error is not None]
        correct = sum(category == "pass" for category in categories.values())
        nearest_action = ""
        nearest_error = None
        if predicted and menu:
            action_distances = []
            for item in menu:
                expected = [predict(model, float(item["x0"]), float(item["measure_t"]), float(public["target_nominal_k"])) for model in expected_by_model]
                distance = sum((float(predicted.get(model, float("nan"))) - target) ** 2 for model, target in zip(expected_by_model, expected) if _finite(predicted.get(model)) is not None)
                action_distances.append((distance, str(item["experiment_id"])))
            if action_distances:
                nearest_error, nearest_action = min(action_distances)
        output.append({
            "world_id": world_id,
            "replicate": row.get("replicate", ""),
            "condition": row.get("condition", ""),
            "pair_id": row.get("pair_id", ""),
            "selected_action": selected_id,
            "selected_action_consistent": action_consistent,
            "agent_numeric_correct_count": correct,
            "agent_numeric_total": len(expected_by_model),
            "agent_numeric_accuracy": correct / len(expected_by_model) if expected_by_model else None,
            "formula_audit_accuracy": correct / len(expected_by_model) if expected_by_model else None,
            "calculator_numeric_accuracy": "NOT_RUN_ASSISTED_PROTOCOL",
            "calculation_mode": "public_formula_audit_only;raw_model_values_preserved",
            "max_abs_error": max(valid) if valid else None,
            "prediction_consistency": row.get("prediction_consistency", ""),
            "nearest_menu_action": nearest_action,
            "nearest_menu_squared_error": nearest_error,
            "error_categories": json.dumps(categories, sort_keys=True),
            "expected_values": json.dumps(expected_by_model, sort_keys=True),
            "raw_model_predicted_values": row.get("predicted_values", ""),
        })
    return output


def audit_pairs(run_dir: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(run_dir) / "results.csv")
    by = {str(row.get("condition")): row for row in rows}
    output = []
    for contrast, left_name, right_name in (("B_minus_A_action", "B_SINGLE_RELATED", "A_TARGET_ONLY"), ("C_minus_D_action", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"), ("C_minus_B_action", "C_SEQ2_TRANSFER", "B_SINGLE_RELATED")):
        pair = paired_metrics(by.get(left_name), by.get(right_name))
        output.append({
            "world_id": (by.get(left_name) or by.get(right_name) or {}).get("world_id", ""),
            "replicate": (by.get(left_name) or by.get(right_name) or {}).get("replicate", ""),
            "contrast": contrast,
            "left_condition": left_name,
            "right_condition": right_name,
            "action_delta": pair.get("delta_action_only"),
            "strict_delta": pair.get("delta_strict"),
            "action_pair_eligible": pair.get("action_pair_eligible"),
            "strict_pair_eligible": pair.get("strict_pair_eligible"),
            "sample_denominator": 1 if pair.get("action_pair_eligible") else 0,
            "strict_status": "DEFINED" if pair.get("strict_pair_eligible") else "UNDEFINED",
            "same_stage1_artifact": pair.get("same_stage1_artifact"),
            "validity_reason": pair.get("exclusion_reason"),
        })
    return output


def ledger_audit(run_dir: str | Path, session_dir: str | Path) -> dict[str, Any]:
    run = Path(run_dir)
    session = Path(session_dir)
    calls = _read_jsonl(run / "call_ledger.jsonl")
    attempts = _read_jsonl(session / "attempt_ledger.jsonl")
    results = _read_csv(run / "results.csv")
    request_ids = [str(row.get("attempt_id") or row.get("request_id")) for row in calls]
    usage = sum(float(row.get("local_response_estimate_usd") or 0.0) for row in calls)
    reserved = sum(float(row.get("reserved_estimated_cost_usd") or 0.0) for row in calls)
    attributed_tokens = sum(int(float(row.get("full_workflow_tokens") or 0)) for row in results)
    return {
        "run_dir": str(run.resolve()),
        "session_dir": str(session.resolve()),
        "request_count": len(calls),
        "unique_request_count": len(set(request_ids)),
        "request_ids": request_ids,
        "request_statuses": [row.get("request_status") for row in calls],
        "http_statuses": [row.get("http_status") for row in calls],
        "returned_models": sorted({row.get("returned_model") for row in calls}),
        "automatic_retries": 0,
        "session_ledger_record_count": len(attempts),
        "session_unique_attempt_count": len({str(row.get("request_id")) for row in attempts}),
        "session_started_count": sum(row.get("status") == "STARTED" for row in attempts),
        "session_completed_count": sum(row.get("status") == "COMPLETED" for row in attempts),
        "unique_provider_input_tokens": sum(int(row.get("actual_input_tokens") or 0) for row in calls),
        "unique_provider_output_tokens": sum(int(row.get("actual_output_tokens") or 0) for row in calls),
        "unique_provider_tokens": sum(int(row.get("actual_input_tokens") or 0) + int(row.get("actual_output_tokens") or 0) for row in calls),
        "attributed_condition_tokens": attributed_tokens,
        "request_reserved_estimate_usd": round(reserved, 10),
        "provider_usage_local_estimate_usd": round(usage, 10),
        "provider_billed_cost_or_null": [row.get("provider_billed_cost_usd") for row in calls],
        "provider_billing_verified": all(row.get("provider_billed_cost_usd") is not None for row in calls),
        "scientific_output_error_policy": "record_and_continue",
        "source_files_and_fields": {
            "request_reserved_estimate_usd": "run/call_ledger.jsonl:reserved_estimated_cost_usd",
            "provider_usage_local_estimate_usd": "run/call_ledger.jsonl:local_response_estimate_usd",
            "provider_billed_cost_or_null": "run/call_ledger.jsonl:provider_billed_cost_usd",
            "unique_provider_tokens": "run/call_ledger.jsonl:actual_input_tokens + actual_output_tokens",
            "attributed_condition_tokens": "run/results.csv:full_workflow_tokens summed by condition",
        },
    }


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return destination
