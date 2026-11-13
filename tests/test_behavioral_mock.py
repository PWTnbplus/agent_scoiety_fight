from __future__ import annotations

import csv

from mini_science.adapters.behavioral_mock import BehavioralMockAdapter
from mini_science.config import load_config
from mini_science.runner import run_pilot
from mini_science.worldgen import generate_worlds


def _rows(run_dir):
    return list(csv.DictReader((run_dir / "results.csv").open(encoding="utf-8")))


def _run(tmp_path, scenario):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    return _rows(run_pilot(tmp_path, config, provider="behavioral-mock", behavioral_scenario=scenario, worlds=["W001"], conditions=["C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=1))


def test_transfer_sensitive_mock_produces_positive_delta(tmp_path):
    rows = _run(tmp_path, "transfer_sensitive")
    c = next(row for row in rows if row["condition"] == "C_SEQ2_TRANSFER")
    d = next(row for row in rows if row["condition"] == "D_SEQ2_BLOCK")
    assert float(c["top1_score"]) > float(d["top1_score"])


def test_transfer_ignored_mock_produces_zero_delta(tmp_path):
    rows = _run(tmp_path, "transfer_ignored")
    c = next(row for row in rows if row["condition"] == "C_SEQ2_TRANSFER")
    d = next(row for row in rows if row["condition"] == "D_SEQ2_BLOCK")
    assert float(c["top1_score"]) == float(d["top1_score"])


def test_bad_stage1_is_not_successful_transfer(tmp_path):
    rows = _run(tmp_path, "bad_stage1")
    assert all(row["stage1_valid"].lower() == "false" for row in rows)
    assert all(row["stage1_transfer_eligible"].lower() == "false" for row in rows)


def test_citation_leak_is_invalid(tmp_path):
    rows = _run(tmp_path, "citation_leak")
    blocked = next(row for row in rows if row["condition"] == "D_SEQ2_BLOCK")
    assert blocked["valid"].lower() == "false"
    assert blocked["invalid_reason"] == "unseen_evidence_reference"


def test_behavioral_mock_never_reads_private_files(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("behavioral mock must not read private files")
    monkeypatch.setattr("pathlib.Path.read_text", fail)
    response = BehavioralMockAdapter("constant").complete([{"role": "user", "content": "Choose an action."}], 8)
    assert response.metadata["test_fixture"] is True
