from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.proposal_fingerprint import verify_proposal_digest


def main() -> int:
    report = ROOT / "reports" / "015_V5P11_PROJECT_FINISH"
    proposal = json.loads((report / "NEW_PROPOSAL.json").read_text(encoding="utf-8"))
    plan = [json.loads(line) for line in (report / "REQUEST_PLAN.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    digest = verify_proposal_digest(proposal)
    ids = [str(item["request_id"]) for item in plan]
    pairs = {}
    for item in plan:
        pairs.setdefault((item["world_id"], int(item["replicate"])), []).append(item)
    assert digest == (report / "NEW_PROPOSAL_SHA256.txt").read_text(encoding="utf-8").strip()
    assert len(plan) == len(set(ids)) == 40
    assert len(pairs) == 8 and all(len(items) == 5 for items in pairs.values())
    assert sum(item["stage"] == "stage1" for item in plan) == 8
    assert proposal["request_plan_hash"] == (report / "REQUEST_PLAN_SHA256.txt").read_text(encoding="utf-8").strip()
    assert proposal["authorization_status"] == "PROPOSED_NOT_AUTHORIZED"
    print(json.dumps({"proposal_sha256": digest, "request_plan_hash": proposal["request_plan_hash"], "request_count": len(plan), "pair_count": len(pairs), "stage1_count": sum(item["stage"] == "stage1" for item in plan), "authorization_status": proposal["authorization_status"], "http_calls_allowed": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
