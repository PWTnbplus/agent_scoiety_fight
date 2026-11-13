from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from mini_science.authorization import proposed_v5p4_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.schema import sha256_json


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "005_V5P4_READY_FOR_AUTH"


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted((entry for entry in path.rglob("*") if entry.is_file()), key=lambda value: value.relative_to(path).as_posix()):
        if item.suffix in {".pyc", ".key"}:
            continue
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(item.read_bytes()).hexdigest().encode("ascii"))
    return digest.hexdigest()


def main() -> None:
    config = load_config(ROOT / "config" / "v5p4_offline_dev.json")
    plan = pilot_request_plan(ROOT, config, worlds=["CV001"], conditions=list(config.conditions), repeats=1, input_rate=0.00095, output_rate=0.004)
    proposal = proposed_v5p4_authorization(ROOT, config, request_plan=plan)
    proposal["source_tree_hash"] = tree_hash(ROOT / "src")
    proposal["scripts_tree_hash"] = tree_hash(ROOT / "scripts")
    proposal["public_world_tree_hash"] = tree_hash(ROOT / "data" / "worlds_v5p4_dev")
    proposal["private_fixture_tree_hash"] = tree_hash(ROOT / "private" / "worlds_v5p4_dev")
    proposal["generated_at"] = "offline_generation"
    proposal["proposal_sha256"] = sha256_json({key: value for key, value in proposal.items() if key != "proposal_sha256"})
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "API_AUTHORIZATION_PROPOSAL.json").write_text(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (REPORT / "BUDGET_PLAN.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(plan[0]))
        writer.writeheader()
        writer.writerows(plan)
    with (REPORT / "experiment_run_plan.jsonl").open("w", encoding="utf-8") as handle:
        for item in plan:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    (REPORT / "prompt_hashes.json").write_text(json.dumps({item["request_id"]: item["prompt_hash"] for item in plan}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    preflight = {
        "session_protocol": "v5p4",
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "http_calls_allowed": False,
        "real_api_calls_this_round": 0,
        "provider": "kimi26",
        "model": "kimi-k2.6",
        "worlds": ["CV001"],
        "conditions": list(config.conditions),
        "request_count": len(plan),
        "estimated_cost_usd": sum(float(item["estimated_cost_usd"]) for item in plan),
        "max_estimated_cost_usd": 0.05,
        "parallelism": 1,
        "auto_retry": False,
        "request_plan_hash": proposal["request_plan_hash"],
        "frozen_config_hash": proposal["frozen_config_hash"],
        "source_tree_hash": proposal["source_tree_hash"],
        "required_future_authorization": "new explicit user approval naming this proposal hash and scope",
        "legacy_authorizations_reused": False,
    }
    (REPORT / "session_preflight.json").write_text(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"proposal": str(REPORT / "API_AUTHORIZATION_PROPOSAL.json"), "request_plan_hash": proposal["request_plan_hash"], "estimated_cost_usd": preflight["estimated_cost_usd"], "status": proposal["authorization_status"]}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
