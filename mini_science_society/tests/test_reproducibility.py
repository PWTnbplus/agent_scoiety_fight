from __future__ import annotations

from mini_science.config import load_config
from mini_science.worldgen import generate_worlds


def test_same_seed_reproduces_public_bytes(tmp_path):
    config = load_config("config/pilot.json")
    left = tmp_path / "left"
    right = tmp_path / "right"
    generate_worlds(left, config)
    generate_worlds(right, config)
    for world_id in ("W001", "W002", "W003", "W004"):
        for name in ("manifest.json", "target_notes.md", "source_related.md", "source_irrelevant.md", "candidate_experiments.json"):
            assert (left / "data" / "worlds" / world_id / name).read_bytes() == (right / "data" / "worlds" / world_id / name).read_bytes()
