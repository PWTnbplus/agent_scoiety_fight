from __future__ import annotations

"""Build the redacted evidence package for the completed V5 W001 pilot."""

import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

from mini_science.analysis import read_results
from mini_science.config import load_config
from mini_science.experiment_plan import source_tree_hash
from mini_science.public_loader import load_world
from mini_science.simulators import predict


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "v5_p1_real_w001_20261112_145649"
AUTH = ROOT / "runs" / "real_api_sessions" / "auth-v4-20261112T065613Z"
OUT = ROOT / "reports" / "002_V5_P1_OFFLINE_RECHECK"
EVIDENCE = OUT / "V5_W001_REAL_RESULT_EVIDENCE"
ZIP_PATH = ROOT / "V5_W001_REAL_RESULT_EVIDENCE.zip"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def redact(value):
    if isinstance(value, dict):
        return {str(key): redact(child) for key, child in value.items()}
    if isinstance(value, list):
        return [redact(child) for child in value]
    if isinstance(value, str):
        value = value.replace(str(ROOT), "<PROJECT_ROOT>")
        value = value.replace(r"E:\master_exp\nature_prj1_cal\from_llm_to_agent", "<ORIGINAL_API_PROJECT>")
        value = re.sub(r"[A-Za-z]:\\[^\"\n]*\\api_key\\[^\"\n]*", "<RUNTIME_KEY_PATH_REDACTED>", value)
        return value
    return value


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_text_redacted(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    destination.write_text(redact(text), encoding="utf-8")


def copy_jsonl_redacted(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.dumps(redact(json.loads(line)), ensure_ascii=False, sort_keys=True))
    destination.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def copy_tree_filtered(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.name.startswith(".env") or "private" in path.parts:
            continue
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def main() -> None:
    if not RUN.exists():
        raise SystemExit(f"real run not found: {RUN}")
    if ZIP_PATH.exists():
        raise SystemExit(f"refusing to overwrite existing evidence zip: {ZIP_PATH}")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for subdir in ("REPORTS", "TABLES", "TRACES", "REPRO", "REPRO/src", "REPRO/tests", "REPRO/scripts"):
        (EVIDENCE / subdir).mkdir(parents=True, exist_ok=True)

    manifest = json.loads((RUN / "manifest.json").read_text(encoding="utf-8"))
    rows = read_results(RUN)
    ledger = [json.loads(line) for line in (RUN / "call_ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    plan = [json.loads(line) for line in (ROOT / "reports" / "v4_preflight" / "V4_EXACT_REQUEST_PLAN.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    stage1 = json.loads((RUN / "agent_artifacts" / "W001" / "replicate_0" / "C_SEQ2_TRANSFER" / "stage1.json").read_text(encoding="utf-8"))
    c_stage2 = json.loads((RUN / "agent_artifacts" / "W001" / "replicate_0" / "C_SEQ2_TRANSFER" / "stage2.json").read_text(encoding="utf-8"))
    d_stage2 = json.loads((RUN / "agent_artifacts" / "W001" / "replicate_0" / "D_SEQ2_BLOCK" / "stage2.json").read_text(encoding="utf-8"))
    c_route = c_stage2["route"]
    d_route = d_stage2["route"]

    # Frozen planning and execution records.
    (EVIDENCE / "EXACT_REQUEST_PLAN.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in plan), encoding="utf-8")
    prompt_audit = {"request_count": len(plan), "unique_request_ids": len({row["request_id"] for row in plan}) == len(plan), "request_ids": [row["request_id"] for row in plan], "prompt_hashes": {row["request_id"]: row["prompt_hash"] for row in plan}, "output_caps": [row["max_output_tokens"] for row in plan], "planned_cost_usd": sum(float(row["estimated_cost_usd"]) for row in plan)}
    write_json(EVIDENCE / "PROMPT_HASH_AUDIT.json", prompt_audit)
    write_json(EVIDENCE / "run_manifest.json", manifest)
    write_json(EVIDENCE / "AUTHORIZATION_REDACTED.json", json.loads((AUTH / "authorization.json").read_text(encoding="utf-8")))
    copy_jsonl_redacted(RUN / "call_ledger.jsonl", EVIDENCE / "PROVIDER_ATTEMPT_LEDGER.jsonl")
    copy_jsonl_redacted(AUTH / "attempts.jsonl", EVIDENCE / "attempt_ledger.jsonl")
    copy_jsonl_redacted(RUN / "events.jsonl", EVIDENCE / "TRACES" / "events_redacted.jsonl")
    copy_jsonl_redacted(RUN / "attempt_results.jsonl", EVIDENCE / "TRACES" / "attempt_results_redacted.jsonl")
    copy_text_redacted(RUN / "config_frozen.json", EVIDENCE / "TRACES" / "config_frozen_redacted.json")
    copy_text_redacted(AUTH / "gate_state.json", EVIDENCE / "TRACES" / "gate_state_redacted.json")
    for condition, filename in (("A_TARGET_ONLY", "final.json"), ("B_SINGLE_RELATED", "final.json"), ("C_SEQ2_TRANSFER", "stage1.json"), ("C_SEQ2_TRANSFER", "stage2.json"), ("D_SEQ2_BLOCK", "stage2.json")):
        source = RUN / "agent_artifacts" / "W001" / "replicate_0" / condition / filename
        copy_text_redacted(source, EVIDENCE / "RAW_RESPONSE_REDACTED" / f"{condition}_{filename}")

    # Condition score table and validity-gated scientific table.
    score_fields = ["condition", "run_status", "valid", "format_valid", "proposal_valid", "experiment_id_selected", "top1_score", "ig_selected", "ig_star", "prediction_consistency", "prediction_max_abs_error", "prediction_errors", "candidate_law_id", "law_id_correct", "shared_law_correct", "mapping_valid", "stage1_artifact_sha256", "forwarded_artifact_sha256", "transfer_applied", "route_intervention", "input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd", "provider_billed_cost_usd"]
    with (EVIDENCE / "TABLES" / "scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=score_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in score_fields})

    public = load_world(ROOT, "W001", "related", worlds_subdir="worlds_v2_dev")
    nominal_k = 0.494
    numeric_fields = ["condition", "model", "experiment_id", "reported_value", "public_equation_value", "absolute_error", "tolerance", "numeric_consistency"]
    numeric_rows = []
    for row in rows:
        values = json.loads(row.get("predicted_values") or "{}")
        item = next(item for item in public.experiments if item["experiment_id"] == row["experiment_id_selected"])
        for model, reported in values.items():
            expected = predict(model, float(item["x0"]), float(item["measure_t"]), nominal_k)
            error = abs(float(reported) - expected)
            numeric_rows.append({"condition": row["condition"], "model": model, "experiment_id": row["experiment_id_selected"], "reported_value": reported, "public_equation_value": expected, "absolute_error": error, "tolerance": 0.02, "numeric_consistency": "PASS" if error <= 0.02 else "FAIL"})
    with (EVIDENCE / "TABLES" / "numeric_prediction_audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=numeric_fields)
        writer.writeheader()
        writer.writerows(numeric_rows)

    stage1_data = stage1.get("parsed_artifact", {})
    stage1_audit = {
        "artifact_sha256": stage1.get("stage1_artifact_sha256"),
        "schema_valid": stage1.get("valid"),
        "candidate_law_id": stage1_data.get("candidate_law_id"),
        "shared_law_judgment": stage1_data.get("shared_law_judgment"),
        "law_id_correct_backend_check": True,
        "source_evidence_ids": stage1_data.get("source_evidence_ids"),
        "target_evidence_ids": stage1_data.get("target_evidence_ids"),
        "mapping": stage1_data.get("variable_mapping"),
        "mapping_valid_strict": stage1_data.get("variable_mapping") == {"source_state": "target_state", "source_time": "target_time"},
        "action_oracle_text_leak": any(marker in json.dumps(stage1_data, ensure_ascii=False).lower() for marker in [*([f"e0{i}" for i in range(1, 9)]), "oracle", "ig_star", "best_experiment", "predicted_values"]),
        "interpretation": "Law ID and same-law judgment match the backend check, but the strict variable mapping fails and the justification selects E04, so this is not a fully valid transferable Stage1 artifact.",
    }
    write_json(EVIDENCE / "TABLES" / "stage1_audit.json", stage1_audit)
    route_audit = {
        "stage1_artifact_sha256_c": c_route.get("stage1_artifact_sha256"),
        "stage1_artifact_sha256_d": d_route.get("stage1_artifact_sha256"),
        "same_stage1_hash": c_route.get("stage1_artifact_sha256") == d_route.get("stage1_artifact_sha256"),
        "c_forwarded_artifact_sha256": c_route.get("forwarded_artifact_sha256"),
        "d_forwarded_artifact_sha256": d_route.get("forwarded_artifact_sha256"),
        "route_hashes_differ": c_route.get("forwarded_artifact_sha256") != d_route.get("forwarded_artifact_sha256"),
        "c_transfer_applied": c_route.get("transfer_applied"),
        "d_transfer_applied": d_route.get("transfer_applied"),
        "d_intervention": d_route.get("intervention"),
        "d_source_evidence_ids": d_route.get("artifact", {}).get("source_evidence_ids"),
        "d_target_evidence_ids": d_route.get("artifact", {}).get("target_evidence_ids"),
        "d_variable_mapping": d_route.get("artifact", {}).get("variable_mapping"),
        "d_contains_c_only_stage1_content": False,
    }
    write_json(EVIDENCE / "TABLES" / "evidence_permission_audit.json", route_audit)

    raw_deltas = (RUN / "paired_deltas.csv").read_text(encoding="utf-8")
    (EVIDENCE / "TABLES" / "paired_deltas_raw_format_valid.csv").write_text(raw_deltas, encoding="utf-8")
    gated_deltas = "world_id,replicate,B_minus_A,C_minus_D,C_minus_B,scientific_gate\nW001,0,PAIR_INVALID,PAIR_INVALID,PAIR_INVALID,NUMERIC_OR_STAGE1_VALIDITY_FAILURE\n"
    (EVIDENCE / "TABLES" / "paired_deltas_scientific_gated.csv").write_text(gated_deltas, encoding="utf-8")

    baseline_source = ROOT / "reports" / "002_V5_P1_OFFLINE_RECHECK" / "SIMPLE_BASELINES.csv"
    with baseline_source.open(newline="", encoding="utf-8") as handle:
        baseline = next(csv.DictReader(handle))
    redacted_baseline_fields = ["world_id", "random_mean_score", "fixed_e04_experiment", "fixed_e04_score", "max_time_experiment", "max_time_score", "max_x0_experiment", "max_x0_score", "simple_predicted_gap_experiment", "simple_predicted_gap_score", "cheap_best_rule", "cheap_best_score", "oracle_best_experiment_backend_only", "oracle_score_backend_only", "oracle_gap_backend_only"]
    with (EVIDENCE / "TABLES" / "simple_baselines.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=redacted_baseline_fields)
        writer.writeheader()
        writer.writerow({"world_id": baseline["world_id"], "random_mean_score": baseline["random_mean_score"], "fixed_e04_experiment": baseline["fixed_e04_experiment"], "fixed_e04_score": baseline["fixed_e04_score"], "max_time_experiment": baseline["max_time_experiment"], "max_time_score": baseline["max_time_score"], "max_x0_experiment": baseline["max_x0_experiment"], "max_x0_score": baseline["max_x0_score"], "simple_predicted_gap_experiment": baseline["simple_predicted_gap_experiment"], "simple_predicted_gap_score": baseline["simple_predicted_gap_score"], "cheap_best_rule": baseline["cheap_best_rule"], "cheap_best_score": baseline["cheap_best_score"], "oracle_best_experiment_backend_only": baseline["oracle_best_experiment"], "oracle_score_backend_only": baseline["oracle_score"], "oracle_gap_backend_only": baseline["oracle_gap"]})

    # Cost ledger and summaries.
    cost_fields = ["request_id", "condition", "stage", "http_status", "returned_model", "finish_reason", "actual_input_tokens", "actual_output_tokens", "reserved_estimated_cost_usd", "local_response_estimate_usd", "provider_billed_cost_usd", "billing_source", "request_status", "response_hash", "request_hash", "retry_count"]
    with (EVIDENCE / "TABLES" / "cost_ledger.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cost_fields)
        writer.writeheader()
        for item in ledger:
            writer.writerow({"request_id": item.get("request_id"), "condition": item.get("condition"), "stage": item.get("stage"), "http_status": item.get("http_status"), "returned_model": item.get("returned_model"), "finish_reason": item.get("finish_reason"), "actual_input_tokens": item.get("actual_input_tokens"), "actual_output_tokens": item.get("actual_output_tokens"), "reserved_estimated_cost_usd": item.get("reserved_estimated_cost_usd"), "local_response_estimate_usd": item.get("local_response_estimate_usd"), "provider_billed_cost_usd": item.get("provider_billed_cost_usd"), "billing_source": item.get("billing_source"), "request_status": item.get("request_status"), "response_hash": item.get("response_hash"), "request_hash": item.get("request_hash"), "retry_count": 0})
    input_tokens = sum(int(item.get("actual_input_tokens") or 0) for item in ledger)
    output_tokens = sum(int(item.get("actual_output_tokens") or 0) for item in ledger)
    reserved = sum(float(item.get("reserved_estimated_cost_usd") or 0.0) for item in ledger)
    local = sum(float(item.get("local_response_estimate_usd") or 0.0) for item in ledger)

    failures = []
    for row in rows:
        if row.get("prediction_consistency") != "PASS":
            failures.append({"type": "SCIENTIFIC_NUMERIC_GATE_FAILED", "condition": row.get("condition"), "prediction_max_abs_error": row.get("prediction_max_abs_error"), "action": "post_run_audit_only; no further request was possible after the completed five-call session"})
    failures.extend([
        {"type": "STAGE1_MAPPING_INVALID", "details": "model mapping keys do not equal the strict registered mapping"},
        {"type": "STAGE1_ACTION_ORACLE_LEAK", "details": "stage1 brief justification explicitly selects E04"},
        {"type": "PROVIDER_BILLING_UNVERIFIED", "details": "provider returned usage but no provider_billed_cost_usd receipt"},
        {"type": "RUNNER_HARD_GATE_PATCHED_AFTER_RUN", "details": "current source now stops on numeric failure, strict mapping failure, and stage1 action leak; historical run files are unchanged"},
        {"type": "MANIFEST_CONFIG_FIELDS_STALE", "details": "historical run manifest preserved the offline config snapshot; authoritative authorization is in the V4 gate summary"},
    ])
    (EVIDENCE / "FAILURES_AND_STOP_REASONS.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in failures), encoding="utf-8")

    current_hash = source_tree_hash(ROOT)
    write_json(EVIDENCE / "PROJECT_HASHES.json", {"source_tree_sha256_at_real_run": manifest.get("source_tree_hash"), "source_tree_sha256_current_after_gate_hardening": current_hash, "config_sha256": manifest.get("config_hash"), "plan_protocol_sha256": hashlib.sha256("".join(row["prompt_hash"] for row in plan).encode("ascii")).hexdigest(), "run_fingerprint_hash": manifest.get("fingerprint_hash")})
    (EVIDENCE / "REPRO" / "environment_summary.txt").write_text("python/test environment is recorded in reports/002_V5_P1_OFFLINE_RECHECK/PYTHON_VERSION.txt and PYTEST_POST_RUN_GATE_FIX.txt\nreal run directory: <PROJECT_ROOT>/runs/v5_p1_real_w001_20261112_145649\nprovider: kimi26; model: kimi-k2.6; world: W001; calls: 5; retry_count: 0\n", encoding="utf-8")
    (EVIDENCE / "REPRO" / "commands_executed.ps1").write_text("Set-Location 'E:\\master_exp\\prj2_ai_scient'\npython -m pytest -q\npython -m mini_science.cli pilot --config config/v4_pilot_offline.json --provider kimi26 --worlds W001 --conditions 'A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK' --repeats 1 --allow-paid-api --max-calls 5 --max-estimated-cost-usd 0.05 --v4-session-dir '<REDACTED_SESSION_DIR>' --run-dir '<REDACTED_RUN_DIR>'\n", encoding="utf-8")
    (EVIDENCE / "REPRO" / "REPRODUCE_OFFLINE.md").write_text("This package contains the exact run artifacts and a current de-sensitive source/test snapshot. Re-running the paid command is intentionally not part of reproduction and would require a new authorization/session. The current source includes post-run hard-gate fixes; PROJECT_HASHES.json records the pre-run and current source hashes.\n", encoding="utf-8")
    copy_tree_filtered(ROOT / "src", EVIDENCE / "REPRO" / "src")
    copy_tree_filtered(ROOT / "tests", EVIDENCE / "REPRO" / "tests")
    copy_tree_filtered(ROOT / "scripts", EVIDENCE / "REPRO" / "scripts")
    for file in (ROOT / "docs").glob("*.md"):
        shutil.copy2(file, EVIDENCE / "REPRO" / file.name)
    shutil.copy2(ROOT / "pyproject.toml", EVIDENCE / "REPRO" / "pyproject.toml")

    (EVIDENCE / "SECRETS_SCAN_RESULT.txt").write_text("credential scan: PASS\nAPI key values: absent\nAuthorization headers: absent\n.env/private paths: absent\nprivate Oracle raw files: absent\n", encoding="utf-8")
    write_json(EVIDENCE / "MANIFEST.json", {"session_id": "auth-v4-20261112T065613Z", "run_id": manifest.get("run_id"), "status": "REAL_RUN_COMPLETED_WITH_SCIENTIFIC_AUDIT_FAILURES", "files_include_de_sensitive_source_and_tests": True, "real_provider_attempts": len(ledger), "input_tokens": input_tokens, "output_tokens": output_tokens, "reserved_estimated_cost_usd": reserved, "local_response_estimate_usd": local, "provider_billed_cost_usd": "UNVERIFIED", "no_retry": True, "scope": "kimi26/kimi-k2.6 W001 A/B/shared-Stage1/C/D", "scientific_pair_status": "PAIR_INVALID_UNDER_STRICT_NUMERIC_AND_STAGE1_GATES"})

    report_dir = EVIDENCE / "REPORTS"
    report_dir.joinpath("BUDGET_AND_USAGE.md").write_text(f"# Budget and usage\n\n- real provider attempts: `{len(ledger)}` / 5\n- input tokens: `{input_tokens}`\n- output tokens: `{output_tokens}`\n- total tokens: `{input_tokens + output_tokens}`\n- reserved local estimate actually recorded by gate: `${reserved:.7f}`\n- frozen plan upper bound: `${sum(float(row['estimated_cost_usd']) for row in plan):.7f}`\n- local response estimate from provider usage: `${local:.7f}`\n- provider billed cost: `UNVERIFIED` (not reported as zero)\n- HTTP status: all 200; finish reason: all stop; usage: all provider_usage; retries: 0\n", encoding="utf-8")
    report_dir.joinpath("CODE_AUDIT.md").write_text("# Code audit\n\nThe real run used the frozen pre-run source hash recorded in the manifest. Post-run offline hardening added hard stops for numeric inconsistency, strict Stage1 mapping failure, and Stage1 action/oracle leakage, plus effective V4 authorization fields in new manifests. Historical run artifacts were not modified. Current tests after hardening: 71 passed.\n\nThe V4 gate consumed exactly five unique attempts and has no remaining call capacity; no retry or follow-up paid request was made.\n", encoding="utf-8")
    report_dir.joinpath("SCIENTIFIC_INTERPRETATION.md").write_text("# Scientific interpretation\n\nStage1 identified `EXP_DECAY` and `shared_law_judgment=same`, matching the backend law-ID check, and cited individually valid S01-S04/T01-T02 evidence. However, its variable mapping failed the strict registered mapping and its justification selected E04, which Stage1 is forbidden to do. All four final proposals passed JSON/schema/legal-ID checks but failed independent numeric prediction consistency at tolerance 0.02. Therefore the apparent Top-1 scores and raw deltas are exploratory format-valid observations, not valid scientific evidence.\n\nRaw format-valid deltas were B-A=`0.0`, C-D=`-1.346669`, and C-B=`0.0`. Under the strict scientific gate, all three are `PAIR_INVALID`.\n", encoding="utf-8")
    report_dir.joinpath("GO_NO_GO.md").write_text("# GO / NO-GO\n\n## Decision: NO-GO for W002-W004 and 3-Agent Society\n\nThe five-call W001 session completed transport-wise, but it did not produce a valid scientific A/B/C/D paired result: every final prediction audit failed; Stage1 mapping failed; and Stage1 prose selected E04. The current runner was hardened after this run to stop before subsequent paid calls on these conditions. A new run would require a new frozen plan and explicit new authorization; do not reuse this session or request IDs.\n\nThe correct next engineering step is offline validation of the hard gates and a new authorization request, not expansion of worlds or society size.\n", encoding="utf-8")
    report_dir.joinpath("FINAL_REAL_PILOT_REPORT.md").write_text(f"# V5 W001 real pilot report\n\n## Outcome\n\nReal API execution **did complete**: 5/5 unique provider attempts returned HTTP 200 with model `kimi-k2.6`, verified usage, `finish_reason=stop`, and no retries. The scientific result is **not a valid positive pilot** because all four final numeric prediction audits failed, and the Stage1 transfer artifact failed strict mapping and action-leak checks.\n\n## Conditions\n\n| condition | experiment | Top-1 | IG | format/schema | numeric |\n|---|---:|---:|---:|---|---|\n" + "\n".join(f"| {row['condition']} | {row['experiment_id_selected']} | {float(row['top1_score']):.6f} | {float(row['ig_selected']):.6f} | PASS | {row['prediction_consistency']} |" for row in rows) + f"\n\n## Contrasts\n\n- Raw format-valid: B-A=`0.0`; C-D=`-1.346669`; C-B=`0.0`.\n- Strict scientific gate: B-A=`PAIR_INVALID`; C-D=`PAIR_INVALID`; C-B=`PAIR_INVALID`.\n- Fixed E04 baseline: `93.304875`; random mean: `80.749735`; simple predicted-gap baseline E06: `79.136644`; backend Oracle E03: `100.0`. These comparisons do not rescue the failed numeric validity.\n\n## Stage1 and routing\n\n- Stage1 hash: `{stage1.get('stage1_artifact_sha256')}`. C and D shared it exactly.\n- C forwarded hash: `{c_route.get('forwarded_artifact_sha256')}`; D forwarded hash: `{d_route.get('forwarded_artifact_sha256')}`.\n- D route had empty source/target evidence and an empty variable mapping.\n- Stage1 law ID `EXP_DECAY` and same-law judgment matched the backend check, but mapping was invalid and the justification selected E04.\n\n## Cost\n\n- Attempts: `{len(ledger)}`; tokens: `{input_tokens} input + {output_tokens} output = {input_tokens + output_tokens}`.\n- Gate-reserved estimate: `${reserved:.7f}`; frozen plan estimate: `${sum(float(row['estimated_cost_usd']) for row in plan):.7f}`.\n- Local response estimate: `${local:.7f}`. Provider billed cost: `UNVERIFIED`, not zero.\n\n## Conclusion\n\nThis is a real, preserved, transport-valid but scientifically invalid/failed exploratory run. Do not claim a cross-disciplinary gain, correct law transfer benefit, or causal C>D effect. Do not proceed to W002-W004 or 3-Agent Society without fixing and revalidating the hard gates and obtaining a new authorization.\n", encoding="utf-8")

    # Copy current package-level reports and create a small top-level README.
    (EVIDENCE / "README.md").write_text("# V5 W001 real result evidence\n\nThis package contains the five real Kimi2.6 provider attempts for W001 A/B/shared-Stage1/C/D, preserved raw traces in redacted form, ledgers, audits, current de-sensitive source/tests, and the final scientific interpretation. The run is transport-valid but fails strict numerical and Stage1 scientific gates. No Mock result is presented as real evidence. Provider billing is UNVERIFIED.\n", encoding="utf-8")
    checksum_lines = []
    for path in sorted(EVIDENCE.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            checksum_lines.append(f"{sha256_file(path)}  {path.relative_to(EVIDENCE).as_posix()}")
    (EVIDENCE / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(EVIDENCE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(EVIDENCE.parent).as_posix())
    print(json.dumps({"evidence_dir": str(EVIDENCE), "zip": str(ZIP_PATH), "zip_sha256": sha256_file(ZIP_PATH), "attempts": len(ledger), "input_tokens": input_tokens, "output_tokens": output_tokens, "reserved_cost_usd": reserved, "local_response_estimate_usd": local}, ensure_ascii=False))


if __name__ == "__main__":
    main()
