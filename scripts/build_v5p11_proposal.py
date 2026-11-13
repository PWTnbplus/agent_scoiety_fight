from __future__ import annotations

"""Freeze the V5-P11 40-request plan and a non-authorizing proposal."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.authorization import proposed_v5p11_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.proposal_fingerprint import proposal_digest
from mini_science.stable_fingerprint import stable_tree_hash


NAMESPACE = "V5P11MAIN20261113"
WORLDS = ["IV001", "IV002", "IV003", "IV004"]
CONDITIONS = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]


def historical_request_ids() -> set[str]:
    result: set[str] = set()
    for path in ROOT.glob("runs/**/*.jsonl"):
        if path.name not in {"call_ledger.jsonl", "attempt_ledger.jsonl"}:
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if item.get("request_id"):
                        result.add(str(item["request_id"]))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return result


def main() -> int:
    config = load_config(ROOT / "config" / "v5p11_main.json")
    plan = pilot_request_plan(ROOT, config, worlds=WORLDS, conditions=CONDITIONS, repeats=2, request_namespace=NAMESPACE, input_rate=0.00095, output_rate=0.004)
    ids = [str(item["request_id"]) for item in plan]
    collisions = sorted(set(ids) & historical_request_ids())
    if len(plan) != 40 or len(set(ids)) != 40 or collisions:
        raise RuntimeError(f"V5P11 request plan invalid: count={len(plan)} unique={len(set(ids))} collisions={collisions}")
    proposal = proposed_v5p11_authorization(ROOT, config, request_plan=plan, worlds=WORLDS, conditions=CONDITIONS, repeats=2, request_namespace=NAMESPACE, max_unique_provider_attempts=40, max_estimated_cost_usd=0.40)
    tree_bindings = {
        "source_tree_hash": ROOT / "src", "tests_tree_hash": ROOT / "tests", "scripts_tree_hash": ROOT / "scripts",
        "public_world_tree_hash": ROOT / "data" / config.worlds_subdir, "private_fixture_tree_hash": ROOT / "private" / config.private_worlds_subdir, "docs_tree_hash": ROOT / "docs",
    }
    proposal.update({field: stable_tree_hash(path) for field, path in tree_bindings.items()})
    proposal["generated_at"] = "offline_generation"
    proposal["proposal_sha256"] = proposal_digest(proposal)
    report = ROOT / "reports" / "015_V5P11_PROJECT_FINISH"
    (report / "NEW_PROPOSAL.json").write_text(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (report / "NEW_PROPOSAL_SHA256.txt").write_text(proposal["proposal_sha256"] + "\n", encoding="utf-8")
    (report / "EXPERIMENT_FROZEN_CONFIG.json").write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (report / "REQUEST_PLAN.jsonl").open("w", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in plan))
    (report / "REQUEST_PLAN_SHA256.txt").write_text(proposal["request_plan_hash"] + "\n", encoding="utf-8")
    (report / "SOURCE_TREE_HASHES.json").write_text(json.dumps({**{field: proposal[field] for field in tree_bindings}, "config_hash": proposal["frozen_config_hash"], "request_count": len(plan), "request_id_collisions": collisions}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scope = {
        "status": "WAITING_FOR_EXPLICIT_NEW_SCOPE_AUTHORIZATION",
        "http_calls_allowed": False,
        "provider": "kimi26",
        "model": "kimi-k2.6",
        "worlds": WORLDS,
        "repeats": 2,
        "conditions": CONDITIONS,
        "request_count": 40,
        "stage1_request_count": 8,
        "max_estimated_cost_usd": 0.40,
        "parallelism": 1,
        "auto_retry": False,
        "proposal_sha256": proposal["proposal_sha256"],
        "request_plan_hash": proposal["request_plan_hash"],
        "required_approval": "User must explicitly name this proposal SHA and approve IV001-IV004, two repeats, A/B/C/D, kimi-k2.6, maximum 40 unique calls, USD 0.40 local estimate cap, serial execution and zero retries.",
        "legacy_authorizations_reused": False,
    }
    (report / "AUTHORIZATION_SCOPE_DECISION.json").write_text(json.dumps(scope, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"proposal": str(report / "NEW_PROPOSAL.json"), "proposal_sha256": proposal["proposal_sha256"], "request_plan_hash": proposal["request_plan_hash"], "request_count": len(plan), "estimated_cost_usd": sum(float(item["estimated_cost_usd"]) for item in plan), "request_id_collisions": collisions, "status": scope["status"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
