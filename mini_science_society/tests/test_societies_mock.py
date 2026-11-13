from __future__ import annotations

import json

from mini_science.config import load_config
from mini_science.runner import run_pilot
from mini_science.worldgen import generate_worlds


def test_all_conditions_run_with_mock(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    run_dir = run_pilot(tmp_path, config, provider="mock", worlds=["W001"], conditions=list(config.conditions), repeats=1)
    rows = list(__import__("csv").DictReader((run_dir / "results.csv").open(encoding="utf-8")))
    assert len(rows) == 6
    assert all(row["provider"] == "mock" for row in rows)
    assert all(row["non_evidence"].lower() == "true" for row in rows)
    c = next(row for row in rows if row["condition"] == "C_SEQ2_TRANSFER")
    d = next(row for row in rows if row["condition"] == "D_SEQ2_BLOCK")
    assert c["stage1_artifact_sha256"] == d["stage1_artifact_sha256"]
    assert c["forwarded_artifact_sha256"] != d["forwarded_artifact_sha256"]
    events = "\n".join((run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines())
    assert "S01" in events
