from __future__ import annotations

import json

import pytest

from mini_science.cli import main
from mini_science.config import load_config
from mini_science.experiment_plan import build_plan
from mini_science.public_loader import load_world
from mini_science.world_registry import resolve_worlds


def test_dv_registry_accepts_both_endpoints_and_rejects_path_traversal():
    config = load_config("config/v5p2_dev.json")
    assert resolve_worlds(".", config, "DV001,DV012") == ["DV001", "DV012"]
    with pytest.raises(ValueError, match="unknown world"):
        resolve_worlds(".", config, "DV999")
    with pytest.raises(ValueError):
        resolve_worlds(".", config, "../private")
    with pytest.raises(ValueError):
        resolve_worlds(".", config, "DV001/../../")


def test_cv_plan_contains_only_explicit_world_and_conditions_with_stable_fingerprint():
    config = load_config("config/v5p3_offline_dev.json")
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    first = build_plan(".", config, run_id="cv_plan", worlds=["CV001"], conditions=conditions, repeats=1)
    second = build_plan(".", config, run_id="cv_plan", worlds=["CV001"], conditions=conditions, repeats=1)
    assert first == second
    assert {row["world_id"] for row in first} == {"CV001"}
    assert {row["condition"] for row in first} == set(conditions)
    assert len({row["world_hash"] for row in first}) == 1
    assert len({row["pair_id"] for row in first}) == 1


def test_cli_plan_and_pilot_accept_dv_world_without_private_prompt_leak(tmp_path, monkeypatch):
    config = load_config("config/v5p2_dev.json")
    config_path = tmp_path / "config" / "v5p2_dev.json"
    config_path.parent.mkdir()
    config_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
    import shutil
    shutil.copytree("data/worlds_v5p2_dev", tmp_path / "data" / "worlds_v5p2_dev")
    shutil.copytree("private/worlds_v5p2_dev", tmp_path / "private" / "worlds_v5p2_dev")
    assert main(["plan", "--config", str(config_path), "--run-id", "dv_plan", "--worlds", "DV001", "--conditions", "A_TARGET_ONLY"]) == 0
    run_dir = tmp_path / "runs" / "dv_pilot"
    assert main(["pilot", "--config", str(config_path), "--provider", "behavioral-mock", "--worlds", "DV001", "--conditions", "A_TARGET_ONLY", "--run-dir", str(run_dir)]) == 0
    text = (run_dir / "agent_artifacts" / "DV001" / "replicate_0" / "A_TARGET_ONLY" / "final_response.json").read_text(encoding="utf-8")
    assert "true_law" not in text and "oracle_results" not in text
