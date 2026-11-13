from __future__ import annotations

import json

from mini_science.config import load_config
from mini_science.prompts import single_messages
from mini_science.public_loader import load_world
from mini_science.worldgen import generate_worlds


def test_private_sentinel_never_enters_prompt(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    truth_path = tmp_path / "private" / "worlds" / "W001" / "hidden_truth.json"
    truth = json.loads(truth_path.read_text())
    truth["sentinel"] = "SENTINEL_SECRET_DO_NOT_LEAK"
    truth_path.write_text(json.dumps(truth))
    view = load_world(tmp_path, "W001", "related")
    prompt_text = json.dumps(single_messages(view, "B_SINGLE_RELATED"), ensure_ascii=False)
    assert "SENTINEL_SECRET_DO_NOT_LEAK" not in prompt_text
    assert "oracle_results" not in prompt_text
    assert "source_related.md" not in prompt_text
