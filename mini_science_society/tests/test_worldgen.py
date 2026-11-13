from __future__ import annotations

import json

from mini_science.config import load_config
from mini_science.worldgen import generate_worlds, validate_worlds


def test_worlds_have_public_private_split_and_eight_actions(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    reports = validate_worlds(tmp_path, config)
    assert len(reports) == 4
    for report in reports:
        world = tmp_path / "data" / "worlds" / report["world_id"]
        private = tmp_path / "private" / "worlds" / report["world_id"]
        assert len(json.loads((world / "candidate_experiments.json").read_text())["experiments"]) == 8
        assert (private / "hidden_truth.json").exists()
        assert not (world / "hidden_truth.json").exists()
