from __future__ import annotations

import csv
import json

from mini_science.config import load_config
from mini_science.runner import run_pilot
from mini_science.worldgen import generate_worlds


def test_repeat_two_has_independent_stage1_and_cd_pairing(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    run_dir = run_pilot(tmp_path, config, provider="behavioral-mock", behavioral_scenario="transfer_sensitive", worlds=["W001"], conditions=["C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=2)
    rows = list(csv.DictReader((run_dir / "results.csv").open(encoding="utf-8")))
    assert len(rows) == 4
    stage1_hashes = {row["stage1_artifact_sha256"] for row in rows}
    assert len(stage1_hashes) == 2
    for replicate in ("0", "1"):
        pair = [row for row in rows if row["replicate"] == replicate]
        assert len({row["stage1_artifact_sha256"] for row in pair}) == 1
        assert len({row["pair_id"] for row in pair}) == 1


def test_resume_complete_run_does_not_add_calls(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    run_dir = run_pilot(tmp_path, config, provider="behavioral-mock", behavioral_scenario="constant", worlds=["W001"], conditions=["C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=1)
    before = (run_dir / "call_ledger.jsonl").read_text(encoding="utf-8")
    run_pilot(tmp_path, config, provider="behavioral-mock", behavioral_scenario="constant", worlds=["W001"], conditions=["C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=1, run_dir=run_dir)
    assert (run_dir / "call_ledger.jsonl").read_text(encoding="utf-8") == before


def test_changed_manifest_refuses_resume(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    run_dir = run_pilot(tmp_path, config, provider="behavioral-mock", worlds=["W001"], conditions=["C_SEQ2_TRANSFER"], repeats=1)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fingerprint_hash"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    import pytest
    with pytest.raises(RuntimeError, match="manifest mismatch"):
        run_pilot(tmp_path, config, provider="behavioral-mock", worlds=["W001"], conditions=["C_SEQ2_TRANSFER"], repeats=1, run_dir=run_dir)


def test_resume_after_stage1_artifact_exists_runs_only_missing_stage2(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    run_dir = run_pilot(tmp_path, config, provider="behavioral-mock", behavioral_scenario="constant", worlds=["W001"], conditions=["C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=1)
    results = run_dir / "results.csv"
    results.unlink()
    before = [json.loads(line) for line in (run_dir / "call_ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    run_pilot(tmp_path, config, provider="behavioral-mock", behavioral_scenario="constant", worlds=["W001"], conditions=["C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=1, run_dir=run_dir)
    after = [json.loads(line) for line in (run_dir / "call_ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(after) == len(before) + 2
    assert sum(record["stage"] == "stage1" for record in after) == 1
