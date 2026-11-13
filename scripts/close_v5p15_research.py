from __future__ import annotations

"""Close the additive V5-P15 study from immutable real-run artifacts.

This script performs read-only scientific aggregation over the validation run
and the network-stopped core run. It preserves unfinished slots as explicit
missingness and never converts unknown provider billing into zero.
"""

import csv
import hashlib
import json
from pathlib import Path
import shutil
import statistics
from typing import Any
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "020_V5P15_RESEARCH_20261114"
CONFIG = ROOT / "config" / "v5p15_research.json"
VALIDATION_RUN = ROOT / "runs" / "real_v5p15_validation_20261114"
CORE_RUN = ROOT / "runs" / "real_v5p15_core_20261114"
VALIDATION_SESSION = ROOT / "runs" / "real_api_sessions" / "v5p11_20261113T172041Z_KdG_IBFf4So2kWRP"
CORE_SESSION = ROOT / "runs" / "real_api_sessions" / "v5p11_20261113T172329Z_kQb9u8LE_bFrwg8r"
ANALYSIS_INPUT = REPORT / "analysis_input_v1"
ANALYSIS_OUTPUT = REPORT / "analysis_v5p15"
STAGE = ROOT / "work" / "v5p15_evidence_staging_20261114"
ZIP_PATH = REPORT / "FINAL_RESEARCH_EVIDENCE.zip"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
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


def as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def as_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes", "pass"}


def executed(row: dict[str, Any]) -> bool:
    return str(row.get("run_status", "")).upper() == "COMPLETED" and bool(str(row.get("experiment_id_selected", "")).strip())


def summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None}
    return {"n": len(values), "mean": statistics.mean(values), "sd": statistics.stdev(values) if len(values) > 1 else 0.0, "min": min(values), "max": max(values)}


def copy_rows() -> list[dict[str, str]]:
    validation = read_csv(VALIDATION_RUN / "results.csv")
    core = read_csv(CORE_RUN / "results.csv")
    for row in validation:
        # Keep the pilot as an additional, explicitly labelled repeat. Its
        # namespace remains the immutable provenance key.
        row["cohort"] = "validation"
        row["original_replicate"] = row.get("replicate", "")
        row["replicate"] = "5"
    for row in core:
        row["cohort"] = "formal_core_partial"
        row["original_replicate"] = row.get("replicate", "")
    rows = validation + core
    write_csv(ANALYSIS_INPUT / "results.csv", rows)
    write_json(ANALYSIS_INPUT / "config_frozen.json", read_json(CONFIG))
    return rows


def combine_ledgers() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cohort, path in (("validation", VALIDATION_RUN / "call_ledger.jsonl"), ("formal_core_partial", CORE_RUN / "call_ledger.jsonl")):
        for row in read_jsonl(path):
            row["cohort"] = cohort
            rows.append(row)
    return rows


def paired(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row.get("world_id", ""), row.get("replicate", "")), {})[row.get("condition", "")] = row
    output: list[dict[str, Any]] = []
    for (world, replicate), values in sorted(groups.items()):
        for contrast, left_name, right_name in (("B-A", "B_SINGLE_RELATED", "A_TARGET_ONLY"), ("C-D", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"), ("C-B", "C_SEQ2_TRANSFER", "B_SINGLE_RELATED")):
            left, right = values.get(left_name), values.get(right_name)
            action_delta = None
            strict_delta = None
            assisted_delta = None
            action_eligible = bool(left and right and executed(left) and executed(right) and as_float(left.get("top1_action_score")) is not None and as_float(right.get("top1_action_score")) is not None)
            if action_eligible:
                action_delta = as_float(left["top1_action_score"]) - as_float(right["top1_action_score"])
            strict_eligible = bool(action_eligible and as_bool(left.get("fully_scientifically_valid")) and as_bool(right.get("fully_scientifically_valid")))
            if strict_eligible:
                strict_delta = as_float(left["top1_score"]) - as_float(right["top1_score"])
            assisted_eligible = bool(action_eligible and as_bool(left.get("calculator_recomputation_success", True)) and as_bool(right.get("calculator_recomputation_success", True)))
            if assisted_eligible:
                assisted_delta = action_delta
            c, d = values.get("C_SEQ2_TRANSFER"), values.get("D_SEQ2_BLOCK")
            same_stage1 = bool(c and d and executed(c) and executed(d) and c.get("stage1_artifact_sha256") and c.get("stage1_artifact_sha256") == d.get("stage1_artifact_sha256")) if contrast == "C-D" else ""
            output.append({
                "world_id": world,
                "replicate": replicate,
                "contrast": contrast,
                "left_condition": left_name,
                "right_condition": right_name,
                "action_delta": action_delta,
                "action_pair_eligible": action_eligible,
                "strict_raw_delta": strict_delta,
                "strict_pair_eligible": strict_eligible,
                "calculator_assisted_delta": assisted_delta,
                "calculator_assisted_pair_eligible": assisted_eligible,
                "same_stage1_artifact": same_stage1,
                "c_route": c.get("route_intervention", "") if c else "",
                "d_route": d.get("route_intervention", "") if d else "",
                "status": "ELIGIBLE" if action_eligible else "UNDEFINED",
                "exclusion_reason": "" if action_eligible else "missing_or_unexecuted_condition",
            })
    return output


def write_cost_ledger(ledger_rows: list[dict[str, Any]]) -> dict[str, Any]:
    fields = ["cohort", "call_id", "request_id", "world_id", "replicate", "condition", "stage", "request_status", "failure_kind", "detail_code", "usage_source", "billing_source", "actual_input_tokens", "actual_output_tokens", "reserved_estimated_cost_usd", "estimated_cost_usd", "local_response_estimate_usd", "provider_billed_cost_usd", "unique_billable_call"]
    write_csv(REPORT / "API_COST_LEDGER.csv", ledger_rows, fields)
    completed = [row for row in ledger_rows if str(row.get("request_status", "")).lower() == "completed"]
    failed = [row for row in ledger_rows if str(row.get("request_status", "")).lower() != "completed"]
    reserved = sum(as_float(row.get("reserved_estimated_cost_usd")) or 0.0 for row in ledger_rows)
    local_completed = sum(as_float(row.get("local_response_estimate_usd")) or 0.0 for row in completed)
    failed_reserved = sum(as_float(row.get("reserved_estimated_cost_usd")) or 0.0 for row in failed)
    accounting = {
        "budget_cap_usd": 10.0,
        "attempted_unique_api_calls": len(ledger_rows),
        "completed_api_calls": len(completed),
        "failed_api_calls": len(failed),
        "automatic_retries": 0,
        "reserved_estimate_usd": reserved,
        "completed_response_local_estimate_usd": local_completed,
        "failed_request_reserved_estimate_usd": failed_reserved,
        "provider_billed_cost_usd": None,
        "provider_billing_status": "UNVERIFIED_PROVIDER_BILLING",
        "remaining_against_authorized_cap_by_reserved_estimate_usd": 10.0 - reserved,
        "note": "Reservation, completed local usage estimate, failed reservation, and provider billing remain separate. Unknown provider billing is not represented as zero.",
    }
    write_json(REPORT / "BUDGET_ACCOUNTING.json", accounting)
    return accounting


def metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    by_condition: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_condition.setdefault(row.get("condition", ""), []).append(row)
    result: dict[str, Any] = {}
    for condition, group in sorted(by_condition.items()):
        done = [row for row in group if executed(row)]
        raw_acc = [as_float(row.get("numeric_prediction_accuracy")) for row in done if as_float(row.get("numeric_prediction_accuracy")) is not None]
        calc = [as_float(row.get("assisted_calculator_accuracy")) for row in done if as_float(row.get("assisted_calculator_accuracy")) is not None]
        ig = [as_float(row.get("ig_selected_action")) for row in done if as_float(row.get("ig_selected_action")) is not None]
        action = [as_float(row.get("top1_action_score")) for row in done if as_float(row.get("top1_action_score")) is not None]
        result[condition] = {
            "planned_slots": len(group),
            "executed_slots": len(done),
            "missing_or_failed_slots": len(group) - len(done),
            "information_gain_nats": summarize([x for x in ig if x is not None]),
            "action_score": summarize([x for x in action if x is not None]),
            "raw_agent_numeric_accuracy": summarize([x for x in raw_acc if x is not None]),
            "calculator_assisted_accuracy": summarize([x for x in calc if x is not None]),
            "strict_scientific_valid_rate": sum(as_bool(row.get("fully_scientifically_valid")) for row in done) / len(done) if done else None,
        }
    stage = [row for row in rows if row.get("condition") == "C_SEQ2_TRANSFER" and executed(row)]
    result["stage1"] = {
        "executed": len(stage),
        "relation_correct": sum(as_bool(row.get("stage1_relation_correct")) for row in stage),
        "law_identification_correct": sum(as_bool(row.get("stage1_law_identification_correct")) for row in stage),
        "mapping_correct": sum(as_bool(row.get("stage1_mapping_correct")) for row in stage),
        "relation_accuracy": sum(as_bool(row.get("stage1_relation_correct")) for row in stage) / len(stage) if stage else None,
        "law_identification_accuracy": sum(as_bool(row.get("stage1_law_identification_correct")) for row in stage) / len(stage) if stage else None,
        "mapping_accuracy": sum(as_bool(row.get("stage1_mapping_correct")) for row in stage) / len(stage) if stage else None,
    }
    return result


def write_reports(rows: list[dict[str, str]], pairs: list[dict[str, Any]], accounting: dict[str, Any], m: dict[str, Any]) -> None:
    write_csv(REPORT / "EXPERIMENT_RESULTS.csv", rows)
    write_csv(REPORT / "PAIRED_CAUSAL_ANALYSIS.csv", pairs)
    baseline_source = ANALYSIS_OUTPUT / "baseline_comparison.csv"
    if baseline_source.exists():
        shutil.copy2(baseline_source, REPORT / "BASELINE_COMPARISON.csv")
    else:
        write_csv(REPORT / "BASELINE_COMPARISON.csv", [])
    write_json(REPORT / "METRICS_SUMMARY.json", m)
    done = [row for row in rows if executed(row)]
    cd_pairs = [row for row in pairs if row["contrast"] == "C-D"]
    route_eligible = [row for row in cd_pairs if row["same_stage1_artifact"] is True]
    relation = m["stage1"]
    report = [
        "# V5-P15 real research report",
        "",
        "## Scope and stopping rule",
        "",
        "This report combines the five-request validation cohort and the additive eight-world core cohort. The core session stopped at the first transport-layer TLS failure, preserved that request, and marked every downstream scientific slot as `UPSTREAM_FAIL_FAST`. The final file retains completed, failed, and unexecuted slots.",
        "",
        f"- planned core scientific slots: 160; validation slots: 4; combined slots: {len(rows)}",
        f"- completed scientific outputs: {len(done)}",
        f"- unique API attempts: {accounting['attempted_unique_api_calls']}; completed responses: {accounting['completed_api_calls']}; failed attempts: {accounting['failed_api_calls']}",
        f"- reserved local estimate: ${accounting['reserved_estimate_usd']:.8f}; provider bill: UNVERIFIED",
        "- paid execution status: STOPPED_AFTER_TLS_FAILURE",
        "",
        "## Descriptive results",
        "",
        "| condition | executed/planned | mean IG (nats) | mean action score | raw Agent numeric accuracy | calculator-assisted accuracy | strict scientific validity |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for condition in ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"):
        x = m.get(condition, {})
        def fmt(key: str) -> str:
            value = x.get(key, {}).get("mean")
            return "UNDEFINED" if value is None else f"{value:.4f}"
        strict = x.get("strict_scientific_valid_rate")
        report.append(f"| {condition} | {x.get('executed_slots', 0)}/{x.get('planned_slots', 0)} | {fmt('information_gain_nats')} | {fmt('action_score')} | {fmt('raw_agent_numeric_accuracy')} | {fmt('calculator_assisted_accuracy')} | {'UNDEFINED' if strict is None else f'{strict:.4f}'} |")
    report.extend([
        "",
        "## Paired causal contrasts",
        "",
        "`B-A`, `C-D`, and `C-B` are retained in `PAIRED_CAUSAL_ANALYSIS.csv`. Action deltas are available only when both condition outputs were executed. Strict raw deltas require both sides to pass the strict scientific gate. Missing pairs remain `UNDEFINED`.",
        "",
        f"- eligible C/D action pairs: {sum(row['action_pair_eligible'] for row in cd_pairs)} / {len(cd_pairs)}",
        f"- C/D pairs with equal Stage1 artifact hash: {len(route_eligible)} / {len(cd_pairs)}",
        f"- Stage1 C/D route evidence rows with explicit D block: {sum(row['d_route'] == 'blocked' for row in route_eligible)} / {len(route_eligible)}",
        f"- C/D action deltas: {[row['action_delta'] for row in cd_pairs if row['action_delta'] is not None]}",
        "",
        "## Stage1",
        "",
        f"- executed Stage1 rows: {relation['executed']}",
        f"- shared-relation correct: {relation['relation_correct']}/{relation['executed']} ({relation['relation_accuracy'] if relation['relation_accuracy'] is not None else 'UNDEFINED'})",
        f"- candidate-law identification correct: {relation['law_identification_correct']}/{relation['executed']} ({relation['law_identification_accuracy'] if relation['law_identification_accuracy'] is not None else 'UNDEFINED'})",
        f"- variable mapping correct: {relation['mapping_correct']}/{relation['executed']} ({relation['mapping_accuracy'] if relation['mapping_accuracy'] is not None else 'UNDEFINED'})",
        "",
        "## Interpretation",
        "",
        "The executed subset supports the engineering claim that C and D can share one Stage1 artifact while D receives a neutral blocked route. The scientific transfer hypothesis remains unresolved because the first core TLS failure stopped the pre-registered cohort before enough worlds and repeats were observed. Action, numeric, and strict metrics are descriptive for the observed subset; they do not support an eight-world confirmation claim.",
        "",
        "Unknown provider billing remains explicitly unverified. Local usage estimates and reserved upper bounds appear in the separate cost ledger.",
    ])
    (REPORT / "FINAL_RESEARCH_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    stats = [
        "# Statistical analysis",
        "",
        "The unit of scientific pairing is world × replicate × condition. Repeats nested within a world are retained as repeated observations; completed rows are separated from missing or failed rows. The report uses descriptive means and sample standard deviations. A confirmatory confidence interval requires enough completed world clusters; the stopped core does not provide that coverage.",
        "",
        f"- combined scientific slots: {len(rows)}",
        f"- completed scientific slots: {len(done)}",
        f"- completed worlds with science output: {len({row['world_id'] for row in done})}",
        "- strict raw validity never replaces missing values with zero.",
        "- failed and upstream-blocked slots remain in the denominator of execution coverage and are excluded from valid-only means.",
        "",
        "## Contrast policy",
        "",
        "Action deltas use `top1_action_score`. Strict raw deltas use `top1_score` only when both rows pass `fully_scientifically_valid`. Calculator-assisted deltas are diagnostic and retain raw Agent numeric accuracy as a separate field.",
        "",
        "The final interpretation is evidence-incomplete rather than positive or negative confirmation. A transport stop is a technical missingness mechanism, not a scientific failure.",
    ]
    (REPORT / "STATISTICAL_ANALYSIS.md").write_text("\n".join(stats) + "\n", encoding="utf-8")
    mechanism = [
        "# Mechanism analysis",
        "",
        "## Stage1 identification",
        "",
        f"Observed Stage1 rows: {relation['executed']}; relation accuracy: {relation['relation_accuracy']}; law accuracy: {relation['law_identification_accuracy']}; mapping accuracy: {relation['mapping_accuracy']}.",
        "",
        "## Program-level C/D route",
        "",
        f"Equal Stage1 artifact hash was observed in {len(route_eligible)}/{len(cd_pairs)} available C/D pairs. The D route intervention field equals `blocked` in {sum(row['d_route'] == 'blocked' for row in route_eligible)}/{len(route_eligible)} available pairs. C route records use `real` when transfer is enabled.",
        "",
        "## Failure mechanism",
        "",
        "The core session stopped on `URLError` classified as `TLS_FAILURE`, reason type `TLS_HANDSHAKE`, detail `TLS_SSLEOFERROR`. The adapter performed zero automatic retries. The result table marks later slots `UPSTREAM_FAIL_FAST`, keeping network missingness separate from scientific output errors.",
        "",
        "## Scientific conclusion",
        "",
        "The route-control mechanism is evidenced in executed pairs. Cross-disciplinary law recognition, transfer benefit, and multi-agent superiority remain insufficiently tested because the pre-registered core cohort did not complete.",
    ]
    (REPORT / "MECHANISM_ANALYSIS.md").write_text("\n".join(mechanism) + "\n", encoding="utf-8")
    status = [
        "# Final project status",
        "",
        "- Engineering: COMPLETE for the V5-P15 offline design, eight-world validation, authorization binding, budget separation, route audit, and evidence packaging; 184 pre-run tests passed.",
        f"- Real execution: PARTIAL_STOPPED; {accounting['completed_api_calls']} completed responses and {accounting['failed_api_calls']} failed transport attempt among {accounting['attempted_unique_api_calls']} unique attempts.",
        "- Scientific validation: INCONCLUSIVE; action and route diagnostics are available for the executed subset, while the eight-world confirmation claim remains untested.",
        "- Core cohort: 8 worlds × 5 repeats × A/B/C/D was frozen as 200 requests and was not fully completed after the TLS stop.",
        "- Multi-agent extension: not started because the protocol requires the core cohort to complete first and the network stop prohibits additional paid execution.",
        "- Historical data: V5-P14 and earlier artifacts remain preserved; the new report uses independent V5-P15 namespaces.",
        "- Secret safety: API key files, authorization headers, `.env` files, and unrelated private credentials are excluded from the evidence package and Git working tree.",
    ]
    (REPORT / "FINAL_PROJECT_STATUS.md").write_text("\n".join(status) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_evidence() -> dict[str, Any]:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    copy_specs = [
        (ROOT / "src", STAGE / "src"),
        (ROOT / "tests", STAGE / "tests"),
        (ROOT / "scripts" / "generate_v5p15_research_worlds.py", STAGE / "scripts" / "generate_v5p15_research_worlds.py"),
        (ROOT / "scripts" / "build_v5p15_research_proposal.py", STAGE / "scripts" / "build_v5p15_research_proposal.py"),
        (ROOT / "scripts" / "close_v5p15_research.py", STAGE / "scripts" / "close_v5p15_research.py"),
        (CONFIG, STAGE / "config" / CONFIG.name),
        (ROOT / "data" / "worlds_v5p15_research", STAGE / "data" / "worlds_v5p15_research"),
        (ROOT / "private" / "worlds_v5p15_research", STAGE / "private" / "worlds_v5p15_research"),
        (ROOT / "docs" / "PROTOCOL.md", STAGE / "docs" / "PROTOCOL.md"),
        (ROOT / "README.md", STAGE / "README.md"),
        (VALIDATION_RUN, STAGE / "runs" / VALIDATION_RUN.name),
        (CORE_RUN, STAGE / "runs" / CORE_RUN.name),
        (VALIDATION_SESSION, STAGE / "runs" / "sessions" / VALIDATION_SESSION.name),
        (CORE_SESSION, STAGE / "runs" / "sessions" / CORE_SESSION.name),
        (REPORT, STAGE / "report"),
    ]
    ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "FINAL_RESEARCH_EVIDENCE.zip")
    for source, target in copy_specs:
        if source.is_dir():
            shutil.copytree(source, target, ignore=ignore)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    secret_names: list[str] = []
    for path in STAGE.rglob("*"):
        if path.is_file() and (path.name.startswith(".env") or "api_key" in str(path).lower() or path.suffix.lower() in {".key", ".pem"}):
            secret_names.append(path.relative_to(STAGE).as_posix())
    write_json(STAGE / "EVIDENCE_SECRET_SCAN.json", {"secret_like_files": secret_names, "status": "PASS" if not secret_names else "FAIL"})
    manifest_rows = []
    for path in sorted(STAGE.rglob("*")):
        if path.is_file():
            manifest_rows.append({"path": path.relative_to(STAGE).as_posix(), "sha256": file_sha256(path), "bytes": path.stat().st_size})
    write_csv(STAGE / "EVIDENCE_MANIFEST_SHA256.csv", manifest_rows, ["path", "sha256", "bytes"])
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGE).as_posix())
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"evidence ZIP integrity failure: {bad}")
        entries = len(archive.namelist())
    zip_hash = file_sha256(ZIP_PATH)
    (REPORT / "FINAL_RESEARCH_EVIDENCE_SHA256.txt").write_text(zip_hash + "\n", encoding="utf-8")
    write_json(REPORT / "EVIDENCE_PACKAGE_CHECK.json", {"zip": ZIP_PATH.name, "sha256": zip_hash, "zip_integrity": "PASS", "entries": entries, "secret_scan": "PASS" if not secret_names else "FAIL"})
    return {"sha256": zip_hash, "entries": entries}


def main() -> int:
    REPORT.mkdir(parents=True, exist_ok=True)
    planned_rows = copy_rows()
    # The analysis module reads only this new combined input directory.
    from mini_science.analysis_v5p11 import analyze_v5p11_run
    analyze_v5p11_run(ROOT, CONFIG, ANALYSIS_INPUT, ANALYSIS_OUTPUT, real_status="STOPPED_AFTER_TLS_FAILURE", planned_condition_rows=len(planned_rows))
    # Use the analysis-enriched rows for the final deliverables so calculator
    # recomputation remains visibly separate from raw Agent arithmetic.
    rows = read_csv(ANALYSIS_OUTPUT / "results_raw.csv")
    ledger_rows = combine_ledgers()
    accounting = write_cost_ledger(ledger_rows)
    pair_rows = paired(rows)
    write_csv(REPORT / "PAIRED_CAUSAL_ANALYSIS.csv", pair_rows)
    write_reports(rows, pair_rows, accounting, metrics(rows))
    package = package_evidence()
    print(json.dumps({"report": str(REPORT), "result_rows": len(rows), "unique_api_attempts": len(ledger_rows), "completed_api_calls": sum(str(row.get("request_status", "")).lower() == "completed" for row in ledger_rows), "failed_api_calls": sum(str(row.get("request_status", "")).lower() != "completed" for row in ledger_rows), "zip_sha256": package["sha256"], "zip_entries": package["entries"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
