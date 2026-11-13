from __future__ import annotations

import csv
import json
from collections import defaultdict
import math
from pathlib import Path
import random
import re
from typing import Any

from .ig_oracle import oracle_scores
from .metrics.prediction_audit import PREDICTION_TOLERANCE, audit_prediction_values, public_nominal_k
from .public_loader import load_world
from .simulators import predict
from .world_registry import configured_world_ids


RESULT_FIELDS = [
    "run_id", "experiment_id", "world_id", "law_family", "seed", "condition", "society_type", "agent_count", "provider", "model_snapshot", "replicate", "pair_id", "config_hash", "question_text", "experiment_id_selected", "valid", "invalid_reason", "transport_success", "format_valid", "proposal_valid", "format_invalid_reason", "proposal_invalid_reason", "top1_score", "ig_selected", "ig_star", "top1_action_score", "ig_selected_action", "selected_action", "action_valid", "action_parameter_mismatch", "transport_valid", "schema_valid", "evidence_valid", "law_valid", "model_numeric_valid", "fully_scientifically_valid", "stage1_relation_valid", "stage1_relation_correct", "stage1_law_identification_correct", "stage1_mapping_correct", "stage1_abstention_appropriate", "selected_hypothesis_pair", "predicted_gap", "pair_discrimination_pass", "prediction_text_structured", "predicted_values", "prediction_max_abs_error", "prediction_consistency", "prediction_errors", "prediction_error_categories", "numeric_prediction_correct_count", "numeric_prediction_total_count", "numeric_prediction_accuracy", "shared_law_text", "shared_law_judgment", "candidate_law_id", "law_id_correct", "shared_law_correct", "mapping_valid", "stage1_valid", "stage1_json_valid", "stage1_transfer_eligible", "transfer_applied", "route_intervention", "stage1_artifact_sha256", "forwarded_artifact_sha256", "input_tokens", "output_tokens", "total_tokens", "api_calls", "unique_provider_calls", "full_workflow_calls", "full_workflow_tokens", "estimated_cost_usd", "provider_billed_cost_usd", "billed_cost", "attributed_full_workflow_cost", "usage_source", "budget_verified", "latency_ms", "run_status", "non_evidence",
]

PRIMARY_CONDITIONS = ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK")
CONTRASTS = (("B-A", "B_SINGLE_RELATED", "A_TARGET_ONLY"), ("C-D", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"), ("C-B", "C_SEQ2_TRANSFER", "B_SINGLE_RELATED"))


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"true", "1", "yes", "pass"}


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _strict_valid(row: dict[str, Any]) -> bool:
    if "fully_scientifically_valid" in row and row.get("fully_scientifically_valid", "") != "":
        return _bool(row.get("fully_scientifically_valid"))
    return _bool(row.get("valid"))


def _scientific_output_available(row: dict[str, Any]) -> bool:
    explicit = row.get("scientific_output_available")
    if explicit not in {None, ""}:
        return _bool(explicit)
    run_status = str(row.get("run_status", "")).strip().upper()
    if run_status and run_status != "COMPLETED":
        return False
    return bool(str(row.get("experiment_id_selected", "")).strip() and _json_object(row.get("selected_action")).get("experiment_id"))


def _action_valid(row: dict[str, Any]) -> bool:
    run_status = str(row.get("run_status", "")).strip().upper()
    if run_status in {"FAILED", "FAILED_TRANSPORT", "NOT_EXECUTED", "UPSTREAM_FAIL_FAST"}:
        return False
    if not _scientific_output_available(row):
        return False
    if str(row.get("transport_success", "")).strip().lower() in {"false", "0", "no"}:
        return False
    if not str(row.get("experiment_id_selected", "")).strip() or not _json_object(row.get("selected_action")).get("experiment_id"):
        return False
    if "action_valid" in row and row.get("action_valid", "") != "":
        return _bool(row.get("action_valid"))
    return _bool(row.get("valid"))


def _numeric_accuracy(row: dict[str, Any], tolerance: float = PREDICTION_TOLERANCE) -> tuple[int | None, int | None, float | None]:
    errors = _json_object(row.get("prediction_errors"))
    if not errors:
        return None, None, None
    numeric_errors = [float(value) for value in errors.values() if value is not None and _number(value) is not None]
    if not numeric_errors:
        return 0, len(errors), 0.0
    correct = sum(error <= tolerance for error in numeric_errors)
    return correct, len(errors), correct / len(errors)


def paired_metrics(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Return action-only and strict metrics without turning ineligible pairs into zero."""
    if left is None or right is None:
        return {
            "delta_action_only": None,
            "delta_strict": None,
            "action_pair_eligible": False,
            "strict_pair_eligible": False,
            "same_stage1_artifact": None,
            "stage1_transfer_eligible": None,
            "exclusion_reason": "missing_condition",
        }
    action_ok = _action_valid(left) and _action_valid(right) and _number(left.get("top1_action_score")) is not None and _number(right.get("top1_action_score")) is not None
    strict_ok = _strict_valid(left) and _strict_valid(right) and _number(left.get("top1_score")) is not None and _number(right.get("top1_score")) is not None
    left_hash = str(left.get("stage1_artifact_sha256", ""))
    right_hash = str(right.get("stage1_artifact_sha256", ""))
    same_artifact = None
    transfer_eligible = None
    if {left.get("condition"), right.get("condition")} == {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}:
        if not left_hash or not right_hash:
            same_artifact = None
            transfer_eligible = None
        else:
            same_artifact = left_hash == right_hash
            transfer_eligible = _bool(left.get("stage1_transfer_eligible")) and _bool(right.get("stage1_transfer_eligible"))
        if same_artifact is False:
            strict_ok = False
    reason = None
    if not strict_ok:
        missing = []
        if not _action_valid(left) or not _action_valid(right):
            missing.append("action_invalid")
        if not _strict_valid(left) or not _strict_valid(right):
            missing.append("at_least_one_scientifically_invalid")
        if same_artifact is False:
            missing.append("stage1_artifact_mismatch")
        elif same_artifact is None and {left.get("condition"), right.get("condition")} == {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}:
            missing.append("stage1_not_executed")
        reason = ";".join(missing) or "strict_fields_missing"
    return {
        "delta_action_only": (_number(left.get("top1_action_score")) - _number(right.get("top1_action_score"))) if action_ok else None,
        "delta_strict": (_number(left.get("top1_score")) - _number(right.get("top1_score"))) if strict_ok else None,
        "action_pair_eligible": action_ok,
        "strict_pair_eligible": strict_ok,
        "same_stage1_artifact": same_artifact,
        "stage1_transfer_eligible": transfer_eligible,
        "exclusion_reason": reason,
    }


def write_results(run_dir: str | Path, rows: list[dict[str, Any]]) -> Path:
    path = Path(run_dir) / "results.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in RESULT_FIELDS})
    return path


def read_results(run_dir: str | Path) -> list[dict[str, str]]:
    path = Path(run_dir) / "results.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_comparisons(run_dir: str | Path, rows: list[dict[str, Any]]) -> Path:
    grouped: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        row_key = (str(row.get("world_id")), str(row.get("replicate")), str(row.get("model_snapshot")), str(row.get("config_hash", "")), str(row.get("condition")))
        if row_key in seen:
            raise ValueError(f"duplicate analysis key: {row_key}")
        seen.add(row_key)
        grouped[(str(row.get("world_id")), str(row.get("replicate")), str(row.get("model_snapshot", "")), str(row.get("config_hash", "")))][str(row.get("condition"))] = row
    records: list[dict[str, Any]] = []
    for (world_id, replicate, model_snapshot, config_hash), values in sorted(grouped.items()):
        strict_values = {condition: row for condition, row in values.items() if _strict_valid(row) and _bool(row.get("proposal_valid", "true"))}

        def strict_delta(left: str, right: str) -> float | str:
            if left not in strict_values or right not in strict_values:
                return ""
            return round(float(strict_values[left]["top1_score"]) - float(strict_values[right]["top1_score"]), 6)

        def action_delta(left: str, right: str) -> float | str:
            pair = paired_metrics(values.get(left), values.get(right))
            return "" if pair["delta_action_only"] is None else round(float(pair["delta_action_only"]), 6)

        ba_pair = paired_metrics(values.get("B_SINGLE_RELATED"), values.get("A_TARGET_ONLY"))
        cd_pair = paired_metrics(values.get("C_SEQ2_TRANSFER"), values.get("D_SEQ2_BLOCK"))
        cb_pair = paired_metrics(values.get("C_SEQ2_TRANSFER"), values.get("B_SINGLE_RELATED"))
        records.append({
            "world_id": world_id,
            "replicate": replicate,
            "model_snapshot": model_snapshot,
            "config_hash": config_hash,
            # Legacy columns retain their old strict-valid semantics.
            "B_minus_A": strict_delta("B_SINGLE_RELATED", "A_TARGET_ONLY"),
            "C_minus_D": strict_delta("C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"),
            "C_minus_B": strict_delta("C_SEQ2_TRANSFER", "B_SINGLE_RELATED"),
            "C_minus_E": strict_delta("C_SEQ2_TRANSFER", "E_SEQ2_IRRELEVANT_TRANSFER"),
            "C_minus_F": strict_delta("C_SEQ2_TRANSFER", "F_SEQ2_MISALIGNED_TRANSFER"),
            "collab3_minus_B": strict_delta("S_COLLAB3", "B_SINGLE_RELATED"),
            "compete3_minus_B": strict_delta("S_COMPETE3", "B_SINGLE_RELATED"),
            "B_minus_A_action_only": action_delta("B_SINGLE_RELATED", "A_TARGET_ONLY"),
            "C_minus_D_action_only": action_delta("C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"),
            "C_minus_B_action_only": action_delta("C_SEQ2_TRANSFER", "B_SINGLE_RELATED"),
            "B_minus_A_strict": strict_delta("B_SINGLE_RELATED", "A_TARGET_ONLY"),
            "C_minus_D_strict": strict_delta("C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"),
            "C_minus_B_strict": strict_delta("C_SEQ2_TRANSFER", "B_SINGLE_RELATED"),
            "B_minus_A_action_pair_eligible": ba_pair["action_pair_eligible"],
            "C_minus_D_action_pair_eligible": cd_pair["action_pair_eligible"],
            "C_minus_B_action_pair_eligible": cb_pair["action_pair_eligible"],
            "B_minus_A_strict_pair_eligible": ba_pair["strict_pair_eligible"],
            "C_minus_D_strict_pair_eligible": cd_pair["strict_pair_eligible"],
            "C_minus_B_strict_pair_eligible": cb_pair["strict_pair_eligible"],
            "C_D_same_stage1_artifact": cd_pair["same_stage1_artifact"],
            "C_D_stage1_transfer_eligible": cd_pair["stage1_transfer_eligible"],
            "C_D_strict_exclusion_reason": cd_pair["exclusion_reason"],
            "valid_conditions": ",".join(sorted(strict_values)),
            "invalid_or_missing_conditions": ",".join(condition for condition in PRIMARY_CONDITIONS if condition not in strict_values),
            "all_planned_success": all(condition in strict_values for condition in PRIMARY_CONDITIONS),
        })
    path = Path(run_dir) / "paired_deltas.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        fields = list(records[0]) if records else ["world_id", "replicate", "model_snapshot", "config_hash"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    return path


def write_report(run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    rows = read_results(run_dir)
    manifest = {}
    if (run_dir / "manifest.json").exists():
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    by_condition: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_condition[row.get("condition", "")].append(row)
    lines = [
        "# Mini Science Society run report",
        "",
        f"- run_id: `{manifest.get('run_id', run_dir.name)}`",
        f"- provider: `{manifest.get('provider', 'unknown')}`",
        f"- evidence status: `{'NON_EVIDENCE' if manifest.get('provider') in {'mock', 'behavioral-mock'} else 'REAL_PROVIDER_PILOT'}`",
        "- scientific status: engineering pilot only; no significance or general mechanism claim",
        "",
        "## Condition summary",
        "",
        "| condition | n | action-valid rate | mean action score | mean numeric accuracy | strict-valid rate | mean strict score | workflow calls | provider billed cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition in sorted(by_condition):
        group = by_condition[condition]
        evaluated_group = [row for row in group if _scientific_output_available(row)]
        action_scores = [float(row.get("top1_action_score", 0.0) or 0.0) for row in evaluated_group]
        strict_scores = [float(row.get("top1_score", 0.0) or 0.0) for row in evaluated_group]
        action_valid = sum(_action_valid(row) for row in evaluated_group)
        strict_valid = sum(_strict_valid(row) for row in evaluated_group)
        numeric_rates = [_numeric_accuracy(row)[2] for row in evaluated_group if _numeric_accuracy(row)[2] is not None]
        calls = sum(int(float(row.get("full_workflow_calls", row.get("api_calls", 0)) or 0)) for row in group)
        costs = [float(row["provider_billed_cost_usd"]) for row in group if row.get("provider_billed_cost_usd") not in {"", "None"}]
        cost_text = f"{sum(costs):.8f}" if costs else "UNVERIFIED"
        numeric_text = f"{sum(numeric_rates) / len(numeric_rates):.3f}" if numeric_rates else "UNDEFINED"
        action_rate_text = f"{action_valid / len(evaluated_group):.3f}" if evaluated_group else "UNDEFINED"
        action_score_text = f"{sum(action_scores) / len(action_scores):.3f}" if action_scores else "UNDEFINED"
        strict_rate_text = f"{strict_valid / len(evaluated_group):.3f}" if evaluated_group else "UNDEFINED"
        strict_score_text = f"{sum(strict_scores) / len(strict_scores):.3f}" if strict_scores else "UNDEFINED"
        lines.append(f"| {condition} | {len(group)} | {action_rate_text} | {action_score_text} | {numeric_text} | {strict_rate_text} | {strict_score_text} | {calls} | {cost_text} |")
    lines.extend([
        "",
        "## Fixed contrasts",
        "",
        "`B-A` is the related-source versus matched-unrelated-source contrast; `C-D` is the same stage-1 artifact with transfer enabled versus router-blocked; `C-B` is an exploratory organization contrast.",
        "",
        "The independent oracle scores discrimination within the frozen candidate set. It does not evaluate scientific novelty. `COLLAB3` and `COMPETE3` use more model calls and are not equal-compute superiority tests.",
        "",
    ])
    failures = [row for row in rows if str(row.get("valid", "")).lower() != "true"]
    if failures:
        lines.extend(["## Independent failure accounting", "", f"- invalid_or_unfinished_rows: `{len(failures)}` of `{len(rows)}`", "- These rows are excluded from valid-only scientific contrasts.", ""])
        for row in failures:
            lines.append(f"- `{row.get('condition', '')}`: `{row.get('run_status', '')}` / `{row.get('invalid_reason', '') or row.get('proposal_invalid_reason', '')}`")
        lines.append("")
    if any(row.get("provider_billed_cost_usd", "") in {"", "None"} for row in rows):
        lines.append("`BUDGET_NOT_VERIFIED`: at least one row has no provider-reported billed cost; local estimates are not provider bills.")
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_comparisons(run_dir, rows)
    return run_dir / "report.md"


def _run_config(run_dir: Path) -> dict[str, Any]:
    for name in ("config_frozen.json", "manifest.json"):
        path = run_dir / name
        if not path.exists():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _prediction_vector_diagnostic(view: Any, experiment_id: str, predicted: dict[str, Any], *, tolerance: float) -> dict[str, Any]:
    """Compare a submitted vector with every public menu action.

    This is diagnostic only. It never changes the submitted vector or strict
    scoring result; it helps distinguish arithmetic mistakes from using the
    wrong menu parameters.
    """
    numeric_models = [model for model in view.candidate_models if isinstance(predicted.get(model), (int, float)) and not isinstance(predicted.get(model), bool) and math.isfinite(float(predicted[model]))]
    action_distances: dict[str, float] = {}
    nominal_k = public_nominal_k(view.target_notes)
    for item in view.experiments:
        candidate_id = str(item["experiment_id"])
        errors = [abs(float(predicted[model]) - predict(model, float(item["x0"]), float(item["measure_t"]), nominal_k)) for model in numeric_models]
        action_distances[candidate_id] = max(errors) if errors else float("inf")
    nearest = min(action_distances, key=action_distances.get) if action_distances else ""
    selected_distance = action_distances.get(str(experiment_id), float("inf"))
    return {
        "nearest_menu_action": nearest,
        "nearest_menu_max_abs_error": action_distances.get(nearest),
        "selected_menu_max_abs_error": selected_distance,
        "vector_closer_to_other_action": bool(nearest and nearest != str(experiment_id) and action_distances[nearest] + tolerance < selected_distance),
    }


def _prediction_rows(project_root: Path, run_dir: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    config = _run_config(run_dir)
    worlds_subdir = str(config.get("worlds_subdir", "worlds_v5p4_dev"))
    result: list[dict[str, Any]] = []
    views: dict[str, Any] = {}
    for row in rows:
        world_id = str(row.get("world_id", ""))
        if world_id not in views:
            views[world_id] = load_world(project_root, world_id, "related", worlds_subdir=worlds_subdir)
        view = views[world_id]
        experiment_id = str(row.get("experiment_id_selected", ""))
        predicted = _json_object(row.get("predicted_values"))
        evaluated = bool(_scientific_output_available(row) and experiment_id and predicted)
        audit = audit_prediction_values(view, experiment_id, predicted) if evaluated else {}
        vector = _prediction_vector_diagnostic(view, experiment_id, predicted, tolerance=PREDICTION_TOLERANCE) if evaluated else {"nearest_menu_action": "", "nearest_menu_max_abs_error": None, "selected_menu_max_abs_error": None, "vector_closer_to_other_action": None}
        for model in view.candidate_models:
            reported = predicted.get(model) if evaluated else None
            expected = audit.get("expected_values", {}).get(model) if evaluated else None
            error = audit.get("prediction_errors", {}).get(model) if evaluated else None
            category = audit.get("prediction_error_categories", {}).get(model, "missing_model") if evaluated else "NOT_EVALUATED"
            if evaluated and category == "abs_error_exceeds_tolerance" and isinstance(reported, (int, float)) and not isinstance(reported, bool):
                other_matches = []
                for item in view.experiments:
                    candidate_id = str(item["experiment_id"])
                    if candidate_id == experiment_id:
                        continue
                    other_expected = predict(model, float(item["x0"]), float(item["measure_t"]), public_nominal_k(view.target_notes))
                    if abs(float(reported) - other_expected) <= PREDICTION_TOLERANCE:
                        other_matches.append(candidate_id)
                category = f"correct_for_other_menu_action:{other_matches[0]}" if other_matches else "formula_or_parameter_error"
            result.append({
                "world_id": world_id,
                "replicate": row.get("replicate", ""),
                "condition": row.get("condition", ""),
                "pair_id": row.get("pair_id", ""),
                "experiment_id": experiment_id,
                "x0": _json_object(row.get("selected_action")).get("x0"),
                "measure_t": _json_object(row.get("selected_action")).get("measure_t"),
                "hypothesis_id": model,
                "reported": reported,
                "public_formula_recomputed": expected,
                "abs_error": error,
                "tolerance": PREDICTION_TOLERANCE,
                "passed": category == "pass" if evaluated else None,
                "error_category": category,
                **vector,
            })
    return result


def analyze_run(project_root: str | Path, run_dir: str | Path, output_dir: str | Path) -> dict[str, Path]:
    """Create a read-only dual-metric analysis for an existing run."""
    root = Path(project_root).resolve()
    run_path = Path(run_dir).resolve()
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    rows = read_results(run_path)
    if not rows:
        raise ValueError(f"run has no results.csv rows: {run_path}")
    required_columns = {"world_id", "replicate", "condition", "top1_action_score", "action_valid", "top1_score", "fully_scientifically_valid"}
    missing_columns = sorted(required_columns - set(rows[0]))
    if missing_columns:
        raise ValueError(f"results.csv is missing required analysis columns: {','.join(missing_columns)}")
    per_condition: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        evaluated = _scientific_output_available(row)
        correct, total, rate = _numeric_accuracy(row)
        selected_action = _json_object(row.get("selected_action"))
        record = {
            "world_id": row.get("world_id", ""),
            "replicate": row.get("replicate", ""),
            "pair_id": row.get("pair_id", ""),
            "condition": row.get("condition", ""),
            "request_id": row.get("request_id", ""),
            "experiment_id": row.get("experiment_id_selected", ""),
            "x0": selected_action.get("x0"),
            "measure_t": selected_action.get("measure_t"),
            "action_valid": _action_valid(row) if evaluated else None,
            "action_selection_success": _action_valid(row) if evaluated else None,
            "ig_selected_nats": (_number(row.get("ig_selected_action")) if _number(row.get("ig_selected_action")) is not None else _number(row.get("ig_selected"))) if evaluated else None,
            "top1_action_score": _number(row.get("top1_action_score")) if evaluated else None,
            "model_numeric_valid": _bool(row.get("model_numeric_valid")) if evaluated else None,
            "numeric_prediction_correct_count": correct if evaluated else None,
            "numeric_prediction_total_count": total if evaluated else None,
            "numeric_prediction_accuracy": rate if evaluated else None,
            "fully_scientifically_valid": _strict_valid(row) if evaluated else None,
            "strict_scientific_validity_success": _strict_valid(row) if evaluated else None,
            "strict_top1_score": _number(row.get("top1_score")) if evaluated else None,
            "numeric_max_abs_error": _number(row.get("prediction_max_abs_error")) if evaluated else None,
            "prediction_consistency": row.get("prediction_consistency", "") if evaluated else "NOT_EVALUATED",
            "stage1_law_id": row.get("candidate_law_id", "") if evaluated else None,
            "stage1_relation_correct": row.get("stage1_relation_correct", "") if evaluated else None,
            "stage1_mapping_correct": row.get("stage1_mapping_correct", "") if evaluated else None,
            "stage1_transfer_eligible": row.get("stage1_transfer_eligible", "") if evaluated else None,
            "route_mode": row.get("route_intervention", ""),
            "stage1_artifact_hash": row.get("stage1_artifact_sha256", ""),
            "forwarded_artifact_hash": row.get("forwarded_artifact_sha256", ""),
            "invalid_reason": row.get("invalid_reason", "") or row.get("prediction_consistency", ""),
            "input_tokens": row.get("input_tokens", ""),
            "output_tokens": row.get("output_tokens", ""),
            "full_workflow_tokens": row.get("full_workflow_tokens", ""),
            "unique_provider_calls": row.get("unique_provider_calls", ""),
            "reserved_estimated_cost_usd": row.get("reserved_estimated_cost_usd", row.get("estimated_cost_usd", "")),
            "provider_billed_cost_usd": row.get("provider_billed_cost_usd", ""),
            "billing_verified": row.get("provider_billed_cost_usd", "") not in {"", "None", "null"},
        }
        per_condition.append(record)
        key = (str(row.get("world_id", "")), str(row.get("replicate", "")), str(row.get("model_snapshot", "")), str(row.get("config_hash", "")))
        if str(row.get("condition", "")) in PRIMARY_CONDITIONS:
            if str(row.get("condition")) in grouped[key]:
                raise ValueError(f"duplicate analysis key: {key}:{row.get('condition')}")
            grouped[key][str(row.get("condition"))] = row

    per_path = destination / "action_and_strict_per_condition.csv"
    with per_path.open("w", newline="", encoding="utf-8") as handle:
        fields = list(per_condition[0])
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(per_condition)

    pair_records: list[dict[str, Any]] = []
    for (world_id, replicate, model_snapshot, config_hash), values in sorted(grouped.items()):
        for contrast, left_name, right_name in CONTRASTS:
            pair = paired_metrics(values.get(left_name), values.get(right_name))
            pair_records.append({
                "world_id": world_id,
                "replicate": replicate,
                "pair_id": (values.get(left_name) or values.get(right_name) or {}).get("pair_id", f"{world_id}_R{replicate}"),
                "model_snapshot": model_snapshot,
                "config_hash": config_hash,
                "contrast": contrast,
                "left_condition": left_name,
                "right_condition": right_name,
                "delta_action_only": pair["delta_action_only"],
                "delta_strict": pair["delta_strict"],
                "action_pair_eligible": pair["action_pair_eligible"],
                "strict_pair_eligible": pair["strict_pair_eligible"],
                "strict_status": "ELIGIBLE" if pair["strict_pair_eligible"] else "UNDEFINED",
                "same_stage1_artifact": pair["same_stage1_artifact"],
                "stage1_transfer_eligible": pair["stage1_transfer_eligible"],
                "validity_reason": pair["exclusion_reason"],
            })
    pair_path = destination / "paired_effects_action_strict.csv"
    with pair_path.open("w", newline="", encoding="utf-8") as handle:
        fields = list(pair_records[0]) if pair_records else ["world_id", "replicate", "contrast"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(pair_records)

    prediction_path = destination / "prediction_error_details.csv"
    prediction_records = _prediction_rows(root, run_path, rows)
    with prediction_path.open("w", newline="", encoding="utf-8") as handle:
        fields = list(prediction_records[0]) if prediction_records else ["world_id", "condition", "hypothesis_id"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(prediction_records)

    ledger = []
    ledger_path = run_path / "call_ledger.jsonl"
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(value.get("request_id", "")) and str(value.get("status", "")).upper() != "STARTED":
                    ledger.append(value)
    unique_by_id = {str(item.get("request_id")): item for item in ledger}
    unique_ledger = list(unique_by_id.values())
    completed_ledger = [item for item in unique_ledger if str(item.get("request_status", "")).lower() == "completed"]
    failed_ledger = [item for item in unique_ledger if item not in completed_ledger]
    input_tokens = sum(int(item.get("actual_input_tokens") or item.get("input_tokens") or 0) for item in completed_ledger)
    output_tokens = sum(int(item.get("actual_output_tokens") or item.get("output_tokens") or 0) for item in completed_ledger)
    completed_usage_costs = [float(item["local_response_estimate_usd"]) for item in completed_ledger if item.get("local_response_estimate_usd") not in {None, ""}]
    completed_usage_cost = sum(completed_usage_costs)
    unknown_reserved_cost = sum(float(item.get("reserved_estimated_cost_usd") or item.get("estimated_cost_usd") or 0.0) for item in failed_ledger)
    all_reserved_cost = sum(float(item.get("reserved_estimated_cost_usd") or item.get("estimated_cost_usd") or 0.0) for item in unique_ledger)
    billed_costs = [float(item["provider_billed_cost_usd"]) for item in completed_ledger if item.get("provider_billed_cost_usd") not in {None, "", "null", "None"}]
    budget_record = {
        "cost_accounting_version": "separated_v2",
        "run_id": run_path.name,
        "unique_attempts_count": len(unique_ledger),
        "unique_completed_count": len(completed_ledger),
        "unique_failed_count": len(failed_ledger),
        "ambiguous_attempt_count": len(failed_ledger),
        "unique_provider_input_tokens": input_tokens,
        "unique_provider_output_tokens": output_tokens,
        "unique_provider_total_tokens": input_tokens + output_tokens,
        "unique_provider_tokens_completed_only": input_tokens + output_tokens,
        "condition_workflow_calls_attributed": sum(int(float(row.get("full_workflow_calls") or row.get("api_calls") or 0)) for row in rows),
        "condition_workflow_tokens_attributed": sum(int(float(row.get("full_workflow_tokens") or 0)) for row in rows),
        "completed_response_usage_local_estimate_usd": completed_usage_cost,
        "completed_usage_cost_unavailable_count": len(completed_ledger) - len(completed_usage_costs),
        "unknown_billable_reserved_estimate_usd": unknown_reserved_cost,
        "all_attempts_reserved_estimate_usd": all_reserved_cost,
        "legacy_local_estimated_cost_usd_unique_mixed_not_usage": completed_usage_cost + unknown_reserved_cost,
        "provider_billed_cost_usd": sum(billed_costs) if billed_costs else None,
        "provider_billing_verified": bool(billed_costs),
        "automatic_retries": 0,
    }
    budget_path = destination / "budget_unique_vs_attributed.csv"
    with budget_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(budget_record))
        writer.writeheader()
        writer.writerow(budget_record)

    report_path = destination / "legacy_reanalysis.md"
    lines = ["# V5P8 read-only reanalysis of an existing run", "", f"- source_run: `{run_path}`", "- source_mutation: `NONE`", "- strict pair differences are `UNDEFINED` when either side is not fully scientifically valid.", "", "| condition | selected action | IG nats | action-only score | numeric accuracy | strict valid | max abs error |", "|---|---|---:|---:|---:|---|---:|"]
    for row in per_condition:
        lines.append(f"| {row['condition']} | {row['experiment_id']} | {row['ig_selected_nats']} | {row['top1_action_score']} | {row['numeric_prediction_accuracy']} | {row['fully_scientifically_valid']} | {row['numeric_max_abs_error']} |")
    lines.extend(["", "## Paired contrasts", ""])
    for item in pair_records:
        lines.append(f"- `{item['contrast']}` action-only: `{item['delta_action_only'] if item['delta_action_only'] is not None else 'UNDEFINED'}`; strict: `{item['delta_strict'] if item['delta_strict'] is not None else 'UNDEFINED'}`; reason: `{item['validity_reason'] or 'eligible'}`")
    lines.extend(["", "## Numeric failure diagnosis", "", "Each mechanism row below is independently recomputed from the public formula and the selected legal menu action. `formula_or_parameter_error` means the value is not within the frozen 0.02 tolerance for the selected action and does not match another legal action within that tolerance; the submitted value is never replaced."])
    by_condition = defaultdict(list)
    for item in prediction_records:
        by_condition[item["condition"]].append(item)
    for condition, items in sorted(by_condition.items()):
        bad = [item for item in items if not item["passed"]]
        categories = ", ".join(f"{item['hypothesis_id']}={item['error_category']}" for item in bad)
        lines.append(f"- `{condition}`: {categories or 'all mechanisms passed'}; selected action vector nearest public menu action=`{items[0]['nearest_menu_action']}` (selected max error={items[0]['selected_menu_max_abs_error']}, nearest max error={items[0]['nearest_menu_max_abs_error']}).")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"per_condition": per_path, "paired_effects": pair_path, "prediction_errors": prediction_path, "budget": budget_path, "report": report_path}


def _public_observations(text: str) -> list[dict[str, float]]:
    legacy = re.compile(r"x0=([0-9.]+), t=([0-9.]+), measured_state=([0-9.]+)")
    v5p11 = re.compile(r"target_state=([0-9.]+), target_time=([0-9.]+) s, target_x0=([0-9.]+)")
    legacy_rows = [{"x0": float(x0), "t": float(t), "observed_x": float(value)} for x0, t, value in legacy.findall(text)]
    return legacy_rows or [{"x0": float(x0), "t": float(t), "observed_x": float(value)} for value, t, x0 in v5p11.findall(text)]


def _public_nominal_k(text: str) -> float:
    match = re.search(r"(?:Nominal candidate-rate|Target .*?candidate-rate) k=([0-9.]+)", text, flags=re.IGNORECASE)
    if match is None:
        raise ValueError("public target notes do not contain a nominal candidate rate")
    return float(match.group(1))


def write_oracle_audit(project_root: str | Path, config: Any, output_path: str | Path) -> Path:
    """Write a descriptive world/action audit without changing any world."""
    root = Path(project_root)
    records: list[dict[str, Any]] = []
    for world_id in configured_world_ids(root, config):
        public = root / "data" / config.worlds_subdir / world_id
        private = root / "private" / config.private_worlds_subdir / world_id
        manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
        truth = json.loads((private / "hidden_truth.json").read_text(encoding="utf-8"))
        menu = json.loads((public / "candidate_experiments.json").read_text(encoding="utf-8"))["experiments"]
        target_notes = (public / "target_notes.md").read_text(encoding="utf-8")
        observations = _public_observations(target_notes)
        public_k = _public_nominal_k(target_notes)
        audit = oracle_scores(observations, menu, float(truth["true_k"]), float(manifest["measurement_sigma"]), models=tuple(config.candidate_models), n_grid=config.integration_grid)
        audit_4001 = oracle_scores(observations, menu, float(truth["true_k"]), float(manifest["measurement_sigma"]), models=tuple(config.candidate_models), n_grid=4001)
        random_mean = sum(audit["top1_score"].values()) / len(audit["top1_score"])
        fixed_e04 = float(audit["top1_score"].get("E04", 0.0))
        max_time = max(menu, key=lambda item: float(item["measure_t"]))["experiment_id"]
        max_x0 = max(menu, key=lambda item: float(item["x0"]))["experiment_id"]
        best = audit["best_experiment_ids"][0]
        for item in menu:
            experiment_id = str(item["experiment_id"])
            predictions = [predict(model, float(item["x0"]), float(item["measure_t"]), float(truth["true_k"])) for model in config.candidate_models]
            public_predictions = [predict(model, float(item["x0"]), float(item["measure_t"]), public_k) for model in config.candidate_models]
            records.append({
                "world_id": world_id,
                "law_family": truth["true_law"],
                "experiment_id": experiment_id,
                "ig_nats": audit["ig_nats"][experiment_id],
                "top1_score": audit["top1_score"][experiment_id],
                "prediction_gap_sigma": (max(predictions) - min(predictions)) / float(manifest["measurement_sigma"]),
                "public_predicted_gap_sigma": (max(public_predictions) - min(public_predictions)) / float(manifest["measurement_sigma"]),
                "ig_4001": audit_4001["ig_nats"][experiment_id],
                "integration_abs_diff": abs(audit["ig_nats"][experiment_id] - audit_4001["ig_nats"][experiment_id]),
                "fixed_e04_score": fixed_e04,
                "random_mean_score": random_mean,
                "max_time_rule_score": audit["top1_score"].get(max_time, 0.0),
                "max_x0_rule_score": audit["top1_score"].get(max_x0, 0.0),
                "oracle_best": experiment_id == best,
            })
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0]) if records else ["world_id", "experiment_id"]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    return destination


def write_cheap_baselines(project_root: str | Path, config: Any, output_path: str | Path) -> Path:
    """Write cheap, pre-LLM baselines using public rules and private scoring only."""
    root = Path(project_root)
    records: list[dict[str, Any]] = []
    for world_id in configured_world_ids(root, config):
        public = root / "data" / config.worlds_subdir / world_id
        private = root / "private" / config.private_worlds_subdir / world_id
        manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
        truth = json.loads((private / "hidden_truth.json").read_text(encoding="utf-8"))
        menu = json.loads((public / "candidate_experiments.json").read_text(encoding="utf-8"))["experiments"]
        target_notes = (public / "target_notes.md").read_text(encoding="utf-8")
        observations = _public_observations(target_notes)
        public_k = _public_nominal_k(target_notes)
        audit = oracle_scores(observations, menu, float(truth["true_k"]), float(manifest["measurement_sigma"]), models=tuple(config.candidate_models), n_grid=config.integration_grid)
        scores = audit["top1_score"]
        random_mean = sum(scores.values()) / len(scores)
        fixed_e04_id = "E04"
        max_time_id = max(menu, key=lambda item: float(item["measure_t"]))["experiment_id"]
        max_x0_id = max(menu, key=lambda item: float(item["x0"]))["experiment_id"]
        predicted_gap_by_action = {
            str(item["experiment_id"]): (max(
                predict(model, float(item["x0"]), float(item["measure_t"]), public_k)
                for model in config.candidate_models
            ) - min(
                predict(model, float(item["x0"]), float(item["measure_t"]), public_k)
                for model in config.candidate_models
            )) / float(manifest["measurement_sigma"])
            for item in menu
        }
        simple_id = max(predicted_gap_by_action, key=predicted_gap_by_action.get)
        cheap_scores = {
            "fixed_e04": float(scores.get(fixed_e04_id, 0.0)),
            "max_time": float(scores.get(max_time_id, 0.0)),
            "max_x0": float(scores.get(max_x0_id, 0.0)),
            "simple_predicted_gap": float(scores.get(simple_id, 0.0)),
        }
        best_cheap_name = max(cheap_scores, key=cheap_scores.get)
        records.append({
            "world_id": world_id,
            "law_family": truth["true_law"],
            "public_nominal_k": public_k,
            "random_mean_score": round(random_mean, 6),
            "fixed_e04_experiment": fixed_e04_id,
            "fixed_e04_score": round(cheap_scores["fixed_e04"], 6),
            "max_time_experiment": max_time_id,
            "max_time_score": round(cheap_scores["max_time"], 6),
            "max_x0_experiment": max_x0_id,
            "max_x0_score": round(cheap_scores["max_x0"], 6),
            "simple_predicted_gap_experiment": simple_id,
            "simple_predicted_gap_score": round(cheap_scores["simple_predicted_gap"], 6),
            "cheap_best_rule": best_cheap_name,
            "cheap_best_score": round(cheap_scores[best_cheap_name], 6),
            "oracle_best_experiment": audit["best_experiment_ids"][0],
            "oracle_score": round(float(max(scores.values())), 6),
            "oracle_gap": round(float(max(scores.values()) - cheap_scores[best_cheap_name]), 6),
        })
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0]) if records else ["world_id"]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    return destination


def write_baselines_by_world(project_root: str | Path, config: Any, output_path: str | Path, *, random_seed: int | None = None) -> Path:
    """Write Oracle, fixed, random, and public-formula baseline rows.

    Selection is performed before private scoring. The public heuristic only
    sees a ``WorldPublicView`` and the public nominal rate; private files are
    opened only afterward to score the chosen action.
    """
    root = Path(project_root).resolve()
    base_seed = int(random_seed if random_seed is not None else (config.plan_seed if config.plan_seed is not None else config.seed))
    records: list[dict[str, Any]] = []
    for index, world_id in enumerate(configured_world_ids(root, config)):
        public_view = load_world(root, world_id, "related", worlds_subdir=config.worlds_subdir)
        public_dir = root / "data" / config.worlds_subdir / world_id
        private_dir = root / "private" / config.private_worlds_subdir / world_id
        manifest = json.loads((public_dir / "manifest.json").read_text(encoding="utf-8"))
        truth = json.loads((private_dir / "hidden_truth.json").read_text(encoding="utf-8"))
        menu = list(public_view.experiments)
        audit = oracle_scores(
            _public_observations(public_view.target_notes),
            menu,
            float(truth["true_k"]),
            float(manifest["measurement_sigma"]),
            models=tuple(config.candidate_models),
            n_grid=config.integration_grid,
        )
        scores = {str(key): float(value) for key, value in audit["top1_score"].items()}
        oracle_action = str(audit["best_experiment_ids"][0])
        public_k = _public_nominal_k(public_view.target_notes)
        target_only_spread = {
            str(item["experiment_id"]): max(predict(model, float(item["x0"]), float(item["measure_t"]), public_k) for model in public_view.candidate_models)
            - min(predict(model, float(item["x0"]), float(item["measure_t"]), public_k) for model in public_view.candidate_models)
            for item in menu
        }
        source_public_k = float(manifest.get("source_public_k", public_k))
        public_spread = {
            str(item["experiment_id"]): max(predict(model, float(item["x0"]), float(item["measure_t"]), source_public_k) for model in public_view.candidate_models)
            - min(predict(model, float(item["x0"]), float(item["measure_t"]), source_public_k) for model in public_view.candidate_models)
            for item in menu
        }
        fixed_action = "E04" if any(str(item["experiment_id"]) == "E04" for item in menu) else str(menu[0]["experiment_id"])
        random_rng = random.Random(base_seed + index * 1009)
        random_action = str(menu[random_rng.randrange(len(menu))]["experiment_id"])
        random_scores = list(scores.values())
        random_expected = sum(random_scores) / len(random_scores)
        random_variance = sum((value - random_expected) ** 2 for value in random_scores) / len(random_scores)
        choices = [
            ("ORACLE_UPPER", oracle_action, None, False, "private_oracle_upper_reference"),
            ("FIXED_E04", fixed_action, None, True, "fixed_experiment_id"),
            ("RANDOM", random_action, base_seed + index * 1009, True, "uniform_menu_with_preregistered_seed"),
            ("PUBLIC_HEURISTIC", max(public_spread, key=public_spread.get), None, True, "max_public_candidate_prediction_spread"),
        ]
        if str(getattr(config, "score_version", "")) == "v5p11":
            choices.append(("TARGET_ONLY_HEURISTIC", max(target_only_spread, key=target_only_spread.get), None, True, "max_target_only_candidate_prediction_spread"))
        for baseline, chosen, seed, public_only, basis in choices:
            records.append({
                "world_id": world_id,
                "law_family": truth.get("true_law", ""),
                "baseline": baseline,
                "chosen_experiment_id": chosen,
                "action_score": scores.get(chosen),
                "oracle_action": oracle_action,
                "oracle_score": scores.get(oracle_action),
                "seed": seed,
                "public_only_verified": public_only,
                "selection_basis": basis,
                "expected_action_score": random_expected if baseline == "RANDOM" else scores.get(chosen),
                "action_score_variance": random_variance if baseline == "RANDOM" else 0.0,
                "public_prediction_spread": public_spread.get(chosen),
            })
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0]) if records else ["world_id", "baseline"]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    return destination


def write_world_difficulty_audit(project_root: str | Path, config: Any, output_path: str | Path) -> Path:
    root = Path(project_root).resolve()
    rows: list[dict[str, Any]] = []
    for world_id in configured_world_ids(root, config):
        public_dir = root / "data" / config.worlds_subdir / world_id
        private_dir = root / "private" / config.private_worlds_subdir / world_id
        manifest = json.loads((public_dir / "manifest.json").read_text(encoding="utf-8"))
        truth = json.loads((private_dir / "hidden_truth.json").read_text(encoding="utf-8"))
        menu = json.loads((public_dir / "candidate_experiments.json").read_text(encoding="utf-8"))["experiments"]
        target_notes = (public_dir / "target_notes.md").read_text(encoding="utf-8")
        audit = oracle_scores(_public_observations(target_notes), menu, float(truth["true_k"]), float(manifest["measurement_sigma"]), models=tuple(config.candidate_models), n_grid=config.integration_grid)
        rows.append({
            "world_id": world_id,
            "law_family": truth.get("true_law", ""),
            "menu_size": len(menu),
            "candidate_model_count": len(config.candidate_models),
            "measurement_sigma": manifest.get("measurement_sigma"),
            "ig_star": audit.get("ig_star"),
            "oracle_best_experiment_id": audit.get("best_experiment_ids", [""])[0],
            "oracle_best_score": max(audit.get("top1_score", {}).values()),
            "oracle_scores_distinct": len(set(round(float(value), 8) for value in audit.get("top1_score", {}).values())),
            "related_source_present": (public_dir / "source_related.md").is_file(),
            "irrelevant_source_present": (public_dir / "source_irrelevant.md").is_file(),
        })
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["world_id"]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return destination
