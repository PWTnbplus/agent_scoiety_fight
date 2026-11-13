from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys

from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.experiment_plan import source_tree_hash
from mini_science.worldgen import validate_worlds


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "v4_real_pre_gate"


def tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file() and "__pycache__" not in item.parts:
            child = hashlib.sha256(item.read_bytes()).hexdigest()
            digest.update(str(item.relative_to(path)).replace("\\", "/").encode("utf-8"))
            digest.update(child.encode("ascii"))
    return digest.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_config(ROOT / "config" / "v4_pilot_offline.json")
    expected_plan = pilot_request_plan(ROOT, config, worlds=["W001"], conditions=list(config.conditions), repeats=1)
    saved_plan_path = ROOT / "reports" / "v4_preflight" / "V4_EXACT_REQUEST_PLAN.jsonl"
    saved_plan = [json.loads(line) for line in saved_plan_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    plan_match = saved_plan == expected_plan
    plan_audit = {
        "status": "PASS" if plan_match else "FAIL",
        "saved_request_ids": [item["request_id"] for item in saved_plan],
        "expected_request_ids": [item["request_id"] for item in expected_plan],
        "unique_request_ids": len({item["request_id"] for item in saved_plan}) == len(saved_plan),
        "prompt_hash_match": all(saved.get("prompt_hash") == expected.get("prompt_hash") for saved, expected in zip(saved_plan, expected_plan)) and len(saved_plan) == len(expected_plan),
        "cost_match": sum(float(item["estimated_cost_usd"]) for item in saved_plan) == sum(float(item["estimated_cost_usd"]) for item in expected_plan),
        "planned_cost_usd": sum(float(item["estimated_cost_usd"]) for item in saved_plan),
        "max_output_tokens": [item["max_output_tokens"] for item in saved_plan],
        "config_hash": __import__("mini_science.authorization", fromlist=["config_digest"]).config_digest(config),
        "source_tree_sha256": source_tree_hash(ROOT),
    }
    (OUT / "REQUEST_PLAN_AUDIT.json").write_text(json.dumps(plan_audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "UPDATED_EXACT_REQUEST_PLAN.jsonl").write_text(saved_plan_path.read_text(encoding="utf-8"), encoding="utf-8")
    world_result = validate_worlds(ROOT, config)
    world_ok = len(world_result) == 1 and world_result[0].get("world_id") == "W001" and world_result[0].get("menu_size") == 8 and world_result[0].get("best_experiment_ids") == ["E03"] and abs(float(world_result[0].get("ig_star", 0.0)) - 0.6164553635141672) < 1e-12
    immutable = json.loads((ROOT / "reports" / "v4_preflight" / "V3_IMMUTABLE_CHECK.json").read_text(encoding="utf-8"))
    proposal = json.loads((ROOT / "reports" / "v4_preflight" / "V4_PROPOSED_AUTHORIZATION.json").read_text(encoding="utf-8"))
    pytest_text = (OUT / "PYTEST.txt").read_text(encoding="utf-8") if (OUT / "PYTEST.txt").exists() else ""
    pytest_ok = "passed" in pytest_text and "failed" not in pytest_text
    session_dir = ROOT / "runs" / "real_api_sessions"
    gate = {
        "gate_version": "v5-p0-real-pre-gate-1",
        "status": "PASS" if all([plan_match, plan_audit["unique_request_ids"], plan_audit["prompt_hash_match"], plan_audit["cost_match"], plan_audit["planned_cost_usd"] <= 0.05, world_ok, immutable.get("status") == "PASS", proposal.get("authorization_status") == "PROPOSED_NOT_AUTHORIZED", proposal.get("approved_by") is None, not session_dir.exists(), pytest_ok]) else "STOP",
        "real_api_called_by_gate": False,
        "python": sys.version,
        "platform": platform.platform(),
        "pytest_output": str(OUT / "PYTEST.txt"),
        "pytest_ok": pytest_ok,
        "historical_immutable_check": immutable,
        "world_validation": world_result,
        "world_validation_expected": {"world_id": "W001", "menu_size": 8, "best_experiment_ids": ["E03"], "ig_star": 0.6164553635141672},
        "request_plan_audit": plan_audit,
        "authorization_status": proposal.get("authorization_status"),
        "approved_by": proposal.get("approved_by"),
        "v4_session_dir_exists": session_dir.exists(),
        "old_v3_files_must_remain_read_only": True,
    }
    (OUT / "GATE_0_FINAL.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": gate["status"], "plan_cost": plan_audit["planned_cost_usd"], "session_dir_exists": session_dir.exists()}, ensure_ascii=False))
    if gate["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
