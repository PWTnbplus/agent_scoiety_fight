from __future__ import annotations

import csv
import json
from pathlib import Path

from mini_science.config import load_config
from mini_science.metrics.prediction_audit import audit_prediction_values
from mini_science.prompts import seq2_stage1_messages
from mini_science.public_loader import load_world
from mini_science.runner import _real_result_failure_reason, run_pilot
from mini_science.schema import validate_mapping, validate_selected_action
from mini_science.scoring import evaluate_final
from mini_science.simulators import predict
from mini_science.worldgen import generate_worlds


def test_v5p2_stage1_prompt_has_observations_but_no_action_menu():
    config = load_config("config/v5p2_dev.json")
    view = load_world(".", "DV001", "related", worlds_subdir=config.worlds_subdir)
    messages = seq2_stage1_messages(view, protocol_version="v5p2")
    serialized = json.dumps(messages, ensure_ascii=False).lower()
    assert "experiments" not in serialized
    assert "candidate_experiments" not in serialized
    assert "choose exactly one experiment" not in serialized
    assert all(f"e{index:02d}" not in serialized for index in range(1, 9))
    assert "public_variable_mapping_schema" in serialized


def test_v5p2_mapping_and_action_are_exact_public_contracts():
    config = load_config("config/v5p2_dev.json")
    view = load_world(".", "DV001", "related", worlds_subdir=config.worlds_subdir)
    assert validate_mapping({"source_state": "target_state", "source_time": "target_time"}, view).valid
    assert not validate_mapping({"source_state": "private_truth", "source_time": "target_time"}, view).valid
    item = next(item for item in view.experiments if item["experiment_id"] == "E04")
    assert validate_selected_action({"experiment_id": "E04", "x0": item["x0"], "measure_t": item["measure_t"]}, view).valid
    assert validate_selected_action({"experiment_id": "E04", "x0": 1.4, "measure_t": item["measure_t"]}, view).reason == "selected_action_parameters_mismatch"


def test_v5p2_action_score_is_separate_from_numeric_accuracy(tmp_path):
    config = load_config("config/v4_pilot_offline.json")
    generate_worlds(tmp_path, config)
    view = load_world(tmp_path, "W001", "related", worlds_subdir=config.worlds_subdir)
    item = next(item for item in view.experiments if item["experiment_id"] == "E04")
    payload = {
        "experiment_id": "E04",
        "selected_action": {"experiment_id": "E04", "x0": item["x0"], "measure_t": item["measure_t"]},
        "scientific_question": "Which mechanisms differ?",
        "hypotheses_to_discriminate": ["EXP_DECAY", "HYPERBOLIC_DECAY"],
        "predicted_values": {"EXP_DECAY": 0.01, "HYPERBOLIC_DECAY": 0.01},
        "measurement": view.measurement,
        "predicted_difference": "The candidates differ.",
        "evidence_ids": ["T01", "T02"],
        "uncertainty": "moderate",
    }
    row = evaluate_final(tmp_path, "W001", view, json.dumps(payload), condition="A_TARGET_ONLY", provider="behavioral-mock", model_snapshot="fixture", replicate=0, input_tokens=1, output_tokens=1, api_calls=1, latency_ms=1, billed_cost=0.0, attributed_full_workflow_cost=0.0, worlds_subdir=config.worlds_subdir, private_worlds_subdir=config.private_worlds_subdir, require_predicted_values=True, require_selected_action=True, separate_scientific_validity=True)
    assert row["action_valid"] is True
    assert row["top1_action_score"] > 0
    assert row["model_numeric_valid"] is False
    assert row["fully_scientifically_valid"] is False


def test_v5p2_fake_adapter_fail_closed_before_followup_paid_call():
    class FakeAdapter:
        def __init__(self):
            self.calls = 0

        def paid_call(self):
            self.calls += 1

    adapter = FakeAdapter()
    first_result = {"valid": True, "prediction_consistency": "FAIL", "mapping_valid": True}
    adapter.paid_call()
    stop_reason = _real_result_failure_reason(first_result)
    if stop_reason is None:
        adapter.paid_call()
    assert stop_reason == "stage2_numeric_consistency_failure"
    assert adapter.calls == 1


def test_v5p2_offline_behavioral_run_preserves_c_d_stage1_and_blocks_d_route(tmp_path):
    config = load_config("config/v5p2_dev.json")
    run_dir = run_pilot(Path(".").resolve(), config, provider="behavioral-mock", behavioral_scenario="constant", worlds=["DV001"], conditions=list(config.conditions), repeats=1, run_dir=tmp_path / "run")
    rows = list(csv.DictReader((run_dir / "results.csv").open(encoding="utf-8")))
    c = next(row for row in rows if row["condition"] == "C_SEQ2_TRANSFER")
    d = next(row for row in rows if row["condition"] == "D_SEQ2_BLOCK")
    assert c["stage1_artifact_sha256"] == d["stage1_artifact_sha256"]
    assert c["forwarded_artifact_sha256"] != d["forwarded_artifact_sha256"]
    assert c["selected_action"]
    assert d["selected_action"]
