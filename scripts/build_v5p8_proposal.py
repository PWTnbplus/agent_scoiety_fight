from __future__ import annotations

"""Freeze the offline V5P8 40-request plan and a non-authorizing proposal."""

import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.authorization import proposed_v5p8_authorization  # noqa: E402
from mini_science.budget_plan import pilot_request_plan  # noqa: E402
from mini_science.config import load_config  # noqa: E402
from mini_science.proposal_fingerprint import proposal_digest  # noqa: E402
from mini_science.stable_fingerprint import stable_tree_hash  # noqa: E402


def historical_request_ids() -> set[str]:
    ids: set[str] = set()
    for path in ROOT.glob("runs/**/*.jsonl"):
        # Offline frozen plans are proposals, not historical provider ledgers.
        # Only ledger-like files can make a future request ID unsafe to reuse.
        if path.name not in {"call_ledger.jsonl", "attempt_ledger.jsonl"}:
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    value = json.loads(line)
                    if value.get("request_id"):
                        ids.add(str(value["request_id"]))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return ids


def main() -> int:
    config = load_config(ROOT / "config" / "v5p8_four_world_two_repeats.json")
    worlds = ["CV001", "CV002", "CV003", "CV004"]
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    plan = pilot_request_plan(ROOT, config, worlds=worlds, conditions=conditions, repeats=2, input_rate=0.00095, output_rate=0.004)
    request_ids = [str(item["request_id"]) for item in plan]
    old_ids = historical_request_ids()
    collisions = sorted(set(request_ids) & old_ids)
    if len(plan) != 40 or len(set(request_ids)) != 40:
        raise RuntimeError("V5P8 plan must contain exactly 40 unique requests")
    if collisions:
        raise RuntimeError(f"V5P8 request IDs collide with historical ledgers: {collisions}")
    proposal = proposed_v5p8_authorization(ROOT, config, request_plan=plan, worlds=worlds, conditions=conditions, max_unique_provider_attempts=40, max_estimated_cost_usd=0.40)
    tree_bindings = {
        "source_tree_hash": ROOT / "src",
        "tests_tree_hash": ROOT / "tests",
        "scripts_tree_hash": ROOT / "scripts",
        "public_world_tree_hash": ROOT / "data" / config.worlds_subdir,
        "private_fixture_tree_hash": ROOT / "private" / config.private_worlds_subdir,
        "docs_tree_hash": ROOT / "docs",
    }
    proposal.update({field: stable_tree_hash(path) for field, path in tree_bindings.items()})
    proposal["generated_at"] = "offline_generation"
    proposal["proposal_sha256"] = proposal_digest(proposal)
    report = ROOT / "reports" / "011_V5P8_HANDOFF_EXECUTION"
    plans = report / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "config_freeze.json").write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (plans / "40_request_plan.jsonl").open("w", encoding="utf-8") as handle:
        for item in plan:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    (plans / "API_AUTHORIZATION_PROPOSAL.json").write_text(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (plans / "proposal_hashes.json").write_text(json.dumps({"proposal_sha256": proposal["proposal_sha256"], "request_plan_hash": proposal["request_plan_hash"], "config_hash": proposal["frozen_config_hash"], "request_count": len(plan), "request_id_collisions": collisions}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (plans / "40_request_plan.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = list(plan[0])
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(plan)
    preflight = {
        "version": "V5P8",
        "session_protocol": "v5p8",
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "http_calls_allowed": False,
        "provider": "kimi26",
        "model": "kimi-k2.6",
        "worlds": worlds,
        "repeats_per_world": 2,
        "conditions": conditions,
        "request_count": len(plan),
        "stage1_request_count": sum(item["stage"] == "stage1" for item in plan),
        "estimated_cost_usd": sum(float(item["estimated_cost_usd"]) for item in plan),
        "max_estimated_cost_usd": 0.40,
        "max_unique_provider_attempts": 40,
        "parallelism": 1,
        "auto_retry": False,
        "request_plan_hash": proposal["request_plan_hash"],
        "proposal_sha256": proposal["proposal_sha256"],
        "config_hash": proposal["frozen_config_hash"],
        "required_future_authorization": "new explicit user approval naming the proposal SHA, 40 requests, four worlds, two repeats, kimi-k2.6, and the local-estimate cap",
        "legacy_authorizations_reused": False,
    }
    (plans / "authorization_preflight.json").write_text(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"proposal": str(plans / "API_AUTHORIZATION_PROPOSAL.json"), "proposal_sha256": proposal["proposal_sha256"], "request_plan_hash": proposal["request_plan_hash"], "request_count": len(plan), "estimated_cost_usd": preflight["estimated_cost_usd"], "status": "PROPOSED_NOT_AUTHORIZED"}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
