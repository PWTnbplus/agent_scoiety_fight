from __future__ import annotations

"""Freeze the V5-P13 IV002/R2-R3 follow-up without making provider calls."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "018_V5P13_SCIENCE_DIAG_AND_FINAL"
CONFIG_PATH = ROOT / "config" / "v5p11_main.json"
WORLDS = ["IV002"]
CONDITIONS = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
REPLICATES = [2, 3]
NAMESPACE = "V5P13IV002R23"
MAX_CALLS = 10
MAX_COST = 0.15

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.authorization import proposed_v5p11_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.proposal_fingerprint import proposal_digest
from mini_science.schema import sha256_json
from mini_science.stable_fingerprint import stable_tree_hash


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_id(value: Any) -> str:
    text = str(value or "")
    return text.rsplit(":attempt", 1)[0] if ":attempt" in text else text


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def historical_request_ids() -> set[str]:
    ids: set[str] = set()
    for path in sorted((ROOT / "runs").glob("real_v5p*")):
        if not path.is_dir() or "v5p13" in path.name.lower():
            continue
        ids.update(normalize_id(row.get("request_id")) for row in read_jsonl(path / "call_ledger.jsonl") if row.get("request_id"))
    for path in sorted((ROOT / "runs" / "real_api_sessions").glob("v5p11_*")):
        ids.update(normalize_id(row.get("request_id")) for row in read_jsonl(path / "planned_requests.jsonl") if row.get("request_id"))
    return {value for value in ids if value}


def main() -> int:
    config = load_config(CONFIG_PATH)
    plan = pilot_request_plan(
        ROOT,
        config,
        worlds=WORLDS,
        conditions=CONDITIONS,
        repeats=4,
        replicate_indices=REPLICATES,
        request_namespace=NAMESPACE,
        input_rate=0.00095,
        output_rate=0.004,
    )
    ids = {normalize_id(row.get("request_id")) for row in plan}
    if len(plan) != MAX_CALLS or len(ids) != MAX_CALLS:
        raise RuntimeError(f"expected {MAX_CALLS} unique requests, got {len(plan)}/{len(ids)}")
    if {int(row["replicate"]) for row in plan} != set(REPLICATES):
        raise RuntimeError("follow-up plan must contain only R2 and R3")
    pair_counts: dict[tuple[str, int], int] = {}
    for row in plan:
        pair_counts[(str(row["world_id"]), int(row["replicate"]))] = pair_counts.get((str(row["world_id"]), int(row["replicate"])), 0) + 1
    if pair_counts != {("IV002", 2): 5, ("IV002", 3): 5}:
        raise RuntimeError(f"unexpected pair structure: {pair_counts}")
    if sum(row["stage"] == "stage1" for row in plan) != 2:
        raise RuntimeError("C/D must share exactly two Stage1 requests")
    estimated = sum(float(row["estimated_cost_usd"]) for row in plan)
    if estimated > MAX_COST:
        raise RuntimeError(f"plan estimate {estimated} exceeds {MAX_COST}")
    collisions = sorted(historical_request_ids() & ids)
    if collisions:
        raise RuntimeError(f"request IDs collide with historical API attempts: {collisions}")

    proposal = proposed_v5p11_authorization(
        ROOT,
        config,
        request_plan=plan,
        worlds=WORLDS,
        conditions=CONDITIONS,
        repeats=4,
        request_namespace=NAMESPACE,
        max_unique_provider_attempts=MAX_CALLS,
        max_estimated_cost_usd=MAX_COST,
    )
    tree_bindings = {
        "source_tree_hash": ROOT / "src",
        "tests_tree_hash": ROOT / "tests",
        "scripts_tree_hash": ROOT / "scripts",
        "public_world_tree_hash": ROOT / "data" / config.worlds_subdir,
        "private_fixture_tree_hash": ROOT / "private" / config.private_worlds_subdir,
        "docs_tree_hash": ROOT / "docs",
    }
    proposal.update({field: stable_tree_hash(path) for field, path in tree_bindings.items()})
    proposal["generated_at"] = datetime.now(timezone.utc).isoformat()
    proposal["protocol_audit"] = {
        "new_namespace": NAMESPACE,
        "historical_ids_checked": len(historical_request_ids()),
        "request_id_collisions": collisions,
        "replicate_indices": REPLICATES,
        "stage1_requests": 2,
        "stage2_requests": 8,
        "parallelism": 1,
        "auto_retry": False,
        "private_truth_in_prompts": False,
    }
    proposal["proposal_sha256"] = proposal_digest(proposal)

    write_json(REPORT / "10_V5P13_NEW_FROZEN_PROPOSAL.json", proposal)
    (REPORT / "11_V5P13_REQUEST_PLAN.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in plan), encoding="utf-8")
    (REPORT / "10_V5P13_PROPOSAL_SHA256.txt").write_text(str(proposal["proposal_sha256"]) + "\n", encoding="utf-8")
    (REPORT / "11_V5P13_REQUEST_PLAN_SHA256.txt").write_text(str(proposal["request_plan_hash"]) + "\n", encoding="utf-8")
    write_json(REPORT / "10_V5P13_SCOPE_CHECK.json", {
        "status": "FROZEN_NOT_AUTHORIZED",
        "provider": proposal["provider"],
        "model": proposal["model"],
        "worlds": WORLDS,
        "conditions": CONDITIONS,
        "replicates": REPLICATES,
        "request_count": len(plan),
        "stage1_request_count": 2,
        "stage2_request_count": 8,
        "estimated_cost_usd": estimated,
        "max_estimated_cost_usd": MAX_COST,
        "request_plan_hash": proposal["request_plan_hash"],
        "proposal_sha256": proposal["proposal_sha256"],
        "request_id_collisions": collisions,
        "old_authorizations_untouched": True,
    })
    print(json.dumps({"proposal": str(REPORT / "10_V5P13_NEW_FROZEN_PROPOSAL.json"), "proposal_sha256": proposal["proposal_sha256"], "request_plan_hash": proposal["request_plan_hash"], "request_count": len(plan), "estimated_cost_usd": estimated, "status": "FROZEN_NOT_AUTHORIZED"}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
