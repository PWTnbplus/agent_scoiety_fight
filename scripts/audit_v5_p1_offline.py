from __future__ import annotations

"""P1-A offline-only audit; this script never constructs a network adapter."""

import hashlib
import json
from pathlib import Path
import zipfile

from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.evidence_policy import policy_for_route
from mini_science.experiment_plan import source_tree_hash
from mini_science.prompts import seq2_stage1_messages, seq2_stage2_messages, single_messages
from mini_science.public_loader import load_world
from mini_science.router import route_shared_law_artifact
from mini_science.schema import sha256_json
from mini_science.worldgen import validate_worlds


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "002_V5_P1_OFFLINE_RECHECK"
EXPECTED_SOURCE = "af07c0d8b5f6b23926344050ce4105cea4be06f9e674b093655577b483d3545b"
EXPECTED_CONFIG = "2aebcfff8f84e9a5e9bd35c3045008ae584e575838640eb59fff8cdbb8625430"
EXPECTED_PROTOCOL = "6213de5248894990ea73f371a7a4e8694671e004763230309e2b3a8b1ab76701"
FORBIDDEN_PROMPT_MARKERS = ("hidden_truth", "oracle_results", "best_experiment_ids", "ig_star", "true_law")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_config(ROOT / "config" / "v4_pilot_offline.json")
    expected = pilot_request_plan(ROOT, config, worlds=["W001"], conditions=list(config.conditions), repeats=1)
    saved_path = ROOT / "reports" / "v4_preflight" / "V4_EXACT_REQUEST_PLAN.jsonl"
    saved = [json.loads(line) for line in saved_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_ids = [row["request_id"] for row in expected]
    saved_ids = [row["request_id"] for row in saved]
    generated_prompts: dict[str, list[dict[str, str]]] = {}
    for row in expected:
        view = load_world(ROOT, row["world_id"], "irrelevant" if row["condition"] == "A_TARGET_ONLY" else "related", worlds_subdir=config.worlds_subdir)
        if row["agent_name"] == "single_question_designer":
            generated_prompts[row["request_id"]] = single_messages(view, row["condition"])
        elif row["stage"] == "stage1":
            generated_prompts[row["request_id"]] = seq2_stage1_messages(view)
        elif row["condition"] == "C_SEQ2_TRANSFER":
            artifact = {"shared_law_judgment": "unknown", "candidate_law_id": "UNKNOWN", "hypothesized_shared_law": "x" * 120, "source_evidence_ids": ["S01", "S02"], "target_evidence_ids": ["T01", "T02"], "variable_mapping": {"source_state": "target_state", "source_time": "target_time"}, "status": "supported_or_uncertain", "brief_justification": "x" * 120}
            generated_prompts[row["request_id"]] = seq2_stage2_messages(view, route_shared_law_artifact(artifact, True)["artifact"], row["condition"])
        else:
            generated_prompts[row["request_id"]] = seq2_stage2_messages(view, route_shared_law_artifact({}, False)["artifact"], row["condition"])
    prompt_hash_match = all(sha256_json(generated_prompts[row["request_id"]]) == row["prompt_hash"] for row in saved) and saved_ids == expected_ids
    prompt_text = json.dumps(generated_prompts, ensure_ascii=False, sort_keys=True)
    prompt_leak_markers = [marker for marker in FORBIDDEN_PROMPT_MARKERS if marker in prompt_text]
    artifact = {"shared_law_judgment": "same", "candidate_law_id": "EXP_DECAY", "hypothesized_shared_law": "decay", "source_evidence_ids": ["S01"], "target_evidence_ids": ["T01"], "variable_mapping": {"source_state": "target_state"}, "status": "hypothesis", "brief_justification": "evidence"}
    c_route = route_shared_law_artifact(artifact, True)
    d_route = route_shared_law_artifact(artifact, False)
    routing = {
        "stage1_hash_equal": c_route["stage1_artifact_sha256"] == d_route["stage1_artifact_sha256"],
        "route_hashes_differ": c_route["forwarded_artifact_sha256"] != d_route["forwarded_artifact_sha256"],
        "d_source_evidence_ids": d_route["artifact"].get("source_evidence_ids"),
        "d_target_evidence_ids": d_route["artifact"].get("target_evidence_ids"),
        "d_variable_mapping": d_route["artifact"].get("variable_mapping"),
        "d_contains_stage1_content": any(value not in (None, [], {}, "UNKNOWN", "unknown", "not_available") for key, value in d_route["artifact"].items() if key in {"candidate_law_id", "source_evidence_ids", "target_evidence_ids", "variable_mapping"}),
    }
    kimi_text = (ROOT / "src" / "mini_science" / "adapters" / "kimi26.py").read_text(encoding="utf-8")
    runner_text = (ROOT / "src" / "mini_science" / "runner.py").read_text(encoding="utf-8")
    provider_contract = {
        "https_default": "https://token.ctflow.cn/v1" in kimi_text,
        "frozen_model": 'DEFAULT_MODEL_ID = "kimi-k2.6"' in kimi_text,
        "runtime_key_read": "def _read_key" in kimi_text and "read_text" in kimi_text,
        "redirect_blocked": "class NoRedirect" in kimi_text,
        "zero_retry": '"retry_count": 0' in kimi_text,
        "runner_identity_usage_truncation_gate": all(marker in runner_text for marker in ("MODEL_ID_UNVERIFIED_OR_MISMATCH", "USAGE_UNVERIFIED", "TRUNCATED_OUTPUT")),
    }
    package_path = ROOT / "v5_p0_pre_paid_evidence_complete3.zip"
    required_package_entries = {"src/mini_science/adapters/kimi26.py", "tests/test_v4_preflight.py", "scripts/audit_v4_real_pre_gate.py", "reports/v4_real_pre_gate/FINAL_PRE_PAID_CHECK.md", "reports/v4_real_pre_gate/V5_GO_NO_GO.json"}
    with zipfile.ZipFile(package_path) as archive:
        package_entries = set(archive.namelist())
    package_index = (ROOT / "reports" / "v4_real_pre_gate" / "EVIDENCE_PACKAGE_INDEX.md").read_text(encoding="utf-8")
    package_audit = {"package_exists": package_path.exists(), "required_entries_present": required_package_entries.issubset(package_entries), "missing_entries": sorted(required_package_entries - package_entries), "index_mentions_source_tests_scripts": all(value in package_index for value in ("src/", "tests/", "scripts/"))}
    package_ok = bool(package_audit["package_exists"] and package_audit["required_entries_present"] and not package_audit["missing_entries"] and package_audit["index_mentions_source_tests_scripts"])
    world = validate_worlds(ROOT, config)
    plan_cost = sum(float(row["estimated_cost_usd"]) for row in saved)
    protocol_hash = hashlib.sha256("".join(row["prompt_hash"] for row in saved).encode("ascii")).hexdigest()
    proposal = json.loads((ROOT / "reports" / "v4_preflight" / "V4_PROPOSED_AUTHORIZATION.json").read_text(encoding="utf-8"))
    immutable = json.loads((ROOT / "reports" / "v4_preflight" / "V3_IMMUTABLE_CHECK.json").read_text(encoding="utf-8"))
    result = {
        "status": "PASS",
        "paid_api_calls_in_p1_a": 0,
        "tests_report": (OUT / "PYTEST.txt").read_text(encoding="utf-8").strip(),
        "source_tree_sha256": source_tree_hash(ROOT),
        "config_sha256": __import__("mini_science.authorization", fromlist=["config_digest"]).config_digest(config),
        "protocol_sha256": protocol_hash,
        "expected_hashes_match": source_tree_hash(ROOT) == EXPECTED_SOURCE and __import__("mini_science.authorization", fromlist=["config_digest"]).config_digest(config) == EXPECTED_CONFIG and protocol_hash == EXPECTED_PROTOCOL,
        "plan": {"saved_ids": saved_ids, "expected_ids": expected_ids, "unique_ids": len(saved_ids) == len(set(saved_ids)), "prompt_hash_match": prompt_hash_match, "output_caps": [row["max_output_tokens"] for row in saved], "planned_cost_usd": plan_cost},
        "prompt_leakage": {"forbidden_markers": FORBIDDEN_PROMPT_MARKERS, "detected_markers": prompt_leak_markers, "public_menu_e03_is_not_oracle_annotation": True},
        "routing": routing,
        "provider_contract": provider_contract,
        "package_audit": package_audit,
        "world_validation": world,
        "historical_immutable": immutable,
        "authorization": {"status": proposal.get("authorization_status"), "approved_by": proposal.get("approved_by"), "session_dir_exists": (ROOT / "runs" / "real_api_sessions").exists()},
        "budget_scope_conflict": {"guide_cap_usd": 0.05, "user_message_cap_usd": 5.0, "action": "STOP_BEFORE_AUTHORIZATION_UNTIL_EXACT_CAP_IS_RESOLVED"},
    }
    if not (result["expected_hashes_match"] and result["plan"]["unique_ids"] and result["plan"]["prompt_hash_match"] and not prompt_leak_markers and routing["stage1_hash_equal"] and routing["route_hashes_differ"] and routing["d_source_evidence_ids"] == [] and not routing["d_contains_stage1_content"] and all(provider_contract.values()) and package_ok and immutable.get("status") == "PASS" and not result["authorization"]["session_dir_exists"]):
        result["status"] = "STOP"
    (OUT / "P1_OFFLINE_AUDIT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "plan_cost_usd": plan_cost, "prompt_leak_markers": prompt_leak_markers, "package_ok": package_ok, "session_dir_exists": result["authorization"]["session_dir_exists"]}, ensure_ascii=False))
    if result["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
