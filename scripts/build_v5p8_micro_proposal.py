from __future__ import annotations

"""Freeze a new, independently hashed V5P8 CV001/R0 five-request proposal."""

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/v5p8_four_world_two_repeats.json")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--request-namespace", required=True)
    args = parser.parse_args()

    config = load_config(ROOT / args.config)
    report = (ROOT / args.report_dir).resolve()
    if report.exists():
        raise RuntimeError(f"refusing to overwrite existing report directory: {report}")
    report.mkdir(parents=True)
    plans = report / "plans"
    plans.mkdir()
    worlds = ["CV001"]
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    repeats = 1
    namespace = args.request_namespace
    if any(not namespace.startswith(prefix) for prefix in ("V5P9_",)):
        raise RuntimeError("new V5P9 proposal namespace must start with V5P9_")
    plan = pilot_request_plan(ROOT, config, worlds=worlds, conditions=conditions, repeats=repeats, request_namespace=namespace, input_rate=0.00095, output_rate=0.004)
    expected = [
        ("A_TARGET_ONLY", "stage2", 900),
        ("B_SINGLE_RELATED", "stage2", 900),
        ("C_SEQ2_TRANSFER", "stage1", 600),
        ("C_SEQ2_TRANSFER", "stage2", 600),
        ("D_SEQ2_BLOCK", "stage2", 600),
    ]
    actual = [(str(item["condition"]), str(item["stage"]), int(item["max_output_tokens"])) for item in plan]
    if len(plan) != 5 or actual != expected or len({item["request_id"] for item in plan}) != 5:
        raise RuntimeError(f"unexpected micro plan shape: {actual!r}")
    expected_stage1_key = f"{namespace}_CV001_R0"
    if {item["stage1_shared_key"] for item in plan} != {expected_stage1_key}:
        raise RuntimeError("C/D plan does not share the new namespace Stage1 key")

    historical_ids = set()
    for ledger_path in (ROOT / "runs").glob("**/*.jsonl"):
        if ledger_path.name not in {"call_ledger.jsonl", "attempt_ledger.jsonl"}:
            continue
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key in ("request_id", "request_ids"):
                value = record.get(key)
                if isinstance(value, list):
                    historical_ids.update(str(item) for item in value)
                elif value:
                    historical_ids.add(str(value))
    collisions = sorted(historical_ids.intersection(str(item["request_id"]) for item in plan))
    if collisions:
        raise RuntimeError(f"new proposal request IDs collide with historical ledgers: {collisions}")

    proposal = proposed_v5p8_authorization(
        ROOT,
        config,
        request_plan=plan,
        worlds=worlds,
        conditions=conditions,
        repeats=repeats,
        request_namespace=namespace,
        max_unique_provider_attempts=5,
        max_estimated_cost_usd=0.05,
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
    proposal["generated_at"] = "offline_generation"
    proposal["proposal_sha256"] = proposal_digest(proposal)

    (plans / "config_freeze.json").write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (plans / "five_request_plan.jsonl").open("w", encoding="utf-8") as handle:
        for item in plan:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    with (plans / "five_request_plan.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(plan[0]))
        writer.writeheader()
        writer.writerows(plan)
    (plans / "API_AUTHORIZATION_PROPOSAL.json").write_text(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (plans / "proposal_hashes.json").write_text(json.dumps({
        "proposal_sha256": proposal["proposal_sha256"],
        "request_plan_hash": proposal["request_plan_hash"],
        "config_hash": proposal["frozen_config_hash"],
        "request_count": len(plan),
        "estimated_cost_usd": sum(float(item["estimated_cost_usd"]) for item in plan),
        "old_40_request_proposal_sha256": "378435fd9d458c6cccae898894fc3c9724340eec1c9d76d0223b199669749a45",
        "request_namespace": namespace,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "proposal": str(plans / "API_AUTHORIZATION_PROPOSAL.json"),
        "proposal_sha256": proposal["proposal_sha256"],
        "request_plan": str(plans / "five_request_plan.jsonl"),
        "request_plan_hash": proposal["request_plan_hash"],
        "request_count": len(plan),
        "estimated_cost_usd": sum(float(item["estimated_cost_usd"]) for item in plan),
        "status": "PROPOSED_NOT_AUTHORIZED",
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
