from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_science.authorization import proposed_v5p11_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config


def test_v5p15_config_freezes_eight_worlds_and_balanced_conditions():
    config = json.loads((ROOT / "config" / "v5p15_research.json").read_text(encoding="utf-8"))
    assert config["num_worlds"] == 8
    assert config["repeats"] == 5
    assert config["allowed_worlds"] == [f"RS{index:03d}" for index in range(1, 9)]
    assert config["conditions"] == ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    assert "E_SEQ2_IRRELEVANT_TRANSFER" in config["allowed_conditions"]
    assert "S_COLLAB3" in config["allowed_conditions"]
    assert "S_COMPETE3" in config["allowed_conditions"]


def test_v5p15_worlds_keep_public_private_separation():
    public_root = ROOT / "data" / "worlds_v5p15_research"
    private_root = ROOT / "private" / "worlds_v5p15_research"
    world_ids = [f"RS{index:03d}" for index in range(1, 9)]
    for world_id in world_ids:
        public = public_root / world_id
        private = private_root / world_id
        assert {path.name for path in public.iterdir() if path.is_file()} == {
            "manifest.json", "candidate_experiments.json", "target_notes.md", "source_related.md", "source_irrelevant.md"
        }
        assert {path.name for path in private.iterdir() if path.is_file()} == {"hidden_truth.json", "oracle_results.json"}
        public_text = "\n".join(path.read_text(encoding="utf-8") for path in public.iterdir() if path.is_file())
        assert "hidden_truth" not in public_text
        assert "oracle_results" not in public_text
        assert "true_law" not in public_text


def test_v5p15_validation_plan_and_authorization_are_frozen_without_http():
    config = load_config(ROOT / "config" / "v5p15_research.json")
    plan = pilot_request_plan(ROOT, config, worlds=["RS001"], conditions=list(config.conditions), repeats=5, replicate_indices=[0], request_namespace="V5P15TEST20261114")
    assert len(plan) == 5
    assert sum(row["stage"] == "stage1" for row in plan) == 1
    proposal = proposed_v5p11_authorization(ROOT, config, request_plan=plan, worlds=["RS001"], conditions=list(config.conditions), repeats=5, request_namespace="V5P15TEST20261114", max_unique_provider_attempts=5, max_estimated_cost_usd=0.1)
    assert proposal["protocol_variant"] == "v5p15_research"
    assert proposal["request_ids"] == [row["request_id"] for row in plan]


def test_v5p15_three_agent_budget_plan_has_unique_provider_calls():
    config = load_config(ROOT / "config" / "v5p15_research.json")
    plan = pilot_request_plan(ROOT, config, worlds=["RS001"], conditions=["S_COLLAB3", "S_COMPETE3"], repeats=5, replicate_indices=[0], request_namespace="V5P15SOCIETY20261114")
    assert len(plan) == 6
    assert len({row["request_id"] for row in plan}) == 6
    assert {row["agent_name"] for row in plan} == {"source_analyst", "target_analyst", "synthesis_designer", "proposer_1", "proposer_2", "evidence_judge"}
