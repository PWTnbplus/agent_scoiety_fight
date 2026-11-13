from __future__ import annotations

"""Verify a new, namespace-isolated V5-P9 five-request proposal offline."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.proposal_fingerprint import verify_proposal_digest  # noqa: E402


def historical_request_ids() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "runs").glob("**/*.jsonl"):
        if path.name not in {"call_ledger.jsonl", "attempt_ledger.jsonl"}:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            value = record.get("request_id")
            if value:
                found.add(str(value))
            values = record.get("request_ids")
            if isinstance(values, list):
                found.update(str(item) for item in values)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("proposal")
    args = parser.parse_args()
    proposal_path = (ROOT / args.proposal).resolve() if not Path(args.proposal).is_absolute() else Path(args.proposal).resolve()
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    digest = verify_proposal_digest(proposal)
    plan = proposal.get("request_plan")
    if not isinstance(plan, list) or len(plan) != 5:
        raise ValueError("proposal must contain exactly five frozen requests")
    namespace = str(proposal.get("request_namespace", ""))
    if not namespace.startswith("V5P9_"):
        raise ValueError("proposal namespace must be new V5P9_ namespace")
    expected = [
        ("A_TARGET_ONLY", "stage2", 900),
        ("B_SINGLE_RELATED", "stage2", 900),
        ("C_SEQ2_TRANSFER", "stage1", 600),
        ("C_SEQ2_TRANSFER", "stage2", 600),
        ("D_SEQ2_BLOCK", "stage2", 600),
    ]
    actual = [(str(item["condition"]), str(item["stage"]), int(item["max_output_tokens"])) for item in plan]
    if actual != expected:
        raise ValueError(f"unexpected request order/shape: {actual!r}")
    request_ids = [str(item["request_id"]) for item in plan]
    if len(set(request_ids)) != 5 or any(not item.startswith(namespace + "_") for item in request_ids):
        raise ValueError("request IDs are not unique and namespace-isolated")
    pair_ids = {str(item["pair_id"]) for item in plan}
    if pair_ids != {f"{namespace}_CV001_R0"}:
        raise ValueError("all five requests must belong to CV001/R0")
    if {str(item["stage1_shared_key"]) for item in plan} != pair_ids:
        raise ValueError("C/D do not share one Stage1 key")
    collisions = sorted(set(request_ids).intersection(historical_request_ids()))
    if collisions:
        raise ValueError(f"historical request ID collision: {collisions}")
    estimate = sum(float(item["estimated_cost_usd"]) for item in plan)
    if estimate > 0.05:
        raise ValueError(f"estimated cost exceeds authorized cap: {estimate}")
    result = {
        "status": "VERIFIED_OFFLINE",
        "proposal": str(proposal_path),
        "proposal_sha256": digest,
        "request_plan_hash": proposal.get("request_plan_hash"),
        "request_namespace": namespace,
        "request_count": 5,
        "estimated_cost_usd": estimate,
        "global_id_collision_count": 0,
        "stage1_shared_key": f"{namespace}_CV001_R0",
        "http_requests_made": 0,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
