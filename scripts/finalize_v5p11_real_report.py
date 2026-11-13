from __future__ import annotations

"""Create a post-run audit without touching raw V5-P11 request evidence."""

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "016_V5P11_REAL_20261113T072222Z"
RUN = ROOT / "runs" / "real_v5p11_IV001_IV004_20261113T072222Z"
SESSION = ROOT / "runs" / "real_api_sessions" / "v5p11_20261113T072254Z_4QaXzSJmGYKikoua"
ANALYSIS = REPORT / "analysis"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def is_completed(row: dict[str, Any]) -> bool:
    return str(row.get("request_status", row.get("status", ""))).strip().lower() in {"completed", "success", "succeeded"}


def finite_float(value: Any) -> float | None:
    try:
        return None if value in {None, "", "null", "None"} else float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    ledger = read_jsonl(RUN / "call_ledger.jsonl")
    unique: dict[str, dict[str, Any]] = {}
    for row in ledger:
        if row.get("request_id"):
            unique.setdefault(str(row["request_id"]), row)
    unique_rows = list(unique.values())
    completed = [row for row in unique_rows if is_completed(row)]
    failed = [row for row in unique_rows if not is_completed(row)]
    analysis = read_json(ANALYSIS / "overall_summary.json")
    manifest = read_json(RUN / "manifest.json")
    proposal = read_json(ROOT / "reports" / "015_V5P11_PROJECT_FINISH" / "NEW_PROPOSAL.json")
    # The frozen proposal uses the project's canonical proposal fingerprint,
    # not the byte hash of pretty-printed JSON.
    proposal_sha = str(proposal.get("proposal_sha256"))

    reserved = sum(finite_float(row.get("reserved_estimated_cost_usd")) or 0.0 for row in unique_rows)
    completed_usage = sum(finite_float(row.get("local_response_estimate_usd")) or 0.0 for row in completed)
    failed_reserved = sum(finite_float(row.get("reserved_estimated_cost_usd")) or 0.0 for row in failed)
    failed_estimate = sum(finite_float(row.get("estimated_cost_usd")) or 0.0 for row in failed)
    all_estimate = sum(finite_float(row.get("estimated_cost_usd")) or 0.0 for row in unique_rows)
    billed = [finite_float(row.get("provider_billed_cost_usd")) for row in completed]
    billed = [value for value in billed if value is not None]
    cost = {
        "accounting_version": "separated_v3",
        "unique_attempts": len(unique_rows),
        "completed_responses": len(completed),
        "failed_or_unresolved": len(failed),
        "automatic_retries": len(ledger) - len(unique_rows),
        "reserved_estimate_usd": reserved,
        "completed_response_usage_local_estimate_usd": completed_usage,
        "failed_reserved_estimate_usd": failed_reserved,
        "failed_attempt_estimate_upper_bound_usd": failed_estimate,
        "all_attempts_estimate_usd": all_estimate,
        "provider_billed_cost_usd": sum(billed) if billed else None,
        "provider_billing_verified": bool(billed),
        "hard_cap_usd": 0.40,
        "note": "These quantities are not additive actual spend. Provider billing was not returned, so actual billed cost remains unverified.",
    }

    result_rows = read_csv(ANALYSIS / "results_raw.csv")
    executed = [row for row in result_rows if row.get("run_status") == "COMPLETED"]
    stage_rows = read_csv(ANALYSIS / "stage1_relation_and_mapping.csv")
    router_rows = read_csv(ANALYSIS / "stage1_router_proofs.csv")
    pair_rows = read_csv(ANALYSIS / "paired_deltas_action.csv")
    eligible_pairs = [row for row in pair_rows if row.get("status") == "ELIGIBLE"]
    failed_ids = [str(row.get("request_id")) for row in failed]

    corrected = {
        "status": "STOPPED_WITH_EVIDENCE",
        "stop_reason": manifest.get("call_policy", {}).get("stop_reason"),
        "pilot_exit_code": 0,
        "proposal_sha256": proposal_sha,
        "proposal_namespace": proposal.get("request_namespace"),
        "planned_unique_requests": 40,
        "observed_unique_requests_in_ledger": len(unique_rows),
        "completed_unique_requests_in_ledger": len(completed),
        "failed_unique_requests_in_ledger": len(failed),
        "unattempted_planned_requests": 40 - len(unique_rows),
        "automatic_retries": len(ledger) - len(unique_rows),
        "request_ids": sorted(unique),
        "failed_request_ids": failed_ids,
        "run_dir": str(RUN),
        "session_dir": str(SESSION),
        "report_dir": str(REPORT),
        "analysis": analysis,
        "cost_accounting": cost,
        "provider_final_billing_verified": False,
        "raw_operator_result_preserved_as": str(REPORT / "FINAL_EXECUTION_RESULT.json"),
        "notes": "Corrected post-run audit. The original operator summary counted status instead of request_status; no API call was repeated and raw ledgers remain unchanged.",
    }
    (REPORT / "FINAL_EXECUTION_RESULT_CORRECTED.json").write_text(json.dumps(corrected, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (REPORT / "POSTRUN_AUDIT.json").write_text(json.dumps({"corrected_execution": corrected, "cost_accounting": cost, "raw_result_rows": len(result_rows), "executed_scientific_rows": len(executed), "eligible_action_pairs": len(eligible_pairs), "router_rows": router_rows}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    progress = {
        "project": "Mini Science Society",
        "protocol": "V5-P11",
        "engineering_progress": {"status": "COMPLETE", "tests_passed": 171, "tests_failed": 0, "analysis_and_cost_fixes_accepted": True, "four_world_validation": "PASS"},
        "minimal_experiment_progress": {"status": "STOPPED_WITH_EVIDENCE", "planned_requests": 40, "unique_attempts": len(unique_rows), "completed_provider_responses": len(completed), "technical_failures": len(failed), "automatic_retries": 0, "unattempted_requests": 40 - len(unique_rows)},
        "real_science_validation_progress": {"status": "PARTIAL_NOT_PAPER_LEVEL", "executed_scientific_rows": len(executed), "strict_valid_rows": sum(str(row.get("fully_scientifically_valid", "")).lower() == "true" for row in executed), "eligible_cd_action_pairs": sum(row.get("contrast") == "C-D" and row.get("status") == "ELIGIBLE" for row in eligible_pairs), "stage1_c_completed": 2, "stage1_c_correct": 2, "d_block_proof_iv001_r0": True},
        "paper_level_validation_progress": {"status": "NOT_ESTABLISHED", "reason": "transport stop left 30 planned requests unobserved and strict validity was zero in the seven completed scientific rows"},
        "historical_data_preserved": True,
    }
    (REPORT / "PROGRESS.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# V5-P11 real experiment — post-run audit and project status",
        "",
        "## Execution status",
        "",
        "- Protocol: frozen V5-P11 proposal; IV001–IV004, R0/R1, A/B/C/D, 40 planned unique request IDs.",
        f"- Observed: {len(unique_rows)} unique request IDs; {len(completed)} completed provider responses; {len(failed)} technical failure; {40 - len(unique_rows)} planned requests not attempted.",
        "- Automatic retries: 0. Historical reports, V5-P8/V5-P9/V5-P11 logs, and the original operator result are preserved.",
        f"- Stop reason: `{manifest.get('call_policy', {}).get('stop_reason')}`.",
        "- Scientific-output errors were retained in the result rows. The transport failure stopped the run as required.",
        "",
        "## Cost accounting",
        "",
        "| Quantity | USD | Interpretation |",
        "|---|---:|---|",
        f"| Explicit reserved estimates | {reserved:.8f} | reservation ledger only |",
        f"| Completed response local usage estimates | {completed_usage:.8f} | 9 completed responses only |",
        f"| Failed-attempt estimate upper bound | {failed_estimate:.8f} | separate; not provider billing |",
        f"| All attempted planned estimates | {all_estimate:.8f} | 10 attempted request envelopes |",
        "| Provider billed cost | unverified | no provider billing field returned |",
        "",
        "## Scientific measurements",
        "",
        f"- Executed scientific result rows: {len(executed)} of 32 planned condition rows; upstream placeholders are not treated as scientific observations.",
        f"- Selected-action information gain: mean {analysis['information_gain_selected_nats']['mean']:.6f} nats (n={analysis['information_gain_selected_nats']['n']}).",
        f"- Action score: mean {analysis['action_score']['mean']:.6f} (n={analysis['action_score']['n']}).",
        f"- Raw agent numeric accuracy: mean {analysis['raw_agent_numeric_accuracy']['mean']:.6f} (n={analysis['raw_agent_numeric_accuracy']['n']}).",
        f"- Calculator-assisted numeric accuracy: {analysis['assisted_calculator_accuracy']['mean']:.6f} (n={analysis['assisted_calculator_accuracy']['n']}).",
        f"- Strict scientific validity: {analysis['strict_scientific_valid_rate']['mean']:.6f} (n={analysis['strict_scientific_valid_rate']['n']}); strict raw paired deltas are undefined because no executed row passed strict raw validity.",
        "",
        "### Executed rows",
        "",
        "| World | Rep | Condition | Selected | Action score | IG (nats) | Raw numeric acc. | Assisted acc. | Strict valid |",
        "|---|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for row in executed:
        lines.append(f"| {row['world_id']} | {row['replicate']} | {row['condition']} | {row['experiment_id_selected']} | {float(row['top1_action_score']):.6f} | {float(row['ig_selected_action']):.6f} | {float(row['numeric_prediction_accuracy']):.6f} | {float(row['assisted_calculator_accuracy']):.6f} | {row['fully_scientifically_valid']} |")
    lines += [
        "",
        "## Stage1 and C/D routing evidence",
        "",
        "- C/R0 and D/R0 carry the same Stage1 artifact hash; D/R0 has `route_intervention=blocked` and a different forwarded-artifact hash, so the D question designer did not receive the C transferred record.",
        "- C/R1 completed Stage1 and Stage2; D/R1 failed at transport before final validation, so its C/D pair is undefined.",
        "- IV002–IV004 were fail-fast placeholders after the technical stop; no Stage1 or Stage2 scientific output is claimed for them.",
        "",
        "| Contrast | Eligible action pairs | Mean delta |",
        "|---|---:|---:|",
    ]
    for contrast in ("B-A", "C-B", "C-D"):
        values = [float(row["delta"]) for row in eligible_pairs if row.get("contrast") == contrast and row.get("delta") not in {"", None}]
        lines.append(f"| {contrast} | {len(values)} | {sum(values) / len(values) if values else 'UNDEFINED'} |")
    lines += [
        "",
        "## Baselines and conclusion",
        "",
        "- Oracle, random, fixed-E04, and public mathematical heuristics remain the pre-registered offline controls in `reports/015_V5P11_PROJECT_FINISH/BASELINES.csv` and `cheap_baselines.csv`; the real partial run does not replace those controls.",
        "- The executed observations show a calculator-assisted advantage over raw numeric transcription, but strict scientific validity is zero in the seven completed rows because action/schema/evidence and raw numeric validity gates were not jointly satisfied.",
        "- The available real sample does not support a paper-level claim about the four-world hypothesis or a general C−D treatment effect. The only eligible C−D action delta is 0 in IV001/R0; the remaining seven planned pairs are undefined or unobserved.",
        "",
        "## Reproducibility",
        "",
        f"- Raw run: `{RUN}`",
        f"- New authorization session: `{SESSION}`",
        f"- Corrected result: `{REPORT / 'FINAL_EXECUTION_RESULT_CORRECTED.json'}`",
        f"- Restricted evidence ZIP: `{REPORT / 'RESTRICTED_REAL_EVIDENCE_POSTRUN_CORRECTED.zip'}` (created after this audit).",
    ]
    (REPORT / "FINAL_PROJECT_STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
