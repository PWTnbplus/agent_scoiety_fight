from __future__ import annotations

from mini_science.config import load_config
from mini_science.experiment_plan import build_plan, write_plan
from mini_science.worldgen import generate_worlds


def test_plan_is_deterministic_and_shuffles_without_breaking_pair_ids(tmp_path):
    config = load_config("config/pilot_v2.json")
    generate_worlds(tmp_path, config)
    first = build_plan(tmp_path, config, run_id="same", worlds=["W001", "W002"], conditions=["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=1)
    second = build_plan(tmp_path, config, run_id="same", worlds=["W001", "W002"], conditions=["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=1)
    left = tmp_path / "left.jsonl"
    right = tmp_path / "right.jsonl"
    write_plan(left, first)
    write_plan(right, second)
    assert left.read_bytes() == right.read_bytes()
    for pair_id in {row["pair_id"] for row in first}:
        seq = [row for row in first if row["pair_id"] == pair_id and row["condition"] in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}]
        assert len([row for row in seq if row["stage"] == "stage1"]) == 1
