from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mini_science.authorization import proposed_v4_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.experiment_plan import source_tree_hash


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    config = load_config(ROOT / "config" / "v4_pilot_offline.json")
    plan = pilot_request_plan(ROOT, config, worlds=["W001"], conditions=list(config.conditions), repeats=1)
    plan_path = ROOT / "reports" / "v4_preflight" / "V4_EXACT_REQUEST_PLAN.jsonl"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in plan), encoding="utf-8")
    protocol_hash = hashlib.sha256("".join(item["prompt_hash"] for item in plan).encode("ascii")).hexdigest()
    proposal = proposed_v4_authorization(ROOT, config, protocol_hash=protocol_hash)
    proposal["planned_cost_usd"] = sum(float(item["estimated_cost_usd"]) for item in plan)
    proposal["planned_request_ids"] = [item["request_id"] for item in plan]
    proposal["planned_request_count"] = len(plan)
    proposal["source_tree_sha256"] = source_tree_hash(ROOT)
    proposal["status_assertion"] = "NOT_AUTHORIZED"
    proposal_path = ROOT / "reports" / "v4_preflight" / "V4_PROPOSED_AUTHORIZATION.json"
    proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(plan_path), "proposal": str(proposal_path), "planned_calls": len(plan), "planned_cost_usd": proposal["planned_cost_usd"], "protocol_hash": protocol_hash}, ensure_ascii=False))


if __name__ == "__main__":
    main()
