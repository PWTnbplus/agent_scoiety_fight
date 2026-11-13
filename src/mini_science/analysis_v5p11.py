from __future__ import annotations

"""V5-P11 analysis with explicit missingness, raw/assisted split and clusters."""

import csv
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any

from .analysis import write_baselines_by_world, write_oracle_audit
from .config import load_config
from .metrics.numeric_ability_split import split_numeric_ability
from .public_loader import load_world

CONDITIONS = ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK")
CONTRASTS = (("B-A", "B_SINGLE_RELATED", "A_TARGET_ONLY"), ("C-D", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"), ("C-B", "C_SEQ2_TRANSFER", "B_SINGLE_RELATED"))


def _bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes", "pass"}


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _executed(row: dict[str, Any]) -> bool:
    return str(row.get("run_status", "")).upper() == "COMPLETED" and _bool(row.get("scientific_output_available", True)) and bool(str(row.get("experiment_id_selected", "")))


def _structural_valid(row: dict[str, Any]) -> bool:
    if not _executed(row):
        return False
    checks = (row.get("action_valid"), row.get("schema_valid"), row.get("evidence_valid"))
    if any(value not in {None, ""} and not _bool(value) for value in checks):
        return False
    if str(row.get("condition")) in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}:
        if row.get("stage1_valid") not in {None, ""} and not _bool(row.get("stage1_valid")):
            return False
        if row.get("mapping_valid") not in {None, ""} and not _bool(row.get("mapping_valid")):
            return False
    return True


def _calculator_recomputation_ok(row: dict[str, Any]) -> bool:
    value = row.get("calculator_recomputation_success")
    if value not in {None, ""} and not _bool(value):
        return False
    return _float(row.get("calculator_assisted_diagnostic_score", row.get("assisted_calculator_accuracy"))) == 1.0


def assisted_diagnostic_eligible(row: dict[str, Any]) -> bool:
    """Eligibility for an action-level calculator-assisted diagnostic.

    This deliberately excludes raw numeric validity and raw-gated top1_score.
    It is an action diagnostic, not proof of strict scientific validity.
    """
    return _structural_valid({**row, "condition": "A_TARGET_ONLY"}) and _calculator_recomputation_ok(row)


def assisted_scientific_eligible(row: dict[str, Any]) -> bool:
    """Eligibility for the stricter assisted comparison with C/D routing gates."""
    if not _structural_valid(row) or not _calculator_recomputation_ok(row):
        return False
    return True


def calculate_assisted_diagnostic_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Compare action value after public-formula recomputation.

    The returned value is intentionally named a diagnostic. It never changes
    ``fully_scientifically_valid`` and never substitutes for raw Agent math.
    """
    eligible = assisted_diagnostic_eligible(left) and assisted_diagnostic_eligible(right)
    left_score = _float(left.get("top1_action_score"))
    right_score = _float(right.get("top1_action_score"))
    if not eligible or left_score is None or right_score is None:
        return {"delta": None, "status": "UNDEFINED", "metric_mode": "CALCULATOR_ASSISTED_DIAGNOSTIC", "exclusion_reason": "missing_or_structurally_invalid_or_calculator_failed"}
    return {"delta": left_score - right_score, "status": "ELIGIBLE", "metric_mode": "CALCULATOR_ASSISTED_DIAGNOSTIC", "exclusion_reason": ""}


def calculate_assisted_scientific_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Action delta with the additional C/D Stage1 validity gate."""
    eligible = assisted_scientific_eligible(left) and assisted_scientific_eligible(right)
    left_score = _float(left.get("top1_action_score"))
    right_score = _float(right.get("top1_action_score"))
    if not eligible or left_score is None or right_score is None:
        return {"delta": None, "status": "UNDEFINED", "metric_mode": "CALCULATOR_ASSISTED_SCIENTIFIC_DIAGNOSTIC", "exclusion_reason": "strict_assisted_stage1_or_structure_invalid"}
    return {"delta": left_score - right_score, "status": "ELIGIBLE", "metric_mode": "CALCULATOR_ASSISTED_SCIENTIFIC_DIAGNOSTIC", "exclusion_reason": ""}


def calculate_strict_raw_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_score = _float(left.get("top1_score"))
    right_score = _float(right.get("top1_score"))
    eligible = _executed(left) and _executed(right) and _bool(left.get("fully_scientifically_valid")) and _bool(right.get("fully_scientifically_valid")) and left_score is not None and right_score is not None
    if not eligible:
        return {"delta": None, "status": "UNDEFINED", "metric_mode": "STRICT_RAW_SCIENTIFIC", "exclusion_reason": "strict_raw_invalid_or_missing"}
    return {"delta": left_score - right_score, "status": "ELIGIBLE", "metric_mode": "STRICT_RAW_SCIENTIFIC", "exclusion_reason": ""}


def _scientific_diagnostic_reason(row: dict[str, Any]) -> str:
    """Explain an invalid row without changing the frozen raw result."""
    if not _executed(row):
        return str(row.get("run_status") or row.get("invalid_reason") or "NOT_EXECUTED")
    reasons: list[str] = []
    if str(row.get("invalid_reason", "")).strip():
        reasons.append(str(row["invalid_reason"]))
    if row.get("action_valid") not in {None, ""} and not _bool(row.get("action_valid")):
        reasons.append("action_invalid")
    for field, label in (("schema_valid", "schema_invalid"), ("evidence_valid", "evidence_invalid"), ("mapping_valid", "mapping_invalid")):
        if row.get(field) not in {None, ""} and not _bool(row.get(field)):
            reasons.append(label)
    if str(row.get("prediction_consistency", "")).upper() not in {"", "PASS", "TRUE"}:
        reasons.append("prediction_consistency_fail")
    raw_accuracy = _raw_accuracy(row)
    if raw_accuracy is not None and raw_accuracy < 1.0:
        reasons.append("raw_numeric_prediction_failure")
    if row.get("model_numeric_valid") not in {None, ""} and not _bool(row.get("model_numeric_valid")):
        reasons.append("raw_numeric_gate_failed")
    if not _bool(row.get("fully_scientifically_valid")):
        reasons.append("strict_scientific_gate_failed")
    return ";".join(dict.fromkeys(reasons)) or "valid"


def _raw_accuracy(row: dict[str, Any]) -> float | None:
    count = _float(row.get("numeric_prediction_correct_count"))
    total = _float(row.get("numeric_prediction_total_count"))
    return count / total if count is not None and total and total > 0 else None


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "sd": None, "min": None, "max": None}
    return {"n": len(values), "mean": statistics.mean(values), "median": statistics.median(values), "sd": statistics.stdev(values) if len(values) > 1 else 0.0, "min": min(values), "max": max(values)}


def _ledger_completed(row: dict[str, Any]) -> bool:
    """Return completion from the real call ledger, not from result-row status.

    The runner's call ledger uses ``request_status`` while some older fixtures use
    ``status``.  A scientific result row must not be used for billing accounting:
    an upstream placeholder can exist without any provider attempt.
    """
    value = row.get("request_status", row.get("status", ""))
    return str(value).strip().lower() in {"completed", "success", "succeeded"}


def _number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in {None, "", "null", "None"}:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def provider_billing_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Report provider billing only when every unique attempt is covered."""
    known = [_number(row, "provider_billed_cost_usd") for row in rows]
    known = [value for value in known if value is not None]
    total = len(rows)
    complete = bool(total) and len(known) == total
    return {
        "provider_billed_cost_usd": sum(known) if complete else None,
        "provider_billed_cost_known_partial_usd": sum(known) if known else None,
        "provider_billing_coverage": (len(known) / total) if total else 0.0,
        "provider_billing_verified": complete,
    }


def _cluster_bootstrap(records: list[dict[str, Any]], *, seed: int = 20261113, draws: int = 2000) -> dict[str, Any]:
    clusters: dict[str, list[float]] = {}
    for row in records:
        value = _float(row.get("delta"))
        if value is not None and str(row.get("world_id", "")):
            clusters.setdefault(str(row["world_id"]), []).append(value)
    world_means = [statistics.mean(values) for values in clusters.values() if values]
    if not world_means:
        return {"world_clusters": 0, "bootstrap_draws": 0, "ci95": None, "ci_status": "NO_ELIGIBLE_WORLD_CLUSTERS"}
    if len(world_means) < 2:
        return {"world_clusters": len(world_means), "bootstrap_draws": 0, "ci95": None, "ci_status": "INSUFFICIENT_WORLD_CLUSTERS"}
    rng = random.Random(seed)
    draws_values = [statistics.mean(rng.choice(world_means) for _ in world_means) for _ in range(draws)]
    draws_values.sort()
    return {"world_clusters": len(world_means), "bootstrap_draws": draws, "ci95": [draws_values[int(0.025 * (draws - 1))], draws_values[int(0.975 * (draws - 1))]], "ci_status": "BOOTSTRAP_95_PERCENT_CLUSTER_DESCRIPTIVE"}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_baseline_comparison(root: Path, config: Any, destination: Path, raw_records: list[dict[str, Any]]) -> None:
    """Write auditable baselines plus every real-agent condition slot.

    Selection for non-Oracle methods is performed from public information. The
    private truth is used only by the existing scoring helper after selection.
    """
    pre_registered_path = destination / "pre_registered_baselines.csv"
    oracle_path = destination / "oracle_action_information_gain.csv"
    write_baselines_by_world(root, config, pre_registered_path, random_seed=config.plan_seed)
    write_oracle_audit(root, config, oracle_path)
    baseline_rows = _read_csv(pre_registered_path)
    oracle_rows = _read_csv(oracle_path)
    oracle_by_action = {(row["world_id"], row["experiment_id"]): row for row in oracle_rows}
    ig_star_by_world: dict[str, float] = {}
    for row in oracle_rows:
        value = _float(row.get("ig_nats"))
        if value is not None:
            ig_star_by_world[row["world_id"]] = max(ig_star_by_world.get(row["world_id"], value), value)
    random_distribution: list[dict[str, Any]] = []
    output_rows: list[dict[str, Any]] = []
    for world_index, world_id in enumerate(config.allowed_worlds):
        world_baselines = [row for row in baseline_rows if row.get("world_id") == world_id]
        random_baseline = next((row for row in world_baselines if row.get("baseline") == "RANDOM"), None)
        menu = [str(row["experiment_id"]) for row in _read_csv(destination / "_menu_placeholder.csv")]
        if not menu:
            public_view = load_world(root, world_id, "related", worlds_subdir=config.worlds_subdir)
            menu = [str(item["experiment_id"]) for item in public_view.experiments]
        score_by_action = {
            key[1]: _float(value.get("top1_score")) or 0.0
            for key, value in oracle_by_action.items()
            if key[0] == world_id
        }
        random_rng = random.Random(int(config.plan_seed) + world_index * 1009)
        samples: list[float] = []
        for sample_index in range(1000):
            action = random_rng.choice(menu)
            score = score_by_action.get(action, 0.0)
            samples.append(score)
            random_distribution.append({"world_id": world_id, "sample_index": sample_index, "seed": int(config.plan_seed) + world_index * 1009, "selected_experiment_id": action, "action_score": score, "source": "public_menu_uniform_random"})
        random_mean = statistics.mean(samples) if samples else None
        random_sd = statistics.stdev(samples) if len(samples) > 1 else 0.0
        observed_replicates = sorted({int(row.get("replicate")) for row in raw_records if str(row.get("world_id")) == world_id and str(row.get("replicate", "")).isdigit()})
        for replicate in (observed_replicates or list(range(int(config.repeats)))):
            for row in world_baselines:
                selected = row.get("chosen_experiment_id", "")
                oracle = oracle_by_action.get((world_id, selected), {})
                output_rows.append({
                    "world_id": world_id,
                    "replicate": replicate,
                    "method": row.get("baseline", ""),
                    "selected_experiment_id": selected,
                    "oracle_ig_nats": _float(oracle.get("ig_nats")),
                    "ig_star_nats": ig_star_by_world.get(world_id),
                    "action_score": _float(row.get("action_score")),
                    "seed": row.get("seed", ""),
                    "source": "offline_pre_registered_baseline",
                    "policy_version": "v5p11",
                    "status": "AVAILABLE",
                    "random_sample_count": 1000 if row.get("baseline") == "RANDOM" else "",
                    "random_sample_mean": random_mean if row.get("baseline") == "RANDOM" else "",
                    "random_sample_sd": random_sd if row.get("baseline") == "RANDOM" else "",
                })
    for row in raw_records:
        selected = str(row.get("experiment_id_selected", "")) if _executed(row) else ""
        oracle = oracle_by_action.get((str(row.get("world_id")), selected), {})
        output_rows.append({
            "world_id": row.get("world_id", ""),
            "replicate": row.get("replicate", ""),
            "method": f"REAL_AGENT_{row.get('condition', '')}",
            "selected_experiment_id": selected,
            "oracle_ig_nats": _float(oracle.get("ig_nats")) if selected else None,
            "ig_star_nats": ig_star_by_world.get(str(row.get("world_id"))),
            "action_score": _float(row.get("top1_action_score")) if _executed(row) else None,
            "seed": "",
            "source": "real_provider_results",
            "policy_version": "v5p11",
            "status": "EXECUTED" if _executed(row) else "NOT_EXECUTED",
            "random_sample_count": "",
            "random_sample_mean": "",
            "random_sample_sd": "",
        })
    fields = ["world_id", "replicate", "method", "selected_experiment_id", "oracle_ig_nats", "ig_star_nats", "action_score", "seed", "source", "policy_version", "status", "random_sample_count", "random_sample_mean", "random_sample_sd"]
    _write_csv(destination / "baseline_comparison.csv", output_rows, fields)
    _write_csv(destination / "random_baseline_distribution.csv", random_distribution, ["world_id", "sample_index", "seed", "selected_experiment_id", "action_score", "source"])
    (destination / "BASELINE_IMPLEMENTATION.md").write_text("""# V5-P11/V5-P12 baseline implementation\n\nOracle is an offline private-truth upper reference and never enters a provider prompt. Fixed E04 is selected by ID. RANDOM samples 1,000 uniform menu actions per world with deterministic seeds derived from the frozen plan seed; its distribution is retained in `random_baseline_distribution.csv`. PUBLIC_HEURISTIC and TARGET_ONLY_HEURISTIC select the maximum candidate prediction spread using public observations, public nominal rate, candidate models, and the legal menu only. Real-agent rows are copied from the result slots without replacing missing outputs. All rows use the same world menu and score implementation.\n""", encoding="utf-8")


def analyze_v5p11_run(project_root: str | Path, config_path: str | Path, run_dir: str | Path | None, output_dir: str | Path, *, real_status: str = "NOT_RUN", current_stage_prefixes: tuple[str, ...] | None = None, planned_condition_rows: int = 32) -> dict[str, Path]:
    root = Path(project_root).resolve()
    config = load_config(config_path)
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    source_rows: list[dict[str, Any]] = []
    if run_dir is not None and (Path(run_dir) / "results.csv").exists():
        with (Path(run_dir) / "results.csv").open(newline="", encoding="utf-8") as handle:
            source_rows = list(csv.DictReader(handle))
    raw_records: list[dict[str, Any]] = []
    numeric_records: list[dict[str, Any]] = []
    for row in source_rows:
        record = dict(row)
        record["raw_agent_numeric_accuracy"] = _raw_accuracy(row)
        record["strict_scientific_valid"] = _bool(row.get("fully_scientifically_valid")) if _executed(row) else False
        record["executed_scientific_output"] = _executed(row)
        assisted = {"accuracy": None, "correct_count": None, "total_count": None, "calculator_values": {}}
        if _executed(row):
            try:
                view = load_world(root, str(row["world_id"]), "related", worlds_subdir=config.worlds_subdir)
                split = split_numeric_ability(view, str(row["experiment_id_selected"]), _json(row.get("predicted_values")))
                assisted = split["assisted_calculator"]
            except (OSError, ValueError, KeyError):
                assisted = {"accuracy": None, "correct_count": None, "total_count": None, "calculator_values": {}}
        record["raw_model_prediction_accuracy"] = record["raw_agent_numeric_accuracy"]
        record["public_formula_recomputed_values"] = json.dumps(assisted.get("calculator_values", {}), ensure_ascii=False, sort_keys=True)
        record["calculator_recomputation_success"] = bool(assisted.get("calculator_recomputation_success", False))
        record["calculator_assisted_diagnostic_score"] = assisted.get("calculator_assisted_diagnostic_score", assisted.get("accuracy"))
        record["assisted_calculator_accuracy"] = assisted.get("accuracy")
        record["assisted_calculator_correct_count"] = assisted.get("correct_count")
        record["assisted_calculator_total_count"] = assisted.get("total_count")
        record["assisted_calculator_values"] = json.dumps(assisted.get("calculator_values", {}), ensure_ascii=False, sort_keys=True)
        record["scientific_diagnostic_reason"] = _scientific_diagnostic_reason(record)
        raw_records.append(record)
        for model in config.candidate_models:
            errors = _json(row.get("prediction_errors"))
            numeric_records.append({"world_id": row.get("world_id"), "replicate": row.get("replicate"), "condition": row.get("condition"), "model": model, "raw_error": errors.get(model), "raw_pass": _float(errors.get(model)) is not None and _float(errors.get(model)) <= 0.02, "assisted_pass": bool(_executed(row)), "status": "EXECUTED" if _executed(row) else "NOT_EXECUTED"})

    diagnostic_rows = [{
        "world_id": row.get("world_id"),
        "replicate": row.get("replicate"),
        "condition": row.get("condition"),
        "run_status": row.get("run_status", ""),
        "executed_scientific_output": row.get("executed_scientific_output", False),
        "raw_model_prediction_accuracy": row.get("raw_model_prediction_accuracy"),
        "assisted_calculator_accuracy": row.get("assisted_calculator_accuracy"),
        "calculator_recomputation_success": row.get("calculator_recomputation_success", False),
        "calculator_assisted_diagnostic_score": row.get("calculator_assisted_diagnostic_score"),
        "strict_scientific_valid": row.get("strict_scientific_valid", False),
        "scientific_diagnostic_reason": row.get("scientific_diagnostic_reason", ""),
    } for row in raw_records]

    _write_csv(destination / "results_raw.csv", raw_records, fields=list(raw_records[0]) if raw_records else ["status", "world_id", "replicate", "condition"])
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in raw_records:
        grouped.setdefault((str(row.get("world_id")), str(row.get("replicate"))), {})[str(row.get("condition"))] = row
    delta_files: dict[str, list[dict[str, Any]]] = {"action": [], "strict_raw": [], "assisted_diagnostic": [], "strict_assisted": []}
    route_rows: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    for (world_id, replicate), values in sorted(grouped.items()):
        c, d = values.get("C_SEQ2_TRANSFER"), values.get("D_SEQ2_BLOCK")
        if c or d:
            route_rows.append({"world_id": world_id, "replicate": replicate, "c_stage1_artifact_sha256": (c or {}).get("stage1_artifact_sha256", ""), "d_stage1_artifact_sha256": (d or {}).get("stage1_artifact_sha256", ""), "same_stage1_artifact": bool(_executed(c or {}) and _executed(d or {}) and c.get("stage1_artifact_sha256") and c.get("stage1_artifact_sha256") == d.get("stage1_artifact_sha256")), "c_forwarded_artifact_sha256": (c or {}).get("forwarded_artifact_sha256", ""), "d_forwarded_artifact_sha256": (d or {}).get("forwarded_artifact_sha256", ""), "d_route_intervention": (d or {}).get("route_intervention", ""), "status": "EXECUTED" if _executed(c or {}) and _executed(d or {}) else "NOT_EXECUTED"})
        for contrast, left_name, right_name in CONTRASTS:
            left, right = values.get(left_name), values.get(right_name)
            action = _float(left.get("top1_action_score")) - _float(right.get("top1_action_score")) if left and right and _executed(left) and _executed(right) and _float(left.get("top1_action_score")) is not None and _float(right.get("top1_action_score")) is not None else None
            raw_result = calculate_strict_raw_delta(left or {}, right or {})
            assisted_result = calculate_assisted_diagnostic_delta(left or {}, right or {})
            assisted_scientific_result = calculate_assisted_scientific_delta(left or {}, right or {})
            common = {"world_id": world_id, "replicate": replicate, "contrast": contrast, "delta": action, "status": "ELIGIBLE" if action is not None else "UNDEFINED", "exclusion_reason": "" if action is not None else "missing_or_unexecuted_condition"}
            delta_files["action"].append(dict(common))
            common_raw = {**common, **raw_result}
            common_assisted_diagnostic = {**common, **assisted_result}
            common_assisted = {**common, **assisted_scientific_result}
            delta_files["strict_raw"].append(common_raw)
            delta_files["assisted_diagnostic"].append(common_assisted_diagnostic)
            delta_files["strict_assisted"].append(common_assisted)
        for condition, row in values.items():
            stage_rows.append({"world_id": world_id, "replicate": replicate, "condition": condition, "stage1_judgment": row.get("shared_law_judgment", ""), "candidate_law_id": row.get("candidate_law_id", ""), "stage1_relation_correct": row.get("stage1_relation_correct", ""), "stage1_law_identification_correct": row.get("stage1_law_identification_correct", ""), "stage1_mapping_correct": row.get("stage1_mapping_correct", ""), "stage1_abstention_appropriate": row.get("stage1_abstention_appropriate", ""), "stage1_valid": row.get("stage1_valid", ""), "stage1_artifact_sha256": row.get("stage1_artifact_sha256", ""), "status": "EXECUTED" if _executed(row) else "NOT_EXECUTED"})
    _write_csv(destination / "paired_deltas_action.csv", delta_files["action"], ["world_id", "replicate", "contrast", "delta", "status", "exclusion_reason"])
    delta_fields = ["world_id", "replicate", "contrast", "delta", "status", "metric_mode", "exclusion_reason"]
    _write_csv(destination / "paired_deltas_strict_raw.csv", delta_files["strict_raw"], delta_fields)
    _write_csv(destination / "paired_deltas_assisted_diagnostic.csv", delta_files["assisted_diagnostic"], delta_fields)
    _write_csv(destination / "paired_deltas_strict_assisted.csv", delta_files["strict_assisted"], delta_fields)
    _write_csv(destination / "stage1_relation_and_mapping.csv", stage_rows, ["world_id", "replicate", "condition", "stage1_judgment", "candidate_law_id", "stage1_relation_correct", "stage1_law_identification_correct", "stage1_mapping_correct", "stage1_abstention_appropriate", "stage1_valid", "stage1_artifact_sha256", "status"])
    _write_csv(destination / "stage1_router_proofs.csv", route_rows)
    _write_csv(destination / "numeric_error_by_model.csv", numeric_records, ["world_id", "replicate", "condition", "model", "raw_error", "raw_pass", "assisted_pass", "status"])
    _write_csv(destination / "scientific_diagnostics.csv", diagnostic_rows, ["world_id", "replicate", "condition", "run_status", "executed_scientific_output", "raw_model_prediction_accuracy", "assisted_calculator_accuracy", "calculator_recomputation_success", "calculator_assisted_diagnostic_score", "strict_scientific_valid", "scientific_diagnostic_reason"])
    ledger_rows: list[dict[str, Any]] = []
    if run_dir is not None and (Path(run_dir) / "call_ledger.jsonl").exists():
        for line in (Path(run_dir) / "call_ledger.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                ledger_rows.append(json.loads(line))
    unique_ledger: dict[str, dict[str, Any]] = {}
    for row in ledger_rows:
        request_id = str(row.get("request_id", ""))
        if request_id:
            unique_ledger.setdefault(request_id, row)
    unique_rows = list(unique_ledger.values())
    completed_ledger = [row for row in unique_rows if _ledger_completed(row)]
    failed_ledger = [row for row in unique_rows if not _ledger_completed(row)]
    reserved_estimate = sum(_number(row, "reserved_estimated_cost_usd") or 0.0 for row in unique_rows)
    completed_usage = sum(_number(row, "local_response_estimate_usd") or 0.0 for row in completed_ledger)
    failed_reserved = sum(_number(row, "reserved_estimated_cost_usd") or 0.0 for row in failed_ledger)
    failed_attempt_estimate = sum(_number(row, "estimated_cost_usd") or 0.0 for row in failed_ledger)
    all_attempt_estimate = sum(_number(row, "estimated_cost_usd") or 0.0 for row in unique_rows)
    billing = provider_billing_summary(unique_rows)
    cost_accounting = {
        "version": "separated_v3",
        "unique_attempts": len(unique_rows),
        "unique_completed": len(completed_ledger),
        "unique_failed_or_unresolved": len(failed_ledger),
        "automatic_retries": len(ledger_rows) - len(unique_rows),
        "reserved_estimate_usd": reserved_estimate,
        "completed_response_usage_local_estimate_usd": completed_usage,
        "failed_reserved_estimate_usd": failed_reserved,
        "failed_attempt_estimate_upper_bound_usd": failed_attempt_estimate,
        "all_attempts_estimate_usd": all_attempt_estimate,
        **billing,
        "accounting_note": "Reserved estimates, completed response usage estimates, failed-attempt estimates, and provider billing are separate quantities; none are added together as actual spend.",
    }
    stats: dict[str, Any] = {}
    for name, records in delta_files.items():
        grouped_values: dict[str, list[float]] = {}
        for row in records:
            value = _float(row.get("delta"))
            if value is not None:
                grouped_values.setdefault(str(row.get("contrast")), []).append(value)
        stats[name] = {contrast: {**_summary(values), **_cluster_bootstrap([row for row in records if row.get("contrast") == contrast])} for contrast, values in grouped_values.items()}
    action_scores = [_float(row.get("top1_action_score")) for row in raw_records if _executed(row) and _float(row.get("top1_action_score")) is not None]
    ig_scores = [_float(row.get("ig_selected_action") or row.get("ig_selected")) for row in raw_records if _executed(row) and _float(row.get("ig_selected_action") or row.get("ig_selected")) is not None]
    raw_acc = [_raw_accuracy(row) for row in raw_records if _executed(row) and _raw_accuracy(row) is not None]
    assisted_acc = [_float(row.get("assisted_calculator_accuracy")) for row in raw_records if _executed(row) and _float(row.get("assisted_calculator_accuracy")) is not None]
    strict = [1.0 if _bool(row.get("fully_scientifically_valid")) else 0.0 for row in raw_records if _executed(row)]
    diagnostic_counts: dict[str, int] = {}
    for row in diagnostic_rows:
        reason = str(row["scientific_diagnostic_reason"] or "")
        diagnostic_counts[reason] = diagnostic_counts.get(reason, 0) + 1
    stage1_rows = [row for row in raw_records if str(row.get("condition")) == "C_SEQ2_TRANSFER" and _executed(row)]
    stage1_summary = {
        "executed_stage1_condition_rows": len(stage1_rows),
        "relation_correct_count": sum(_bool(row.get("stage1_relation_correct")) for row in stage1_rows),
        "law_identification_correct_count": sum(_bool(row.get("stage1_law_identification_correct")) for row in stage1_rows),
        "mapping_correct_count": sum(_bool(row.get("stage1_mapping_correct")) for row in stage1_rows),
        "abstention_appropriate_count": sum(_bool(row.get("stage1_abstention_appropriate")) for row in stage1_rows),
    }
    current_stage_rows = [row for row in unique_rows if current_stage_prefixes and any(str(row.get("request_id", "")).startswith(prefix) for prefix in current_stage_prefixes)]
    current_stage_completed = [row for row in current_stage_rows if _ledger_completed(row)]
    overall = {"protocol": "v5p11", "real_status": real_status, "result_rows": len(raw_records), "completed_scientific_rows": sum(_executed(row) for row in raw_records), "planned_condition_rows": planned_condition_rows, "cumulative_unique_attempts": len(unique_rows), "cumulative_completed_responses": len(completed_ledger), "cumulative_failed_or_unresolved": len(failed_ledger), "current_stage_unique_attempts": len(current_stage_rows) if current_stage_prefixes else len(unique_rows), "current_stage_completed_responses": len(current_stage_completed) if current_stage_prefixes else len(completed_ledger), "new_real_api_calls": len(current_stage_rows) if current_stage_prefixes else len(unique_rows), "completed_real_api_calls": len(completed_ledger), "failed_or_unresolved_real_api_calls": len(failed_ledger), "information_gain_selected_nats": _summary([v for v in ig_scores if v is not None]), "action_score": _summary([v for v in action_scores if v is not None]), "raw_agent_numeric_accuracy": _summary([v for v in raw_acc if v is not None]), "assisted_calculator_accuracy": _summary([v for v in assisted_acc if v is not None]), "strict_scientific_valid_rate": _summary(strict), "scientific_diagnostic_counts": diagnostic_counts, "stage1_summary": stage1_summary, "paired_deltas": stats, "cost_accounting": cost_accounting, "strict_zero_vs_undefined_policy": "zero is retained only for an eligible pair; missing or invalid pair is UNDEFINED", "world_cluster_inference": "descriptive only; four worlds are clusters and repeats are nested", "provider_billing": "VERIFIED only when every unique provider attempt has a provider-billed amount; otherwise NULL/UNVERIFIED"}
    (destination / "overall_summary.json").write_text(json.dumps(overall, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (destination / "cost_accounting.json").write_text(json.dumps(cost_accounting, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_baseline_comparison(root, config, destination, raw_records)
    _write_csv(destination / "cost_provider_ledger.csv", ledger_rows or [{"status": "NOT_RUN", "reserved_estimate_usd": None, "usage_estimate_usd": None, "provider_billed_cost_usd": None, "billing_status": "UNVERIFIED"}])
    by_world: list[dict[str, Any]] = []
    for world_id in config.allowed_worlds:
        rows = [row for row in raw_records if str(row.get("world_id")) == world_id]
        by_world.append({"world_id": world_id, "rows": len(rows), "executed_rows": sum(_executed(row) for row in rows), "action_score_mean": _summary([_float(row.get("top1_action_score")) for row in rows if _executed(row) and _float(row.get("top1_action_score")) is not None])["mean"], "strict_raw_valid_rows": sum(_bool(row.get("fully_scientifically_valid")) for row in rows if _executed(row))})
    _write_csv(destination / "by_world_summary.csv", by_world, ["world_id", "rows", "executed_rows", "action_score_mean", "strict_raw_valid_rows"])
    return {"results_raw": destination / "results_raw.csv", "overall_summary": destination / "overall_summary.json"}


def write_not_run_analysis(project_root: str | Path, config_path: str | Path, output_dir: str | Path) -> dict[str, Path]:
    return analyze_v5p11_run(project_root, config_path, None, output_dir, real_status="NOT_RUN")
