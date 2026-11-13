from __future__ import annotations

"""Freeze an additive V5-P15 request cohort without making provider calls."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "020_V5P15_RESEARCH_20261114"
CONFIG_PATH = ROOT / "config" / "v5p15_research.json"
CONDITIONS = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.authorization import proposed_v5p11_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.proposal_fingerprint import proposal_digest
from mini_science.stable_fingerprint import stable_tree_hash


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_id(value: Any) -> str:
    text = str(value or "")
    return text.rsplit(":attempt", 1)[0] if ":attempt" in text else text


def historical_request_ids() -> set[str]:
    ids: set[str] = set()
    for path in sorted((ROOT / "runs").glob("real_v5p*")):
        if path.is_dir():
            ids.update(normalize_id(row.get("request_id")) for row in read_jsonl(path / "call_ledger.jsonl") if row.get("request_id"))
    for path in sorted((ROOT / "runs" / "real_api_sessions").glob("v5p11_*")):
        ids.update(normalize_id(row.get("request_id")) for row in read_jsonl(path / "planned_requests.jsonl") if row.get("request_id"))
    return {value for value in ids if value}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scope_for(cohort: str) -> tuple[list[str], list[int], str, int, float]:
    if cohort == "validation":
        return ["RS001"], [0], "V5P15VAL20261114", 5, 0.10
    if cohort == "core":
        return [f"RS{index:03d}" for index in range(1, 9)], list(range(5)), "V5P15CORE20261114", 200, 2.00
    raise ValueError("cohort must be validation or core")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", choices=("validation", "core"), required=True)
    args = parser.parse_args()
    config = load_config(CONFIG_PATH)
    worlds, replicates, namespace, max_calls, max_cost = scope_for(args.cohort)
    plan = pilot_request_plan(
        ROOT,
        config,
        worlds=worlds,
        conditions=CONDITIONS,
        repeats=config.repeats,
        replicate_indices=replicates,
        request_namespace=namespace,
        input_rate=0.00095,
        output_rate=0.004,
    )
    ids = {normalize_id(row.get("request_id")) for row in plan}
    if len(plan) != max_calls or len(ids) != max_calls:
        raise RuntimeError(f"{args.cohort} expected {max_calls} unique requests, got {len(plan)}/{len(ids)}")
    collisions = sorted(historical_request_ids() & ids)
    if collisions:
        raise RuntimeError(f"request IDs collide with historical API attempts: {collisions}")
    pair_counts: dict[tuple[str, int], int] = {}
    for row in plan:
        pair = (str(row["world_id"]), int(row["replicate"]))
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
    expected_pairs = {(world, replicate): 5 for world in worlds for replicate in replicates}
    if pair_counts != expected_pairs:
        raise RuntimeError(f"unexpected pair structure: {pair_counts}")
    if sum(row["stage"] == "stage1" for row in plan) != len(expected_pairs):
        raise RuntimeError("each A/B/C/D pair must contain exactly one shared Stage1 request")
    estimated = float(sum(float(row["estimated_cost_usd"]) for row in plan))
    if estimated > max_cost:
        raise RuntimeError(f"plan estimate {estimated} exceeds session cap {max_cost}")

    proposal = proposed_v5p11_authorization(
        ROOT,
        config,
        request_plan=plan,
        worlds=worlds,
        conditions=CONDITIONS,
        repeats=config.repeats,
        request_namespace=namespace,
        max_unique_provider_attempts=max_calls,
        max_estimated_cost_usd=max_cost,
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
    proposal["cohort"] = args.cohort
    proposal["cumulative_budget_usd"] = 10.0
    proposal["protocol_audit"] = {
        "new_namespace": namespace,
        "historical_ids_checked": len(historical_request_ids()),
        "request_id_collisions": collisions,
        "replicate_indices": replicates,
        "pair_counts": {f"{world}/R{replicate}": count for (world, replicate), count in sorted(pair_counts.items())},
        "stage1_requests": len(expected_pairs),
        "stage2_requests": max_calls - len(expected_pairs),
        "parallelism": 1,
        "auto_retry": False,
        "private_truth_in_prompts": False,
        "old_authorizations_untouched": True,
    }
    proposal["proposal_sha256"] = proposal_digest(proposal)
    prefix = f"V5P15_{args.cohort.upper()}"
    proposal_path = REPORT / f"{prefix}_PROPOSAL.json"
    plan_path = REPORT / f"{prefix}_REQUEST_PLAN.jsonl"
    write_json(proposal_path, proposal)
    plan_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in plan), encoding="utf-8")
    (REPORT / f"{prefix}_PROPOSAL_SHA256.txt").write_text(proposal["proposal_sha256"] + "\n", encoding="utf-8")
    (REPORT / f"{prefix}_REQUEST_PLAN_SHA256.txt").write_text(proposal["request_plan_hash"] + "\n", encoding="utf-8")
    write_json(REPORT / f"{prefix}_SCOPE_CHECK.json", {
        "status": "FROZEN_NOT_AUTHORIZED",
        "cohort": args.cohort,
        "provider": proposal["provider"],
        "model": proposal["model"],
        "worlds": worlds,
        "conditions": CONDITIONS,
        "replicates": replicates,
        "request_count": len(plan),
        "stage1_request_count": len(expected_pairs),
        "stage2_request_count": max_calls - len(expected_pairs),
        "estimated_cost_usd": estimated,
        "max_estimated_cost_usd": max_cost,
        "request_plan_hash": proposal["request_plan_hash"],
        "proposal_sha256": proposal["proposal_sha256"],
        "request_id_collisions": collisions,
        "old_authorizations_untouched": True,
    })
    print(json.dumps({"proposal": str(proposal_path), "proposal_sha256": proposal["proposal_sha256"], "request_plan_hash": proposal["request_plan_hash"], "request_count": len(plan), "estimated_cost_usd": estimated, "status": "FROZEN_NOT_AUTHORIZED"}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
