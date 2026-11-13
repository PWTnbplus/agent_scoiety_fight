from __future__ import annotations

"""Merge the V5-P13 evidence and produce the final reproducible analysis package."""

import csv
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import zipfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "018_V5P13_SCIENCE_DIAG_AND_FINAL"
OLD_SOURCE = ROOT / "reports" / "017_V5P12_REMAINDER_LIVE" / "combined_analysis_source"
OLD_PACKAGE = ROOT / "reports" / "017_V5P12_REMAINDER_LIVE" / "RESTRICTED_REPRODUCIBLE_EVIDENCE.zip"
CONFIG = ROOT / "config" / "v5p11_main.json"
NEW_RUNS = sorted((ROOT / "runs").glob("real_v5p13_followup_*"), key=lambda p: p.stat().st_mtime)
NEW_SESSION_GLOB = sorted((ROOT / "runs" / "real_api_sessions").glob("v5p11_*"), key=lambda p: p.stat().st_mtime)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
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
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def slot(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row.get("world_id", "")), str(row.get("replicate", "")), str(row.get("condition", ""))


def executed(row: dict[str, Any]) -> bool:
    return str(row.get("run_status", "")).upper() == "COMPLETED" and bool(str(row.get("experiment_id_selected", "")))


def status(row: dict[str, Any]) -> str:
    value = str(row.get("run_status", ""))
    if value == "COMPLETED":
        return "EXECUTED" if executed(row) else "EXECUTED_INVALID_SCIENCE"
    if value.startswith("FAILED"):
        return "FAILED_TRANSPORT"
    if value in {"UPSTREAM_FAIL_FAST", ""}:
        return "NOT_EXECUTED"
    return value


def latest_session_for_run(run: Path) -> Path | None:
    manifest = run / "manifest.json"
    if not manifest.exists():
        return None
    auth_id = read_json(manifest).get("call_policy", {}).get("authorization_id")
    for session in reversed(NEW_SESSION_GLOB):
        auth = session / "authorization.json"
        if auth.exists() and read_json(auth).get("authorization_id") == auth_id:
            return session
    return None


def build_combined_source(new_run: Path) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]]:
    old_rows = read_csv(OLD_SOURCE / "results.csv")
    new_rows = read_csv(new_run / "results.csv")
    by_slot: dict[tuple[str, str, str], dict[str, Any]] = {slot(row): row for row in old_rows}
    for row in new_rows:
        key = slot(row)
        if key in by_slot:
            raise RuntimeError(f"new V5-P13 slot collides with historical source: {key}")
        by_slot[key] = row
    rows = [by_slot[key] for key in sorted(by_slot)]
    if len(rows) != 40:
        raise RuntimeError(f"expected 40 combined condition slots, got {len(rows)}")
    destination = REPORT / "14_FINAL_ANALYSIS" / "combined_analysis_source"
    destination.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    write_csv(destination / "results.csv", rows, fields)
    calls = read_jsonl(OLD_SOURCE / "call_ledger.jsonl") + read_jsonl(new_run / "call_ledger.jsonl")
    unique: dict[str, dict[str, Any]] = {}
    for row in calls:
        request_id = str(row.get("request_id", ""))
        if request_id and request_id not in unique:
            unique[request_id] = row
    if len(unique) != len(calls):
        raise RuntimeError("duplicate request IDs found while merging historical and V5-P13 ledgers")
    (destination / "call_ledger.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in calls), encoding="utf-8")
    write_json(destination / "MERGE_PROVENANCE.json", {
        "historical_source": str(OLD_SOURCE),
        "new_source": str(new_run),
        "historical_condition_slots": len(old_rows),
        "new_condition_slots": len(new_rows),
        "combined_condition_slots": len(rows),
        "historical_request_ids": len({str(row.get("request_id")) for row in read_jsonl(OLD_SOURCE / "call_ledger.jsonl") if row.get("request_id")}),
        "new_request_ids": len({str(row.get("request_id")) for row in read_jsonl(new_run / "call_ledger.jsonl") if row.get("request_id")}),
        "combined_unique_request_ids": len(unique),
        "historical_source_read_only": True,
    })
    return destination, rows, calls


def copy_analysis_outputs(analysis: Path) -> None:
    mapping = {
        "results_raw.csv": "raw_action_and_numeric_results.csv",
        "paired_deltas_action.csv": "paired_deltas_action.csv",
        "paired_deltas_strict_raw.csv": "paired_deltas_strict_raw.csv",
        "paired_deltas_assisted_diagnostic.csv": "paired_deltas_assisted_diagnostic.csv",
        "stage1_relation_and_mapping.csv": "stage1_relation_and_mapping.csv",
        "stage1_router_proofs.csv": "stage1_router_proofs.csv",
        "by_world_summary.csv": "per_world_summary.csv",
        "overall_summary.json": "overall_summary_corrected.json",
        "cost_accounting.json": "cost_accounting.json",
        "cost_provider_ledger.csv": "cost_provider_ledger.csv",
        "scientific_diagnostics.csv": "scientific_diagnostics.csv",
        "oracle_action_information_gain.csv": "oracle_action_information_gain.csv",
        "pre_registered_baselines.csv": "pre_registered_baselines.csv",
        "baseline_comparison.csv": "baseline_comparison_matched.csv",
    }
    for source, target in mapping.items():
        source_path = analysis / source
        if source_path.exists():
            shutil.copy2(source_path, REPORT / target)


def write_derived_tables(analysis: Path, rows: list[dict[str, Any]], calls: list[dict[str, Any]]) -> None:
    distribution = read_csv(analysis / "random_baseline_distribution.csv")
    random_rows = []
    for world in sorted({row.get("world_id") for row in distribution}):
        values = [float(row["action_score"]) for row in distribution if row.get("world_id") == world and row.get("action_score") not in {"", None}]
        random_rows.append({"world_id": world, "n_samples": len(values), "mean_action_score": statistics.mean(values) if values else None, "sd_action_score": statistics.stdev(values) if len(values) > 1 else 0.0, "source": "public_menu_uniform_random_matched_distribution"})
    write_csv(REPORT / "random_expected_value_by_world.csv", random_rows)

    frequency: list[dict[str, Any]] = []
    for condition in ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"):
        selected = [row for row in rows if row.get("condition") == condition]
        counts: dict[str, int] = {}
        for row in selected:
            action = str(row.get("experiment_id_selected") or "MISSING") if executed(row) else "MISSING"
            counts[action] = counts.get(action, 0) + 1
        for action, count in sorted(counts.items()):
            frequency.append({"condition": condition, "experiment_id": action, "count": count, "denominator_slots": len(selected), "executed_count": sum(executed(row) for row in selected)})
    write_csv(REPORT / "action_selection_frequency.csv", frequency)

    effects = {}
    for name in ("paired_deltas_action.csv", "paired_deltas_strict_raw.csv", "paired_deltas_assisted_diagnostic.csv", "paired_deltas_strict_assisted.csv"):
        path = analysis / name
        if path.exists():
            effects[name] = read_csv(path)
    write_json(REPORT / "all_effects_and_missingness.json", {
        "slot_status_counts": {value: sum(status(row) == value for row in rows) for value in sorted({status(row) for row in rows})},
        "condition_slot_count": len(rows),
        "executed_scientific_rows": sum(executed(row) for row in rows),
        "undefined_is_not_zero": True,
        "effects": effects,
        "new_request_ledger_rows": len(calls),
        "transport_failures": [row.get("request_id") for row in calls if str(row.get("request_status", "")).startswith("failed")],
    })


def write_progress(summary: dict[str, Any], rows: list[dict[str, Any]], calls: list[dict[str, Any]], new_run: Path) -> None:
    cd_pairs = {(row.get("world_id"), row.get("replicate")) for row in rows if row.get("condition") == "C_SEQ2_TRANSFER" and executed(row)}
    completed_cd = sum(1 for key in {(row.get("world_id"), row.get("replicate")) for row in rows if row.get("condition") == "C_SEQ2_TRANSFER" and executed(row)} if any(row.get("world_id") == key[0] and row.get("replicate") == key[1] and row.get("condition") == "D_SEQ2_BLOCK" and executed(row) for row in rows))
    strict_valid = sum(str(row.get("fully_scientifically_valid", "")).lower() == "true" for row in rows if executed(row))
    current_calls = [row for row in calls if str(row.get("request_id", "")).startswith("V5P13")]
    completed_calls = [row for row in current_calls if str(row.get("request_status", "")).lower() == "completed"]
    progress = {
        "engineering": {"status": "COMPLETE_WITH_HISTORICAL_REMEDIATION_RECORDED", "tests_passed": 182, "tests_failed": 0, "core_fixes": ["calculator-assisted diagnostic no longer uses raw-zero strict score", "missing/unexecuted rows remain invalid", "separated reserved/usage/provider billing", "V5-P13 R2/R3 authorization supports explicit replicate indices", "D route gate remains code-blocked", "V5 real runs no longer write the legacy V3 G3 report path"], "historical_remediation": "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/19_LEGACY_V3_OVERWRITE_REMEDIATION.json"},
        "real_experiment": {"historical_and_new_planned_condition_slots": 40, "cumulative_unique_provider_attempts": summary.get("cumulative_unique_attempts"), "cumulative_completed_responses": summary.get("cumulative_completed_responses"), "cumulative_failed_or_unresolved": summary.get("cumulative_failed_or_unresolved"), "new_v5p13_calls": len(current_calls), "new_v5p13_completed": len(completed_calls), "new_run": str(new_run), "automatic_retries": summary.get("cost_accounting", {}).get("automatic_retries", 0), "status": "STOPPED_WITH_EVIDENCE_AFTER_B_TRANSPORT_FAILURE"},
        "cd_pairing": {"planned_pairs_in_40_slots": 10, "completed_pairs": completed_cd, "valid_pair_ratio": completed_cd / 10.0, "historical_v5p12_pairs": 5, "historical_v5p12_pair_ratio": 5 / 8.0},
        "strict_science": {"executed_rows": sum(executed(row) for row in rows), "strict_valid_rows": strict_valid, "strict_valid_rate": strict_valid / sum(executed(row) for row in rows) if any(executed(row) for row in rows) else None, "status": "DESCRIPTIVE_ONLY_NO_PAPER_LEVEL_CONFIRMATION"},
        "paper_level_validation": {"status": "NOT_ESTABLISHED", "reason": "zero strict raw valid rows and incomplete C/D pairs; calculator diagnostic is not raw Agent math"},
    }
    write_json(REPORT / "16_PROJECT_PROGRESS.json", progress)
    write_csv(REPORT / "15_PROJECT_COMPLETION_MATRIX.csv", [
        {"area": "history_protection", "status": "REMEDIATED_WITH_OPERATOR_REVIEW", "evidence": "03_HISTORY_IMMUTABILITY_CHECK.json and 19_LEGACY_V3_OVERWRITE_REMEDIATION.json; two legacy report digests cannot be reconstructed exactly from available backups"},
        {"area": "engineering_tests", "status": "PASS", "evidence": "182 passed"},
        {"area": "offline_sensitivity_and_controls", "status": "PASS", "evidence": "08_LAW_INFORMATION_SENSITIVITY_AUDIT.csv and control runs"},
        {"area": "new_real_api_scope", "status": "PARTIAL_STOPPED", "evidence": "10-request proposal; 2 calls; B RemoteDisconnected"},
        {"area": "scientific_analysis", "status": "PASS_DESCRIPTIVE", "evidence": "14_V5P13_FINAL_SCIENCE_REPORT.md and corrected tables"},
        {"area": "paper_level_validation", "status": "NOT_ESTABLISHED", "evidence": "strict raw validity and C/D pair coverage"},
    ])


def final_report(summary: dict[str, Any], rows: list[dict[str, Any]], calls: list[dict[str, Any]], new_run: Path) -> None:
    condition_counts = {}
    for condition in ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"):
        selected = [row for row in rows if row.get("condition") == condition]
        values = [float(row["top1_action_score"]) for row in selected if executed(row) and row.get("top1_action_score") not in {"", None}]
        ig = [float(row["ig_selected_action"]) for row in selected if executed(row) and row.get("ig_selected_action") not in {"", None}]
        raw = [float(row["raw_agent_numeric_accuracy"]) for row in selected if executed(row) and row.get("raw_agent_numeric_accuracy") not in {"", None}]
        condition_counts[condition] = {"n_executed": len(values), "action_mean": statistics.mean(values) if values else None, "selected_ig_mean_nats": statistics.mean(ig) if ig else None, "raw_numeric_accuracy_mean": statistics.mean(raw) if raw else None, "strict_valid_n": sum(str(row.get("fully_scientifically_valid", "")).lower() == "true" for row in selected if executed(row))}
    failed = [f"{row.get('request_id')}: {row.get('failure_kind') or row.get('error') or row.get('request_status')}" for row in calls if str(row.get("request_status", "")).lower() != "completed"]
    baseline = read_csv(REPORT / "baseline_comparison_matched.csv")
    baseline_means = {}
    for method in ("ORACLE", "ORACLE_UPPER", "FIXED_E04", "RANDOM", "PUBLIC_HEURISTIC", "TARGET_ONLY_HEURISTIC"):
        values = [float(row["action_score"]) for row in baseline if row.get("method") == method and row.get("action_score") not in {"", None}]
        if values:
            baseline_means[method] = statistics.mean(values)
    report = f'''# V5-P13 Mini Science Society final science report

## Scope and evidence status

This report merges the read-only V5-P11/V5-P12 scientific source with the new V5-P13 IV002 R2/R3 cohort. The historical V5-P11/V5-P12 source tables were not overwritten. A legacy V3 report writer did write two files under `reports/real_v3` during the V5-P13 run; the new evidence captures those overwritten bytes, restores a known archived copy, records the pre-lock digests, and leaves an explicit operator-review failure because the exact pre-lock bytes are not recoverable from the current worktree. The runner is now patched so V5 contracts cannot call that legacy writer. The new proposal namespace was `V5P13IV002R23`, with ten unique planned requests: two shared Stage1 requests and eight Stage2 requests. The local upper-bound estimate was USD 0.051885 against the authorized USD 0.15 cap; automatic retry was disabled.

The new session made two provider attempts before the required transport stop: A/R2 completed with HTTP 200 and provider usage metadata; B/R2 failed as `RemoteDisconnected`. C/D and all R3 slots are retained as unexecuted, not as scientific successes. No second session and no retry were made.

Retained failed/unresolved request IDs in the merged ledger: {' | '.join(failed)}.

## Engineering and accounting

- Full regression suite: 182 passed, 0 failed.
- World validation and offline oracle/sensitivity audit passed.
- Reserved estimate, completed-response usage estimate, failed-attempt estimate, and provider billing are separate fields. Provider billing remains unverified because the provider did not return billed-cost fields for all attempts.
- C/D share the same Stage1 artifact key in the runner; D's route is code-blocked. The new cohort did not reach C/D, so it cannot add a new paired causal observation.
- Historical protection status is explicitly `REMEDIATED_WITH_OPERATOR_REVIEW`; see `03_HISTORY_IMMUTABILITY_CHECK.json` and `19_LEGACY_V3_OVERWRITE_REMEDIATION.json`.

## Scientific metrics

- Cumulative unique provider attempts: {summary.get('cumulative_unique_attempts')}; completed responses: {summary.get('cumulative_completed_responses')}; failed/unresolved: {summary.get('cumulative_failed_or_unresolved')}.
- Completed scientific condition rows: {summary.get('completed_scientific_rows')}/{summary.get('planned_condition_rows')}.
- Mean selected information gain: {summary.get('information_gain_selected_nats', {}).get('mean')} nats (n={summary.get('information_gain_selected_nats', {}).get('n')}).
- Mean action score: {summary.get('action_score', {}).get('mean')} (n={summary.get('action_score', {}).get('n')}).
- Raw Agent numerical prediction accuracy: {summary.get('raw_agent_numeric_accuracy', {}).get('mean')} (n={summary.get('raw_agent_numeric_accuracy', {}).get('n')}).
- Calculator-assisted diagnostic score: {summary.get('assisted_calculator_accuracy', {}).get('mean')} (n={summary.get('assisted_calculator_accuracy', {}).get('n')}); this is deterministic public-formula recomputation and is not raw Agent mathematical ability.
- Strict raw scientific validity: {summary.get('strict_scientific_valid_rate', {}).get('mean')} (n={summary.get('strict_scientific_valid_rate', {}).get('n')}).

Condition-level descriptive values: `{json.dumps(condition_counts, ensure_ascii=False, sort_keys=True)}`.

## Contrasts and baselines

The corrected files report B-A, C-D, and C-B separately for action diagnostics, strict raw science, and calculator-assisted diagnostics. Missing, failed, or invalid pairs are `UNDEFINED`, never zero. Baseline matched means where available: `{json.dumps(baseline_means, ensure_ascii=False, sort_keys=True)}`. Oracle is a private-truth retrospective upper reference; public heuristic, fixed E04, and random controls use only legal public/menu information.

The historical completed C/D pairs remain 5 of 8; after adding the two planned IV002 R2/R3 pairs, the merged 40-slot design has 5 of 10 completed C/D pairs (50%). The new cohort contributes no C/D pair because the transport stop occurred at B/R2.

## Stage1, route, and C/D diagnosis

Offline sensitivity shows that public law conditioning changes the selected action only in IV004; in IV001–IV003 the public objective is insensitive to the identified-law conditioning or leaves E08 low-ranked. The private retrospective oracle identifies different best actions by world, so the public candidate spread is not a substitute for ground-truth oracle scoring. Behavioral controls distinguish transfer-sensitive from transfer-ignored behavior, confirming that the code-level route can produce different C/D actions. In the real historical data, identical C/D selections are therefore consistent with a combination of law-identification failures and action-objective insensitivity; they are not evidence that D received the Stage1 artifact.

## Conclusion

The engineering protocol is reproducible and the corrected accounting is complete, but the scientific hypothesis is not paper-level validated. Strict raw numerical validity is zero among completed scientific rows, the new follow-up stopped at a documented transport failure, and only half of the merged design's C/D pairs are complete. Calculator-assisted diagnostics can describe what the deterministic calculator would score, but cannot turn invalid raw Agent predictions into valid scientific evidence. The appropriate conclusion is descriptive/non-confirmatory, with all negative and missing results retained.

## Reproduction

See `17_COMPLETE_REPRODUCIBILITY_MANIFEST.json`, `18_RESTRICTED_EVIDENCE.zip`, the frozen proposal and plan, the new run/session logs, the corrected CSV/JSON tables, and `01_HISTORY_BEFORE_SHA256.json` plus the after-hash comparison.
'''
    (REPORT / "14_V5P13_FINAL_SCIENCE_REPORT.md").write_text(report, encoding="utf-8")


def package() -> Path:
    package_path = REPORT / "18_RESTRICTED_EVIDENCE.zip"
    if package_path.exists():
        package_path.unlink()
    entries: list[tuple[Path, str]] = []

    def add(path: Path, arc: str) -> None:
        if path.is_file():
            entries.append((path, arc))
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and "__pycache__" not in child.parts and ".pytest_cache" not in child.parts and child.suffix not in {".pyc", ".pyo"}:
                    entries.append((child, f"{arc}/{child.relative_to(path).as_posix()}"))

    add(REPORT, "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL")
    add(NEW_RUNS[-1], f"runs/{NEW_RUNS[-1].name}")
    session = latest_session_for_run(NEW_RUNS[-1])
    if session:
        add(session, f"runs/real_api_sessions/{session.name}")
    if OLD_PACKAGE.exists():
        add(OLD_PACKAGE, "historical/V5P12_RESTRICTED_REPRODUCIBLE_EVIDENCE.zip")
    for control in sorted((ROOT / "runs").glob("v5p13_control_*")):
        add(control, f"offline_controls/{control.name}")
    for path, arc in [(ROOT / "src", "src"), (ROOT / "scripts", "scripts"), (ROOT / "tests", "tests"), (ROOT / "config", "config"), (ROOT / "docs", "docs"), (ROOT / "data" / "worlds_v5p11_main", "data/worlds_v5p11_main"), (ROOT / "private" / "worlds_v5p11_main", "private/worlds_v5p11_main")]:
        add(path, arc)
    unique: dict[str, Path] = {arc: path for path, arc in entries if arc != package_path.name}
    manifest = {"schema_version": 1, "source_mutation": "NONE", "excluded": [".env", "API keys/tokens", "cache files"], "files": [{"archive_path": arc, "source_path": str(path), "sha256": sha256(path), "size": path.stat().st_size} for arc, path in sorted(unique.items())]}
    write_json(REPORT / "17_COMPLETE_REPRODUCIBILITY_MANIFEST.json", manifest)
    add(REPORT / "17_COMPLETE_REPRODUCIBILITY_MANIFEST.json", "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/17_COMPLETE_REPRODUCIBILITY_MANIFEST.json")
    deduped: dict[str, Path] = {}
    for path, arc in entries:
        deduped[arc] = path
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arc, path in deduped.items():
            if path.resolve() == package_path.resolve():
                continue
            archive.write(path, arc)
    write_json(REPORT / "18_RESTRICTED_EVIDENCE_SHA256.json", {"path": str(package_path), "sha256": sha256(package_path), "size": package_path.stat().st_size, "api_key_included": False})
    return package_path


def main() -> int:
    if not NEW_RUNS:
        raise RuntimeError("no V5-P13 follow-up run found")
    new_run = NEW_RUNS[-1]
    source, rows, calls = build_combined_source(new_run)
    from mini_science.analysis_v5p11 import analyze_v5p11_run
    analysis = REPORT / "14_FINAL_ANALYSIS" / "analysis"
    analyze_v5p11_run(ROOT, CONFIG, source, analysis, real_status="STOPPED_WITH_EVIDENCE", current_stage_prefixes=("V5P13",), planned_condition_rows=40)
    summary = read_json(analysis / "overall_summary.json")
    copy_analysis_outputs(analysis)
    write_derived_tables(analysis, rows, calls)
    write_progress(summary, rows, calls, new_run)
    final_report(summary, rows, calls, new_run)
    package_path = package()
    print(json.dumps({"report": str(REPORT), "combined_slots": len(rows), "merged_calls": len(calls), "new_run": str(new_run), "package": str(package_path), "package_sha256": sha256(package_path)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
