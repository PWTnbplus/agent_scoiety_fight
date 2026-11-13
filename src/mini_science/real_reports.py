from __future__ import annotations

"""Non-secret reports for the staged real-provider pilot."""

import csv
import json
from pathlib import Path
from typing import Any

from .analysis import paired_metrics


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def report_root(project_root: str | Path) -> Path:
    path = Path(project_root).resolve() / "reports" / "real_v3"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_api_budget_ledger(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    destination = report_root(root) / "API_BUDGET_LEDGER.csv"
    state_path = root / "runs" / "v3_real_gate_state.json"
    state = _json(state_path)
    fields = ["request_id", "attempt_number", "provider", "model", "stage", "world_id", "condition", "estimated_cost_usd", "actual_cost_usd", "billing_verified", "status", "returned_model", "error"]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in state.get("attempts", []):
            writer.writerow({field: item.get(field, "") for field in fields})
    return destination


def write_g1_report(project_root: str | Path, *, run_dir: Path, result: dict[str, Any], budget_plan: list[dict[str, Any]], gate_summary: dict[str, Any]) -> Path:
    root = Path(project_root).resolve()
    destination = report_root(root) / "G1_API_CONTRACT_REPORT.md"
    plan = budget_plan[0] if budget_plan else {}
    lines = [
        "# G1 Kimi2.6 API contract report",
        "",
        f"- run_dir: `{run_dir}`",
        f"- provider: `{result.get('provider', 'kimi26')}`",
        f"- requested_model: `{result.get('requested_model', '')}`",
        f"- returned_model: `{result.get('returned_model')}`",
        f"- gate_result: `{result.get('gate_result', 'UNKNOWN')}`",
        f"- contract_json_valid: `{result.get('contract_json_valid')}`",
        f"- usage_source: `{result.get('usage_source')}`",
        f"- billing_source: `{result.get('billing_source')}`",
        f"- request_attempts: `{result.get('request_attempts')}`",
        f"- truncated: `{result.get('truncated')}`",
        f"- request_hash: `{plan.get('prompt_hash', '')}`",
        f"- response_hash: `{result.get('response_hash', '')}`",
        f"- input_tokens: `{result.get('input_tokens')}`",
        f"- output_tokens: `{result.get('output_tokens')}`",
        f"- local_estimated_cost_usd: `{plan.get('estimated_cost_usd')}`",
        f"- adapter_local_response_cost_usd: `{result.get('cost_usd')}`",
        "- provider_billed_cost_usd: `UNVERIFIED`",
        f"- gate_summary: `{json.dumps(gate_summary, ensure_ascii=False, sort_keys=True)}`",
        "",
        "No API key, Authorization header, or raw credential is included in this report.",
    ]
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_api_budget_ledger(root)
    return destination


def write_g2_report(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    destination = report_root(root) / "G2_ROLE_PROBES.md"
    lines = ["# G2 role probe report", "", "| role | run | JSON | schema | gate | truncated | candidate law | law correct | usage | input | output | local cost |", "|---|---|---|---|---|---|---|---|---|---:|---:|---:|"]
    probe_dirs = sorted((root / "runs").glob("real_kimi26_probe_*"))
    blocked: list[str] = []
    for run_dir in probe_dirs:
        manifest = _json(run_dir / "manifest.json")
        if not manifest.get("role"):
            continue
        check = manifest.get("contract_check", {})
        if not check:
            blocked.append(f"`{run_dir.name}`: {manifest.get('error', 'pre-request gate block')}")
            continue
        response = _json(run_dir / "probe_response.json").get("response", {})
        lines.append(f"| {manifest.get('role', '')} | `{run_dir.name}` | {check.get('json_valid')} | {check.get('schema_valid')} | {check.get('gate_result')} | {check.get('truncated')} | {check.get('candidate_law_id', '')} | {check.get('law_id_correct', '')} | {check.get('usage_source')} | {response.get('input_tokens', '')} | {response.get('output_tokens', '')} | {response.get('cost_usd', '')} |")
    if not probe_dirs:
        lines.append("| — | NOT_RUN | — | — | NOT_RUN | — | — | — | — |")
    lines.extend(["", "Role probes are diagnostic and are not reused as the formal C/D stage-1 artifact."])
    if blocked:
        lines.extend(["", "Pre-request local gate blocks (no provider attempt):"] + [f"- {item}" for item in blocked])
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_api_budget_ledger(root)
    return destination


def write_g3_report(project_root: str | Path, run_dir: str | Path) -> Path:
    root = Path(project_root).resolve()
    run_path = Path(run_dir).resolve()
    destination = report_root(root) / "G3_W001_FOUR_ARM_REPORT.md"
    manifest = _json(run_path / "manifest.json")
    rows = []
    results_path = run_path / "results.csv"
    if results_path.exists():
        with results_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    selected = {row.get("condition"): row for row in rows if row.get("condition") in {"A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}}
    ba = paired_metrics(selected.get("B_SINGLE_RELATED"), selected.get("A_TARGET_ONLY"))
    cd = paired_metrics(selected.get("C_SEQ2_TRANSFER"), selected.get("D_SEQ2_BLOCK"))
    cb = paired_metrics(selected.get("C_SEQ2_TRANSFER"), selected.get("B_SINGLE_RELATED"))
    ledger_lines = (run_path / "call_ledger.jsonl").read_text(encoding="utf-8").splitlines() if (run_path / "call_ledger.jsonl").exists() else []
    gate_summary = manifest.get("call_policy", {}).get("gate_summary", {})
    stop_reason = manifest.get("call_policy", {}).get("stop_reason")
    stage1_path = run_path / "agent_artifacts" / "W001" / "replicate_0" / "C_SEQ2_TRANSFER" / "stage1.json"
    stage1_meta = _json(stage1_path)
    baseline = {}
    baseline_path = root / "reports" / "v3" / "cheap_baselines.csv"
    if baseline_path.exists():
        with baseline_path.open(newline="", encoding="utf-8") as handle:
            baseline = next((item for item in csv.DictReader(handle) if item.get("world_id") == "W001"), {})
    planned_calls = len(manifest.get("call_policy", {}).get("budget_plan", []))
    lines = [
        "# G3 W001 four-arm report",
        "",
        f"- run_dir: `{run_path}`",
        f"- real_api_status: `{manifest.get('call_policy', {}).get('real_api_status', 'UNKNOWN')}`",
        f"- planned unique provider calls: `{planned_calls}`",
        f"- provider attempts issued in this G3 run: `{sum(1 for line in ledger_lines if line.strip())}`",
        f"- cumulative provider attempts in authorized session: `{gate_summary.get('calls_used', '')}`",
        f"- stop_reason: `{stop_reason or 'none'}`",
        "",
        "The run stopped immediately after the first formal pilot result failed structured JSON parsing. C stage1 was completed and validated, B completed, A returned a JSON object inside Markdown fences, and C stage2/D were not called.",
        "",
        "| condition | experiment | strict Top-1 | action-only | valid | run status | stage1 law | law correct | transfer | workflow calls | tokens | local cost |",
        "|---|---|---:|---:|---|---|---|---|---|---:|---:|---:|",
    ]
    for condition in ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"):
        row = selected.get(condition, {})
        lines.append(f"| {condition} | {row.get('experiment_id_selected', '')} | {row.get('top1_score', '')} | {row.get('top1_action_score', '')} | {row.get('valid', '')} | {row.get('run_status', '')} | {row.get('candidate_law_id', '')} | {row.get('law_id_correct', '')} | {row.get('route_intervention', '') or row.get('transfer_applied', '')} | {row.get('full_workflow_calls', '')} | {row.get('full_workflow_tokens', '')} | {row.get('estimated_cost_usd', '')} |")
    lines.extend([
        "",
        "## Formal stage1 evidence",
        "",
        f"- C stage1 schema valid: `{stage1_meta.get('valid', '')}`",
        f"- C stage1 artifact hash: `{stage1_meta.get('stage1_artifact_sha256', '')}`",
        "- C and D paired metrics are reported separately: action-only can be eligible while strict remains `UNDEFINED`.",
        f"- B-A action-only: `{ba.get('delta_action_only')}`; strict: `{ba.get('delta_strict') if ba.get('delta_strict') is not None else 'UNDEFINED'}`.",
        f"- C-D action-only: `{cd.get('delta_action_only')}`; strict: `{cd.get('delta_strict') if cd.get('delta_strict') is not None else 'UNDEFINED'}`; same Stage1 artifact: `{cd.get('same_stage1_artifact')}`.",
        f"- C-B action-only: `{cb.get('delta_action_only')}`; strict: `{cb.get('delta_strict') if cb.get('delta_strict') is not None else 'UNDEFINED'}`.",
        "",
        "## Baseline comparison for W001",
        "",
        "| baseline | experiment | Top-1 |",
        "|---|---|---:|",
        f"| random mean | — | {baseline.get('random_mean_score', '')} |",
        f"| fixed E04 | {baseline.get('fixed_e04_experiment', '')} | {baseline.get('fixed_e04_score', '')} |",
        f"| max time | {baseline.get('max_time_experiment', '')} | {baseline.get('max_time_score', '')} |",
        f"| max x0 | {baseline.get('max_x0_experiment', '')} | {baseline.get('max_x0_score', '')} |",
        f"| simple predicted gap | {baseline.get('simple_predicted_gap_experiment', '')} | {baseline.get('simple_predicted_gap_score', '')} |",
        "",
        "B-A is not interpretable as a scientific effect because A failed the structured-output contract and received score 0 by the frozen scorer. C-D and C-B are `NOT_AVAILABLE`; no C/D pair exists.",
        "",
        f"- gate_summary: `{json.dumps(gate_summary, ensure_ascii=False, sort_keys=True)}`",
    ])
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paired = run_path / "paired_deltas.csv"
    if paired.exists():
        (report_root(root) / "G3_W001_PAIRED_DELTAS.csv").write_text(paired.read_text(encoding="utf-8"), encoding="utf-8")
    write_api_budget_ledger(root)
    return destination
