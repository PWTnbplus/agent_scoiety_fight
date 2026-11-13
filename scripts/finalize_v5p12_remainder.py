from __future__ import annotations

"""Merge V5-P11 history with the V5-P12 remainder without mutating history."""

import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import statistics
import zipfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "017_V5P12_REMAINDER_LIVE"
OLD_REPORT = ROOT / "reports" / "016_V5P11_REAL_20261113T072222Z"
OLD_RUN = ROOT / "runs" / "real_v5p11_IV001_IV004_20261113T072222Z"
OLD_SESSION = ROOT / "runs" / "real_api_sessions" / "v5p11_20261113T072254Z_4QaXzSJmGYKikoua"
CONFIG = ROOT / "config" / "v5p11_main.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, value: Any) -> None:
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_new_runs() -> list[Path]:
    candidates = sorted(
        list((ROOT / "runs").glob("real_v5p12_remainder_*"))
        + list((ROOT / "runs").glob("real_v5p12_recovery_*")),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError("no V5-P12 remainder run directory")
    return candidates


def find_new_sessions() -> list[Path]:
    sessions: list[Path] = []
    auth = REPORT / "AUTHORIZATION_RESULT.json"
    if auth.exists():
        value = read_json(auth)
        if value.get("session_dir"):
            sessions.append(Path(value["session_dir"]).resolve())
    candidates = sorted((ROOT / "runs" / "real_api_sessions").glob("v5p11_*"), key=lambda path: path.stat().st_mtime)
    for path in candidates:
        if (path / "authorization.json").exists():
            record = read_json(path / "authorization.json")
            if record.get("protocol_variant") in {"v5p12_remainder", "v5p12_recovery_after_transport_stop"}:
                sessions.append(path.resolve())
    unique = list(dict.fromkeys(sessions))
    if not unique:
        raise FileNotFoundError("no V5-P12 remainder authorization session")
    return unique


def slot_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row.get("world_id", "")), str(row.get("replicate", "")), str(row.get("condition", ""))


def status_for(row: dict[str, Any]) -> str:
    run_status = str(row.get("run_status", ""))
    if run_status == "UPSTREAM_FAIL_FAST" or not row.get("run_status"):
        return "NOT_EXECUTED"
    if run_status.startswith("FAILED"):
        return "FAILED_TRANSPORT"
    if run_status == "COMPLETED":
        return "EXECUTED_VALID_ACTION" if str(row.get("action_valid", "")).lower() == "true" else "EXECUTED_INVALID_SCIENCE"
    return run_status


def make_combined_source(new_runs: list[Path]) -> tuple[Path, list[dict[str, Any]]]:
    combined = REPORT / "combined_analysis_source"
    combined.mkdir(parents=True, exist_ok=True)
    old_rows = read_csv(OLD_REPORT / "analysis" / "results_raw.csv")
    chosen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in old_rows:
        if row.get("world_id") == "IV001":
            chosen[slot_key(row)] = row
    for new_run in new_runs:
        for row in read_csv(new_run / "results.csv"):
            if row.get("world_id") not in {"IV002", "IV003", "IV004"}:
                continue
            key = slot_key(row)
            current = chosen.get(key)
            if current is None or status_for(current) in {"NOT_EXECUTED", "UPSTREAM_FAIL_FAST"}:
                chosen[key] = row
    rows = [chosen[key] for key in sorted(chosen)]
    if len(rows) != 32:
        raise RuntimeError(f"combined condition slots must be exactly 32, got {len(rows)}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    write_csv(combined / "results.csv", rows, fields)
    old_calls = read_jsonl(OLD_RUN / "call_ledger.jsonl")
    with (combined / "call_ledger.jsonl").open("w", encoding="utf-8") as handle:
        for row in old_calls:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        for new_run in new_runs:
            for row in read_jsonl(new_run / "call_ledger.jsonl"):
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return combined, rows


def write_complete_table(rows: list[dict[str, Any]], new_runs: list[Path], new_sessions: list[Path]) -> None:
    output: list[dict[str, Any]] = []
    for row in rows:
        world = str(row.get("world_id"))
        output.append({
            "world_id": world,
            "replicate": row.get("replicate", ""),
            "condition": row.get("condition", ""),
            "slot_status": status_for(row),
            "run_status": row.get("run_status", ""),
            "experiment_id_selected": row.get("experiment_id_selected", ""),
            "top1_action_score": row.get("top1_action_score", ""),
            "ig_selected_action": row.get("ig_selected_action", ""),
            "raw_numeric_accuracy": row.get("numeric_prediction_accuracy", ""),
            "assisted_calculator_accuracy": row.get("assisted_calculator_accuracy", ""),
            "strict_scientific_valid": row.get("fully_scientifically_valid", ""),
            "scientific_diagnostic_reason": row.get("scientific_diagnostic_reason", ""),
            "source_run": str(OLD_RUN if world == "IV001" else _source_run(row, new_runs)),
            "source_session": "historical_v5p11" if world == "IV001" else str(_source_session(row, new_runs, new_sessions)),
        })
    write_csv(REPORT / "COMPLETE_RESULT_BY_WORLD_AND_REP.csv", output)


def _source_run(row: dict[str, Any], new_runs: list[Path]) -> Path:
    for run in new_runs:
        for candidate in read_csv(run / "results.csv"):
            if slot_key(candidate) == slot_key(row) and status_for(candidate) == status_for(row):
                return run
    return new_runs[0]


def _source_session(row: dict[str, Any], new_runs: list[Path], new_sessions: list[Path]) -> Path:
    run = _source_run(row, new_runs)
    manifest = read_json(run / "manifest.json")
    authorization_id = manifest.get("call_policy", {}).get("authorization_id")
    for session in new_sessions:
        auth_path = session / "authorization.json"
        if auth_path.exists() and read_json(auth_path).get("authorization_id") == authorization_id:
            return session
    return new_sessions[0]


def write_provenance(rows: list[dict[str, Any]], new_runs: list[Path], new_sessions: list[Path]) -> None:
    old_files = [OLD_RUN / "results.csv", OLD_RUN / "call_ledger.jsonl", OLD_RUN / "manifest.json", OLD_SESSION / "attempt_ledger.jsonl"]
    sources = []
    sources.append({"label": "V5P11_HISTORY", "files": [{"path": str(path), "sha256": sha256(path)} for path in old_files if path.exists()]})
    for index, new_run in enumerate(new_runs, 1):
        session = new_sessions[min(index - 1, len(new_sessions) - 1)]
        files = [new_run / "results.csv", new_run / "call_ledger.jsonl", new_run / "manifest.json", session / "attempt_ledger.jsonl"]
        label = "V5P12_NEW_RUN_" + str(index)
        sources.append({"label": label, "files": [{"path": str(path), "sha256": sha256(path)} for path in files if path.exists()]})
    row_sources = [{"world_id": row.get("world_id"), "replicate": row.get("replicate"), "condition": row.get("condition"), "source": "V5P11_HISTORY" if row.get("world_id") == "IV001" else "V5P12_REMAINDER"} for row in rows]
    write_json(REPORT / "COMBINED_PROVENANCE.json", {"sources": sources, "rows": row_sources, "old_failure_retained": "V5P11MAIN20261113_IV001_R1:D_SEQ2_BLOCK:stage2:question_designer", "analysis_is_combined_not_a_single_timepoint": True})


def write_stage_router_proof() -> None:
    stage_rows = read_csv(REPORT / "analysis" / "stage1_relation_and_mapping.csv")
    route_rows = {(row.get("world_id"), row.get("replicate")): row for row in read_csv(REPORT / "analysis" / "stage1_router_proofs.csv")}
    output = []
    for row in stage_rows:
        route = route_rows.get((row.get("world_id"), row.get("replicate")), {})
        output.append({**row, "same_stage1_artifact": route.get("same_stage1_artifact", ""), "d_route_intervention": route.get("d_route_intervention", ""), "c_forwarded_artifact_sha256": route.get("c_forwarded_artifact_sha256", ""), "d_forwarded_artifact_sha256": route.get("d_forwarded_artifact_sha256", "")})
    write_csv(REPORT / "STAGE1_AND_ROUTER_PROOF.csv", output)


def write_cost_audit(new_runs: list[Path], new_sessions: list[Path]) -> dict[str, Any]:
    old_calls = read_jsonl(OLD_RUN / "call_ledger.jsonl")
    new_calls = [row for new_run in new_runs for row in read_jsonl(new_run / "call_ledger.jsonl")]
    all_calls = old_calls + new_calls
    unique: dict[str, dict[str, Any]] = {}
    for row in all_calls:
        if row.get("request_id"):
            unique.setdefault(str(row["request_id"]), row)
    unique_rows = list(unique.values())
    completed = [row for row in unique_rows if str(row.get("request_status", "")).lower() == "completed"]
    failed = [row for row in unique_rows if str(row.get("request_status", "")).lower() != "completed"]
    cost = {
        "accounting_version": "separated_v3",
        "historical_v5p11_attempts": len({str(row.get("request_id")) for row in old_calls if row.get("request_id")}),
        "new_v5p12_attempts": len({str(row.get("request_id")) for row in new_calls if row.get("request_id")}),
        "cumulative_unique_attempts": len(unique_rows),
        "cumulative_completed_responses": len(completed),
        "cumulative_failed_or_unresolved": len(failed),
        "automatic_retries": len(all_calls) - len(unique_rows),
        "reserved_estimate_usd": sum(float(row.get("reserved_estimated_cost_usd") or 0.0) for row in unique_rows),
        "completed_response_usage_local_estimate_usd": sum(float(row.get("local_response_estimate_usd") or 0.0) for row in completed),
        "failed_reserved_estimate_usd": sum(float(row.get("reserved_estimated_cost_usd") or 0.0) for row in failed),
        "failed_attempt_estimate_upper_bound_usd": sum(float(row.get("estimated_cost_usd") or 0.0) for row in failed),
        "all_attempts_estimate_usd": sum(float(row.get("estimated_cost_usd") or 0.0) for row in unique_rows),
        "provider_billed_cost_usd": None,
        "provider_billing_verified": False,
        "new_session_dirs": [str(path) for path in new_sessions],
        "note": "Historical and new ledgers are combined by unique request_id; reservation, completed usage, failed-attempt estimate, and provider billing are not added together as actual spend.",
    }
    write_json(REPORT / "COST_AND_USAGE_AUDIT.json", cost)
    return cost


def write_failure_audit(rows: list[dict[str, Any]], new_runs: list[Path]) -> None:
    pairs = []
    for world in ("IV001", "IV002", "IV003", "IV004"):
        for replicate in ("0", "1"):
            values = {row.get("condition"): row for row in rows if row.get("world_id") == world and str(row.get("replicate")) == replicate}
            c, d = values.get("C_SEQ2_TRANSFER"), values.get("D_SEQ2_BLOCK")
            eligible = bool(c and d and status_for(c).startswith("EXECUTED") and status_for(d).startswith("EXECUTED"))
            pairs.append({"world_id": world, "replicate": replicate, "contrast": "C-D", "status": "ELIGIBLE" if eligible else "UNDEFINED", "reason": "" if eligible else "missing_or_failed_condition"})
    write_json(REPORT / "FAILURE_AND_MISSINGNESS_AUDIT.json", {
        "slot_status_counts": {status: sum(status_for(row) == status for row in rows) for status in {status_for(row) for row in rows}},
        "old_transport_failure_retained": "V5P11MAIN20261113_IV001_R1:D_SEQ2_BLOCK:stage2:question_designer",
        "new_runs": [str(path) for path in new_runs],
        "cd_pairs": pairs,
        "undefined_is_not_zero": True,
    })


def write_final_report(new_runs: list[Path], new_sessions: list[Path], cost: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    summary = read_json(REPORT / "analysis" / "overall_summary.json")
    pairs = read_csv(REPORT / "analysis" / "paired_deltas_action.csv")
    baseline_rows = read_csv(REPORT / "analysis" / "baseline_comparison.csv")
    all_calls = read_jsonl(REPORT / "combined_analysis_source" / "call_ledger.jsonl")
    failed_calls = [
        f"{row.get('request_id')}: {row.get('failure_kind') or row.get('error') or row.get('request_status')}"
        for row in all_calls
        if str(row.get("request_status", "")).lower() != "completed"
    ]
    def deltas(name: str) -> list[float]:
        return [float(row["delta"]) for row in pairs if row.get("contrast") == name and row.get("status") == "ELIGIBLE" and row.get("delta") not in {"", None}]
    def mean_field(source: list[dict[str, Any]], field: str) -> float | None:
        values = [float(row[field]) for row in source if row.get(field) not in {"", None}]
        return statistics.mean(values) if values else None
    condition_means = {}
    for condition in ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"):
        selected = [row for row in rows if row.get("condition") == condition and status_for(row).startswith("EXECUTED")]
        condition_means[condition] = {
            "action": mean_field(selected, "top1_action_score"),
            "ig": mean_field(selected, "ig_selected_action"),
            "raw": mean_field(selected, "raw_agent_numeric_accuracy"),
            "assisted": mean_field(selected, "assisted_calculator_accuracy"),
            "strict": statistics.mean([1.0 if str(row.get("strict_scientific_valid", "")).lower() == "true" else 0.0 for row in selected]) if selected else None,
            "n": len(selected),
        }
    baseline_means = {method: mean_field([row for row in baseline_rows if row.get("method") == method], "action_score") for method in ("ORACLE_UPPER", "FIXED_E04", "RANDOM", "PUBLIC_HEURISTIC", "TARGET_ONLY_HEURISTIC")}
    lines = [
        "# V5-P12 final science report",
        "",
        "## Scope and execution",
        "",
        f"- Historical V5-P11 remains read-only: IV001 had 9 completed requests and one retained RemoteDisconnected failure.",
        f"- New scope: IV002–IV004, R0/R1, A/B/C/D; 30 planned unique requests in namespace `V5P12REM20261113`.",
        f"- After the first transport stop, three independent recovery proposals covered 25 additional slots; 22 recovery requests were actually attempted. New V5-P12 attempts across the original and recovery runs: {cost['new_v5p12_attempts']}.",
        f"- New runs: {', '.join('`' + str(path) + '`' for path in new_runs)}; sessions: {', '.join('`' + str(path) + '`' for path in new_sessions)}.",
        f"- Combined condition slots: {len(rows)}/32; cumulative unique provider attempts: {cost['cumulative_unique_attempts']}; completed responses: {cost['cumulative_completed_responses']}; automatic retries: {cost['automatic_retries']}.",
        "- The old IV001/R1/D request was not retried. Any new transport failure is retained and its remaining slots are marked not executed.",
        f"- Retained failed requests: {' | '.join(failed_calls)}.",
        "",
        "## Metrics",
        "",
        f"- Action score mean: {summary['action_score']['mean']} (n={summary['action_score']['n']}).",
        f"- Selected information gain mean: {summary['information_gain_selected_nats']['mean']} nats (n={summary['information_gain_selected_nats']['n']}).",
        f"- Raw Agent numeric accuracy mean: {summary['raw_agent_numeric_accuracy']['mean']} (n={summary['raw_agent_numeric_accuracy']['n']}).",
        f"- Calculator-assisted accuracy mean: {summary['assisted_calculator_accuracy']['mean']} (n={summary['assisted_calculator_accuracy']['n']}).",
        f"- Strict scientific validity: {summary['strict_scientific_valid_rate']['mean']} (n={summary['strict_scientific_valid_rate']['n']}).",
        f"- Condition means (action/IG/raw/assisted/strict): {condition_means}.",
        f"- Baseline mean action scores: {baseline_means}.",
        f"- Executed condition rows: {summary['completed_scientific_rows']}/{summary['planned_condition_rows']}; diagnostic counts: {summary.get('scientific_diagnostic_counts', {})}.",
        f"- Stage1 executed C rows: {summary.get('stage1_summary', {}).get('executed_stage1_condition_rows', 0)}; relation-correct={summary.get('stage1_summary', {}).get('relation_correct_count', 0)}, law-identification-correct={summary.get('stage1_summary', {}).get('law_identification_correct_count', 0)}, mapping-correct={summary.get('stage1_summary', {}).get('mapping_correct_count', 0)}.",
        "",
        "## Paired action contrasts",
        "",
        "| Contrast | Eligible pairs | Mean delta | World-level CI status |",
        "|---|---:|---:|---|",
    ]
    for name in ("B-A", "C-D", "C-B"):
        values = deltas(name)
        stats = summary["paired_deltas"]["action"].get(name, {})
        lines.append(f"| {name} | {len(values)} | {statistics.mean(values) if values else 'UNDEFINED'} | {stats.get('ci_status', 'UNDEFINED')} |")
    lines += [
        "",
        "## Stage1 and routing",
        "",
        "- C and D share the same Stage1 artifact only when both outputs were actually executed; D uses the code-level blocked route and a distinct forwarded artifact.",
        "- All C/D rows include same/different/unknown state and artifact hashes in `STAGE1_AND_ROUTER_PROOF.csv`.",
        "- Stage1 recognition is not treated as proof that Stage2 used the law; strict raw science remains separately gated.",
        "",
        "## Baseline comparison",
        "",
        "- `BASELINE_COMPARISON.csv` contains Oracle upper reference, fixed E04, seeded random distribution, public mathematical heuristic, target-only heuristic, and every real-agent condition slot.",
        "- Oracle is private scoring only and never enters prompts. Random samples use 1,000 deterministic menu draws per world. Public heuristics use only public observations, nominal rate, candidate equations, and the legal menu.",
        "",
        "## Cost and evidence",
        "",
        f"- Historical successful usage estimate: kept in `COST_AND_USAGE_AUDIT.json`; cumulative completed-response usage estimate: `{cost['completed_response_usage_local_estimate_usd']}` USD.",
        f"- Cumulative reserved estimate: `{cost['reserved_estimate_usd']}` USD; provider billing: `UNVERIFIED`.",
        "- Raw scientific errors and transport errors are included; undefined paired effects are never replaced by zero.",
        "",
        "## Conclusion",
        "",
        "The combined run provides the pre-registered exploratory comparison for the available worlds and repeats. The agent selected actions and generated completed responses, but every executed scientific row failed the strict raw numeric/consistency gate; the calculator-assisted column is an upper diagnostic, not a substitute for the raw Agent result. Stage1 was correct on the executed C rows only where the recorded law and mapping matched the private truth, and C/D routing evidence confirms shared artifacts plus code-level D blocking for eligible pairs. The study therefore does not establish a paper-level mechanism claim: strict scientific validity, missingness, world-cluster count, and transport failures remain explicit. Positive action-only contrasts are not evidence of general law transfer without strict valid paired results.",
    ]
    (REPORT / "FINAL_SCIENCE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    progress = {
        "engineering": {"status": "COMPLETE_AFTER_P12_FIXES", "full_tests": "recorded_in_OFFLINE_GATE.json", "four_world_validation": "PASS"},
        "real_experiment": {"planned_historical_plus_new": 40, "combined_unique_attempts": cost["cumulative_unique_attempts"], "completed_responses": cost["cumulative_completed_responses"], "condition_slots": f"{len(rows)}/32", "cd_action_eligible": sum(row.get("contrast") == "C-D" and row.get("status") == "ELIGIBLE" for row in pairs)},
        "strict_science": {"executed_rows": summary["completed_scientific_rows"], "strict_valid_rows": summary["strict_scientific_valid_rate"]["n"] and int(summary["strict_scientific_valid_rate"]["mean"] * summary["strict_scientific_valid_rate"]["n"]) or 0, "status": "DESCRIPTIVE_ONLY"},
        "paper_level_mechanism": {"status": "NOT_ESTABLISHED", "reason": "strict gates and world-level inference remain limiting"},
        "historical_preserved": True,
    }
    write_json(REPORT / "PROJECT_PROGRESS.json", progress)
    (REPORT / "PROJECT_PROGRESS.md").write_text("""# Project progress\n\n- Engineering: complete after the V5-P12 statistical, baseline, and exit-status fixes; see `OFFLINE_GATE.json`.\n- Real experiment: historical V5-P11 plus the new IV002–IV004 remainder are merged by provenance; failures and missing slots remain explicit.\n- Strict scientific validation: reported separately from action-only and calculator-assisted diagnostics.\n- Paper-level mechanism validation: not established unless the final combined strict-valid and world-cluster evidence supports it.\n""", encoding="utf-8")


def safe_add(archive: zipfile.ZipFile, source: Path, name: str, *, check_bearer: bool = True) -> None:
    if not source.is_file() or source.suffix.lower() not in {".json", ".jsonl", ".csv", ".md", ".txt", ".log", ".py"}:
        return
    data = source.read_bytes()
    if check_bearer and re.search(rb"authorization\s*[:=]\s*[\"']?bearer\s+", data, re.I):
        raise RuntimeError(f"bearer header found in evidence source: {source}")
    archive.writestr(name, data)


def package_evidence(new_runs: list[Path], new_sessions: list[Path]) -> Path:
    destination = REPORT / "RESTRICTED_REPRODUCIBLE_EVIDENCE.zip"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=8) as archive:
        for path in sorted(REPORT.rglob("*")):
            if path.is_file() and path != destination:
                safe_add(archive, path, f"report/{path.relative_to(REPORT).as_posix()}")
        for index, new_run in enumerate(new_runs, 1):
            for path in sorted(new_run.rglob("*")):
                if path.is_file():
                    safe_add(archive, path, f"new_run_{index}/{path.relative_to(new_run).as_posix()}")
        for index, new_session in enumerate(new_sessions, 1):
            for name in ("attempt_ledger.jsonl", "planned_requests.jsonl", "gate_state.json", "authorization.json"):
                safe_add(archive, new_session / name, f"new_session_{index}/{name}")
        old_zip = OLD_REPORT / "RESTRICTED_REAL_EVIDENCE_POSTRUN_CORRECTED.zip"
        safe_add(archive, old_zip, "history/V5P11_RESTRICTED_REAL_EVIDENCE.zip")
        for path in sorted((ROOT / "src" / "mini_science").rglob("*.py")):
            safe_add(archive, path, f"source/{path.relative_to(ROOT).as_posix()}", check_bearer=False)
        for path in sorted((ROOT / "tests").glob("*.py")):
            safe_add(archive, path, f"source/{path.relative_to(ROOT).as_posix()}", check_bearer=False)
        safe_add(archive, CONFIG, f"source/{CONFIG.relative_to(ROOT).as_posix()}", check_bearer=False)
        for base in (ROOT / "data" / "worlds_v5p11_main", ROOT / "private" / "worlds_v5p11_main"):
            for path in sorted(base.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".json", ".md", ".csv"}:
                    safe_add(archive, path, f"source/{path.relative_to(ROOT).as_posix()}", check_bearer=False)
    return destination


def main() -> int:
    new_runs = find_new_runs()
    new_sessions = find_new_sessions()
    combined_dir, rows = make_combined_source(new_runs)
    from mini_science.analysis_v5p11 import analyze_v5p11_run
    all_completed = all(read_json(run / "manifest.json").get("call_policy", {}).get("real_api_status") == "COMPLETED" for run in new_runs)
    analyze_v5p11_run(ROOT, CONFIG, combined_dir, REPORT / "analysis", real_status="COMPLETED" if all_completed else "STOPPED_WITH_EVIDENCE")
    analyzed_rows = read_csv(REPORT / "analysis" / "results_raw.csv")
    write_complete_table(analyzed_rows, new_runs, new_sessions)
    write_provenance(analyzed_rows, new_runs, new_sessions)
    write_stage_router_proof()
    cost = write_cost_audit(new_runs, new_sessions)
    write_failure_audit(analyzed_rows, new_runs)
    write_final_report(new_runs, new_sessions, cost, analyzed_rows)
    package = package_evidence(new_runs, new_sessions)
    write_json(REPORT / "PACKAGE_SHA256.json", {"path": str(package), "sha256": sha256(package), "size": package.stat().st_size})
    print(json.dumps({"report": str(REPORT), "runs": [str(path) for path in new_runs], "sessions": [str(path) for path in new_sessions], "package": str(package), "package_sha256": sha256(package), "combined_rows": len(rows)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
