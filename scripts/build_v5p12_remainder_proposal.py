from __future__ import annotations

"""Freeze the six untouched V5-P11 world/repeat blocks for V5-P12."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "017_V5P12_REMAINDER_LIVE"
OLD_REPORT = ROOT / "reports" / "016_V5P11_REAL_20261113T072222Z"
OLD_RUN = ROOT / "runs" / "real_v5p11_IV001_IV004_20261113T072222Z"
OLD_SESSION = ROOT / "runs" / "real_api_sessions" / "v5p11_20261113T072254Z_4QaXzSJmGYKikoua"
WORLDS = ["IV002", "IV003", "IV004"]
CONDITIONS = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
NAMESPACE = "V5P12REM20261113"
CAP_USD = 0.25

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.authorization import proposed_v5p11_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.proposal_fingerprint import proposal_digest
from mini_science.stable_fingerprint import stable_tree_hash


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_request_id(value: Any) -> str:
    text = str(value or "")
    return text.rsplit(":attempt", 1)[0] if ":attempt" in text else text


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def history_lock() -> dict[str, Any]:
    files = [
        OLD_REPORT / "FINAL_EXECUTION_RESULT.json",
        OLD_REPORT / "FINAL_EXECUTION_RESULT_CORRECTED.json",
        OLD_REPORT / "results.csv",
        OLD_REPORT / "call_ledger.jsonl",
        OLD_REPORT / "RESTRICTED_REAL_EVIDENCE_POSTRUN_CORRECTED.zip",
        OLD_RUN / "results.csv",
        OLD_RUN / "call_ledger.jsonl",
        OLD_RUN / "events.jsonl",
        OLD_RUN / "manifest.json",
        OLD_SESSION / "attempt_ledger.jsonl",
        OLD_SESSION / "planned_requests.jsonl",
        OLD_SESSION / "gate_state.json",
        OLD_SESSION / "authorization.json",
    ]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_mutation": "NONE",
        "files": [{"path": str(path), "sha256": sha256(path), "size": path.stat().st_size} for path in files if path.is_file()],
    }


def ledger_reconciliation() -> dict[str, Any]:
    call_rows = read_jsonl(OLD_RUN / "call_ledger.jsonl")
    session_rows = read_jsonl(OLD_SESSION / "attempt_ledger.jsonl")
    call_ids = {normalize_request_id(row.get("request_id")) for row in call_rows if row.get("request_id")}
    session_started = {normalize_request_id(row.get("request_id")) for row in session_rows if row.get("status") == "STARTED" and row.get("request_id")}
    completed = {normalize_request_id(row.get("request_id")) for row in call_rows if str(row.get("request_status", "")).lower() == "completed"}
    failed = {normalize_request_id(row.get("request_id")) for row in call_rows if str(row.get("request_status", "")).lower().startswith("failed")}
    provider_models = sorted({str(row.get("returned_model")) for row in call_rows if row.get("returned_model")})
    plan_rows = read_jsonl(OLD_SESSION / "planned_requests.jsonl")
    plan_ids = {normalize_request_id(row.get("request_id")) for row in plan_rows if row.get("request_id")}
    successful_usage = sum(float(row.get("local_response_estimate_usd") or 0.0) for row in call_rows if str(row.get("request_status", "")).lower() == "completed")
    attempted_estimate = sum(float(row.get("estimated_cost_usd") or 0.0) for row in call_rows)
    return {
        "status": "PASS" if call_ids == session_started and len(plan_ids) == 40 and len(call_ids) == 10 and len(completed) == 9 and len(failed) == 1 else "FAIL",
        "call_ledger_rows": len(call_rows),
        "session_attempt_ledger_rows": len(session_rows),
        "plan_unique_ids": len(plan_ids),
        "call_unique_ids": len(call_ids),
        "session_started_unique_ids": len(session_started),
        "call_vs_session_id_difference": sorted(call_ids ^ session_started),
        "completed_unique_ids": len(completed),
        "failed_unique_ids": len(failed),
        "provider_models": provider_models,
        "automatic_retries": len(call_rows) - len(call_ids),
        "successful_usage_local_estimate_usd": successful_usage,
        "attempted_estimate_usd": attempted_estimate,
        "old_failed_request_ids": sorted(failed),
        "old_authorization_untouched": True,
    }


def main() -> int:
    if REPORT.exists():
        raise RuntimeError(f"refusing to overwrite existing report: {REPORT}")
    REPORT.mkdir(parents=True)
    config = load_config(ROOT / "config" / "v5p11_main.json")
    history = history_lock()
    reconciliation = ledger_reconciliation()
    if reconciliation["status"] != "PASS":
        raise RuntimeError(f"historical ledger reconciliation failed: {reconciliation}")
    plan = pilot_request_plan(ROOT, config, worlds=WORLDS, conditions=CONDITIONS, repeats=2, request_namespace=NAMESPACE, input_rate=0.00095, output_rate=0.004)
    if len(plan) != 30 or len({row["request_id"] for row in plan}) != 30 or sum(row["stage"] == "stage1" for row in plan) != 6:
        raise RuntimeError("V5-P12 remainder plan is not 30 unique requests with six shared Stage1 calls")
    old_ids = {normalize_request_id(row.get("request_id")) for row in read_jsonl(OLD_RUN / "call_ledger.jsonl")}
    collisions = sorted(old_ids & {normalize_request_id(row.get("request_id")) for row in plan})
    if collisions:
        raise RuntimeError(f"new request IDs collide with historical attempts: {collisions}")
    proposal = proposed_v5p11_authorization(ROOT, config, request_plan=plan, worlds=WORLDS, conditions=CONDITIONS, repeats=2, request_namespace=NAMESPACE, max_unique_provider_attempts=30, max_estimated_cost_usd=CAP_USD)
    tree_bindings = {
        "source_tree_hash": ROOT / "src",
        "tests_tree_hash": ROOT / "tests",
        "scripts_tree_hash": ROOT / "scripts",
        "public_world_tree_hash": ROOT / "data" / config.worlds_subdir,
        "private_fixture_tree_hash": ROOT / "private" / config.private_worlds_subdir,
        "docs_tree_hash": ROOT / "docs",
    }
    proposal.update({field: stable_tree_hash(path) for field, path in tree_bindings.items()})
    proposal["generated_at"] = "offline_generation_v5p12_remainder"
    proposal["proposal_sha256"] = proposal_digest(proposal)
    write_json(REPORT / "HISTORY_SHA256_BEFORE.json", history)
    write_json(REPORT / "LEDGER_RECONCILIATION.json", reconciliation)
    with (REPORT / "NEW_REQUEST_PLAN.jsonl").open("w", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in plan))
    write_json(REPORT / "NEW_FROZEN_PROPOSAL.json", proposal)
    (REPORT / "NEW_PROPOSAL_SHA256.txt").write_text(proposal["proposal_sha256"] + "\n", encoding="utf-8")
    (REPORT / "REQUEST_PLAN_SHA256.txt").write_text(proposal["request_plan_hash"] + "\n", encoding="utf-8")
    write_json(REPORT / "SOURCE_TREE_HASHES.json", {**{field: proposal[field] for field in tree_bindings}, "config_hash": proposal["frozen_config_hash"], "request_count": 30, "request_id_collisions": collisions})
    new_estimate = sum(float(row["estimated_cost_usd"]) for row in plan)
    old_estimate = float(reconciliation["attempted_estimate_usd"])
    write_json(REPORT / "AUTHORIZATION_SCOPE_DECISION.json", {
        "status": "AUTHORIZED_BY_CURRENT_USER_SCOPE_PENDING_SESSION_CREATION",
        "http_calls_allowed_before_session": False,
        "provider": "kimi26",
        "model": "kimi-k2.6",
        "worlds": WORLDS,
        "conditions": CONDITIONS,
        "repeats": 2,
        "request_count": 30,
        "stage1_request_count": 6,
        "max_estimated_cost_usd": CAP_USD,
        "new_plan_estimate_usd": new_estimate,
        "historical_attempt_estimate_usd": old_estimate,
        "cumulative_attempt_estimate_usd": old_estimate + new_estimate,
        "overall_user_budget_reference_usd": 2.0,
        "parallelism": 1,
        "auto_retry": False,
        "proposal_sha256": proposal["proposal_sha256"],
        "request_plan_hash": proposal["request_plan_hash"],
        "old_authorizations_untouched": True,
        "old_failed_request_excluded": reconciliation["old_failed_request_ids"],
    })
    (REPORT / "EXECUTION_COMMANDS.ps1").write_text("# Filled with the exact authorized command and session path by execute_v5p12_remainder.py.\n", encoding="utf-8")
    (REPORT / "README.md").write_text("""# V5-P12 remainder execution\n\nThis report adds only the six untouched IV002–IV004/R0–R1 blocks from the frozen V5-P11 design. The V5-P11 IV001 run, failed IV001/R1/D request, authorization session, and evidence package are read-only inputs. The new namespace is `V5P12REM20261113`; automatic retries are disabled.\n""", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "proposal_sha256": proposal["proposal_sha256"], "request_plan_hash": proposal["request_plan_hash"], "request_count": len(plan), "estimated_cost_usd": new_estimate, "cumulative_attempt_estimate_usd": old_estimate + new_estimate, "status": "FROZEN_NOT_AUTHORIZED"}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
