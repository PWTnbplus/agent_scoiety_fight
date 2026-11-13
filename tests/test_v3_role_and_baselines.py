from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from mini_science.analysis import write_cheap_baselines
from mini_science.config import load_config
from mini_science.protocol_checks import role_response_check
from mini_science.public_loader import load_world
from mini_science.runner import probe_role


def test_v3_role_contract_detects_valid_and_truncated_outputs():
    config = load_config("config/pilot_v2.json")
    view = load_world(".", "W001", "related", worlds_subdir=config.worlds_subdir)

    from mini_science.adapters.base import LLMResponse

    response = LLMResponse(
        text=json.dumps({
            "experiment_id": "E04",
            "scientific_question": "Which candidate mechanisms make different predictions?",
            "hypotheses_to_discriminate": ["EXP_DECAY", "HYPERBOLIC_DECAY"],
            "measurement": "normalized_state",
            "predicted_difference": "The predictions differ.",
            "evidence_ids": ["T01", "T02"],
            "uncertainty": "moderate",
        }),
        model="mock",
        input_tokens=10,
        output_tokens=20,
        latency_ms=1,
        metadata={"usage_verified": True},
    )
    checked = role_response_check(response, role="single_question_designer", view=view, requested_model="mock")
    assert checked["gate_result"] == "PASS"

    truncated = LLMResponse(**{**response.__dict__, "metadata": {"usage_verified": True, "finish_reason": "length"}})
    assert role_response_check(truncated, role="single_question_designer", view=view, requested_model="mock")["gate_result"] == "TRUNCATED_OUTPUT"


def test_v3_behavioral_probe_writes_contract_report(tmp_path):
    config = load_config("config/pilot_v2.json")
    shutil.copytree(Path("data") / config.worlds_subdir / "W001", tmp_path / "data" / config.worlds_subdir / "W001")
    run_dir = probe_role(tmp_path, config, provider="behavioral-mock", world_id="W001", role="single_question_designer", max_calls=1, kimi26_max_output_tokens=800)
    payload = json.loads((run_dir / "probe_response.json").read_text(encoding="utf-8"))
    assert payload["contract_check"]["gate_result"] == "PASS"
    assert (run_dir / "role_probe_report.md").exists()


def test_v3_cheap_baselines_use_public_nominal_rate(tmp_path):
    config = load_config("config/pilot_v2.json")
    output = write_cheap_baselines(".", config, tmp_path / "cheap_baselines.csv")
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == config.num_worlds
    assert "simple_predicted_gap_experiment" in rows[0]
    assert "true_k" not in (tmp_path / "cheap_baselines.csv").read_text(encoding="utf-8")

