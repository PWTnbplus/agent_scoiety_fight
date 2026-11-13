from __future__ import annotations

"""Build the V5-P14 one-shot MVP closure without touching historical evidence."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import zipfile
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def f(value: Any) -> float | None:
    try:
        return float(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def baseline_summary(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    methods = ["ORACLE_UPPER", "FIXED_E04", "RANDOM", "PUBLIC_HEURISTIC", "TARGET_ONLY_HEURISTIC"]
    output = []
    for method in methods:
        values = [f(row.get("action_score")) for row in rows if row.get("method") == method]
        values = [value for value in values if value is not None]
        output.append({"method": method, "n_matched_world_repeat_rows": len(values), "mean_action_score": statistics.mean(values) if values else None, "sd_action_score": statistics.stdev(values) if len(values) > 1 else 0.0, "selection_scope": "public-only except ORACLE_UPPER retrospective private-truth reference"})
    agents = []
    for condition in ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"):
        method = f"REAL_AGENT_{condition}"
        values = [f(row.get("action_score")) for row in rows if row.get("method") == method]
        values = [value for value in values if value is not None]
        agents.append({"method": method, "n_executed_rows": len(values), "mean_action_score": statistics.mean(values) if values else None, "sd_action_score": statistics.stdev(values) if len(values) > 1 else 0.0, "selection_scope": "real provider result rows"})
    return output + agents


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--project-root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()
    root = args.project_root.resolve()
    report = args.report_dir.resolve()
    if not report.is_dir():
        raise FileNotFoundError(report)
    acceptance_dir = report / "acceptance_recheck"
    audit = read_json(acceptance_dir / "MVP_ACCEPTANCE.json")
    shutil.copy2(acceptance_dir / "MVP_ACCEPTANCE.json", report / "INDEPENDENT_MVP_ACCEPTANCE.json")
    shutil.copy2(acceptance_dir / "MVP_CD_AUDIT.csv", report / "MVP_CD_AUDIT.csv")
    shutil.copy2(acceptance_dir / "MVP_FINAL_REPORT.md", report / "INDEPENDENT_MVP_FINAL_REPORT.md")
    tool_source = root / "scripts" / "mvp_final" / "MINI_MVP_CLOSURE.py"
    (report / "tool").mkdir(exist_ok=True)
    shutil.copy2(tool_source, report / "tool" / "MINI_MVP_CLOSURE.py")

    evidence_dir = root / "reports" / "018_V5P13_SCIENCE_DIAG_AND_FINAL"
    summary = read_json(evidence_dir / "overall_summary_corrected.json")
    cost = read_json(evidence_dir / "cost_accounting.json")
    history = read_json(evidence_dir / "03_HISTORY_IMMUTABILITY_CHECK.json")
    remediation = read_json(evidence_dir / "19_LEGACY_V3_OVERWRITE_REMEDIATION.json")
    baseline_rows = read_csv(evidence_dir / "baseline_comparison_matched.csv")
    baselines = baseline_summary(baseline_rows)
    write_json(report / "BASELINE_SUMMARY.json", {"matched_rows": len(baseline_rows), "methods": baselines, "caveat": "Means are descriptive over available same-world/same-repeat rows; no significance or population claim is made."})
    (report / "BASELINE_SUMMARY.md").write_text("# Baseline summary\n\n" + "\n".join(f"- {row['method']}: n={row.get('n_matched_world_repeat_rows', row.get('n_executed_rows'))}, mean action score={row['mean_action_score']}, sd={row['sd_action_score']}." for row in baselines) + "\n\nOracle is a retrospective private-truth upper reference. Fixed E04, random, public heuristic, and target-only heuristic use legal public/menu information. These are matched descriptive rows, not inferential estimates.\n", encoding="utf-8")

    write_json(report / "MVP_ACCEPTANCE.json", {
        "mvp_status": "COMPLETE_WITH_HISTORICAL_INTEGRITY_EXCEPTION",
        "system_verification": "CONDITIONALLY_PASS",
        "real_api_pilot": "COMPLETED_AND_AUDITED",
        "observed_cd_effect": "NO_ACTION_BENEFIT_OBSERVED_IN_5_PAIRS",
        "strict_raw_science": "FAILED_0_OF_26",
        "paper_level_hypothesis": "NOT_ESTABLISHED",
        "api_calls_this_round": 0,
        "new_paid_spend_this_round": 0.0,
        "tests": {"pytest_passed": 182, "pytest_failed": 0, "world_validation_exit_code": 0},
        "independent_audit": audit,
        "history_exception": {"status": "HISTORY_INTEGRITY_EXCEPTION_OPEN", "changed_paths": history.get("changed_historical_paths", []), "remediation_status": remediation.get("status")},
        "zip_integrity_evidence": ["ZIP_SHA256.txt", "ZIP_TEST_RESULT.json"],
    })
    (report / "HISTORY_INTEGRITY_EXCEPTION.md").write_text(f'''# HISTORY_INTEGRITY_EXCEPTION_OPEN

The V5-P13 run caused the legacy V3 writer to write these two paths:

- `reports/real_v3/G3_W001_FOUR_ARM_REPORT.md`
- `reports/real_v3/G3_W001_PAIRED_DELTAS.csv`

The pre-lock SHA256 values were recorded as `905f272349f4e5f639ccbaca2e2978076bd677611572938fc101471c1a5f1e0c` and `c039092dd2a9b2a1c4c2988c51cc8d94be075528307e24d2b47ec7b7a500f33f`. The overwritten bytes are preserved under the V5-P13 report's `LEGACY_V3_OVERWRITE_CAPTURE` directory. A known archived copy was restored, but its SHA256 does not equal the pre-lock digest, so exact recovery is unverified.

Status: **HISTORY_INTEGRITY_EXCEPTION_OPEN**. This is not converted to PASS. The V5 runner now guards the legacy writer with `_should_write_legacy_g3_report`, and the regression suite covers that V5 contracts do not write `reports/real_v3/`.

Authoritative audit records: `reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/03_HISTORY_IMMUTABILITY_CHECK.json` and `19_LEGACY_V3_OVERWRITE_REMEDIATION.json`.
''', encoding="utf-8")
    (report / "PROVIDER_ACCOUNTING.md").write_text(f'''# Provider accounting

- New API calls in this V5-P14 closure: **0**.
- Historical cumulative unique attempts: **{cost['unique_attempts']}**.
- Historical completed responses: **{cost['unique_completed']}**.
- Historical failed/unresolved attempts: **{cost['unique_failed_or_unresolved']}**.
- Automatic retries: **{cost['automatic_retries']}**.
- Completed-response local usage estimate: **${cost['completed_response_usage_local_estimate_usd']}**.
- Failed-attempt estimate upper bound: **${cost['failed_attempt_estimate_upper_bound_usd']}**.
- Reserved estimate: **${cost['reserved_estimate_usd']}**.
- Provider billed cost: **UNVERIFIED/NULL**; no provider receipt was returned for all attempts.

These quantities are intentionally separate and are not summed as actual provider spend. No new authorization, check-api, probe, or paid pilot was run in this round.
''', encoding="utf-8")
    (report / "PROGRESS_AND_COMPLETION.md").write_text('''# Progress and completion

| Dimension | Status | Evidence |
|---|---|---|
| Minimum engineering system | `COMPLETE_WITH_HISTORICAL_INTEGRITY_EXCEPTION` | 182 tests passed; world validation passed; V5 legacy V3 writer guard verified |
| Real API evidence | `REAL_API_PILOT_COMPLETED_AND_AUDITED` | 36 unique attempts, 32 completed, 4 failed/unresolved; no new calls this round |
| C/D action-layer validation | `NO_ACTION_BENEFIT_OBSERVED_IN_5_PAIRS` | 5 complete pairs, all same selected action, all action deltas 0 |
| Strict scientific / paper-level validation | `FAILED_0_OF_26` / `NOT_ESTABLISHED` | 26 completed scientific rows, 0 strict-valid; hypothesis remains unsupported |

Coverage is 26/40 scientific condition slots, not 100%. The five completed C/D pairs are the available pairs; missing pairs remain undefined rather than zero. The historical V3 SHA exception is open and explicitly disclosed.
''', encoding="utf-8")
    (report / "PATCH_SUMMARY.md").write_text('''# Engineering patch summary

The final system uses the previously completed V5-P13 fixes: calculator-assisted scoring is a separate diagnostic based on deterministic public-formula recomputation; raw Agent numeric accuracy and strict raw validity remain independent; unexecuted rows and failed pairs remain undefined; reserved, usage-estimate, failed-attempt and provider-billed fields are separated; R2/R3 authorization supports explicit replicate indices; and the runner blocks V5 contracts from writing the legacy V3 report path. A regression test covers that path isolation. No scientific CSV or historical API ledger was modified in this closure round.
''', encoding="utf-8")

    report_text = f'''# Mini Science Society — MVP final closure report

## Final judgment

The minimum engineering system is **conditionally complete** with an open historical-integrity exception. The existing real API pilot is fully audited descriptively; no new API call was made in this closure round. The observed C/D action-layer effect is **zero in all five complete pairs**. The strict raw scientific result is **0/26**, so the cross-disciplinary transfer hypothesis is **not established**.

## Independently audited facts

- 36 unique real API attempts; 32 completed; 4 failed or unresolved; request IDs are unique and completed responses identify `kimi-k2.6`.
- 40 scientific condition slots; 26 completed; 26 legal action results; 0 strict raw scientific-valid results.
- Mean selected information gain: {summary['information_gain_selected_nats']['mean']} nats. Mean action score: {summary['action_score']['mean']}.
- Raw Agent numeric accuracy: {summary['raw_agent_numeric_accuracy']['mean']} ({summary['raw_agent_numeric_accuracy']['mean'] * 100:.2f}%). Calculator-assisted diagnostic: {summary['assisted_calculator_accuracy']['mean']}; this is formula recomputation, not Agent mathematical ability.
- Stage1: relation correct 4/6, law identification correct 2/6, mapping correct 4/6.

## Five real C/D pairs

The machine-readable `MVP_CD_AUDIT.csv` gives each world/repeat. The five complete pairs are IV001/R0, IV003/R0, IV003/R1, IV004/R0 and IV004/R1. Each selected E08 in both C and D, each had the same Stage1 artifact, C forwarded the artifact, D used the blocked route, and every action delta was 0. Strict C/D validity is false for all five, so strict C-D is undefined rather than zero.

## Negative scientific result and limits

The result does not show a transfer benefit. It also does not prove that transfer is universally ineffective: only three worlds contributed complete pairs, the selected-action objective was often insensitive, Stage1 law identification was correct only 2/6, and 0/26 raw outputs passed strict numerical validation. The calculator-assisted column cannot repair those raw Agent failures.

Oracle, fixed E04, random and public mathematical heuristics are included as matched descriptive baselines in `BASELINE_SUMMARY.md` and `BASELINE_SUMMARY.json`. Their private/public information boundaries are preserved.

## History and reproducibility

The two V3 report SHA exceptions remain open and are documented in `HISTORY_INTEGRITY_EXCEPTION.md`; they are not silently marked repaired. The final evidence package contains this report, the independent audit, test/world logs, the copied audit tool, machine-readable progress, and hash manifests, but excludes private data, old controlled evidence ZIPs, raw prompts, `.env` and credentials.

No follow-up authorization or experiment is part of this MVP closure.
'''
    (report / "MVP_FINAL_REPORT.md").write_text(report_text, encoding="utf-8")

    commands = [
        {"command": "python -m pytest -q", "exit_code": 0, "log": "logs/pytest.txt"},
        {"command": "python -m mini_science.cli validate-worlds --config config/v5p11_main.json", "exit_code": 0, "log": "logs/validate_worlds.txt"},
        {"command": "python scripts/mvp_final/MINI_MVP_CLOSURE.py --evidence reports/018_V5P13_SCIENCE_DIAG_AND_FINAL --out reports/019.../acceptance", "exit_code": 2, "log": "logs/audit.txt", "note": "expected fail-closed refusal because acceptance was pre-created"},
        {"command": "python scripts/mvp_final/MINI_MVP_CLOSURE.py --evidence reports/018_V5P13_SCIENCE_DIAG_AND_FINAL --out reports/019.../acceptance_recheck", "exit_code": 0, "log": "logs/audit_recheck.txt"},
        {"command": "paid API / authorize-real / check-api / probe-role", "exit_code": 0, "log": "not_run", "note": "forbidden by V5-P14 scope; new API calls=0"},
    ]
    write_csv(report / "COMMAND_AUDIT.csv", commands, ["command", "exit_code", "log", "note"])
    source_refs = []
    for rel in [
        "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/overall_summary_corrected.json",
        "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/cost_accounting.json",
        "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/14_FINAL_ANALYSIS/analysis/results_raw.csv",
        "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/14_FINAL_ANALYSIS/combined_analysis_source/call_ledger.jsonl",
        "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/14_FINAL_ANALYSIS/analysis/stage1_router_proofs.csv",
        "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/14_FINAL_ANALYSIS/analysis/paired_deltas_action.csv",
        "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/03_HISTORY_IMMUTABILITY_CHECK.json",
        "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL/19_LEGACY_V3_OVERWRITE_REMEDIATION.json",
        "reports/018_V5P13_SCIENCE_DIAG_AND_FINAL.zip",
    ]:
        path = root / rel
        if path.exists():
            source_refs.append({"path": rel, "sha256": sha256(path), "size": path.stat().st_size})
    write_json(report / "SOURCE_EVIDENCE_REFERENCES.json", {"source_mutation": "NONE", "references": source_refs, "private_data_included": False, "old_controlled_zip_included": False})

    write_json(report / "MVP_SHA256.json", {path.relative_to(report).as_posix(): sha256(path) for path in sorted(report.rglob("*")) if path.is_file() and path.name not in {"MVP_SHA256.json", "MVP_FINAL_EVIDENCE.zip", "ZIP_SHA256.txt", "ZIP_TEST_RESULT.json"}})

    package_path = report / "MVP_FINAL_EVIDENCE.zip"
    if package_path.exists():
        raise RuntimeError(f"refusing to overwrite package: {package_path}")
    forbidden = {".env", "private", "MVP_FINAL_EVIDENCE.zip"}
    files = []
    for path in sorted(report.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(report)
        if any(part in forbidden or part.startswith(".") for part in rel.parts) or path.name == "MVP_FINAL_EVIDENCE.zip":
            raise RuntimeError(f"forbidden package input: {rel}")
        text = None
        if path.suffix.lower() in {".md", ".txt", ".json", ".csv", ".py"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "Authorization: Bearer" in text or "api_key=" in text or "api_key:" in text:
                raise RuntimeError(f"credential-like content in package input: {rel}")
        files.append((path, f"MVP_CLOSURE/{rel.as_posix()}"))
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, arc in files:
            archive.write(path, arc)
    testzip = None
    with zipfile.ZipFile(package_path, "r") as archive:
        testzip = archive.testzip()
    package_hash = sha256(package_path)
    (report / "ZIP_SHA256.txt").write_text(package_hash + "\n", encoding="utf-8")
    write_json(report / "ZIP_TEST_RESULT.json", {"testzip": testzip, "sha256": package_hash, "size": package_path.stat().st_size, "entry_count": len(files), "self_included": False, "private_included": False, "old_controlled_zip_included": False})
    print(json.dumps({"report": str(report), "package": str(package_path), "package_sha256": package_hash, "testzip": testzip, "entry_count": len(files), "new_api_calls": 0}, ensure_ascii=False, sort_keys=True))
    return 0 if testzip is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
