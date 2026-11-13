from __future__ import annotations

import csv
import io
import json
from urllib.error import HTTPError

from mini_science.config import load_config
from mini_science.public_loader import load_world
from mini_science.router import route_shared_law_artifact
from mini_science.scoring import evaluate_final
from mini_science.adapters.kimi26 import Kimi26Adapter, KimiRequestError
from mini_science.protocol_checks import check_api_response


def test_action_score_survives_numeric_error_but_strict_science_fails(tmp_path):
    config = load_config("config/v5p3_offline_dev.json")
    view = load_world(".", "CV001", "related", worlds_subdir=config.worlds_subdir)
    menu_item = next(item for item in view.experiments if item["experiment_id"] == "E03")
    payload = {
        "experiment_id": "E03",
        "selected_action": {"experiment_id": "E03", "x0": menu_item["x0"], "measure_t": menu_item["measure_t"]},
        "scientific_question": "Which candidates differ?",
        "hypotheses_to_discriminate": ["EXP_DECAY", "HYPERBOLIC_DECAY"],
        "predicted_values": {"EXP_DECAY": 0.01, "HYPERBOLIC_DECAY": 0.01},
        "measurement": view.measurement,
        "predicted_difference": "The candidates differ.",
        "evidence_ids": ["T01", "T02"],
        "uncertainty": "moderate",
    }
    row = evaluate_final(".", "CV001", view, json.dumps(payload), condition="A_TARGET_ONLY", provider="behavioral-mock", model_snapshot="fixture", replicate=0, input_tokens=1, output_tokens=1, api_calls=1, latency_ms=1, billed_cost=0.0, attributed_full_workflow_cost=0.0, worlds_subdir="worlds_v5p3_dev", private_worlds_subdir="worlds_v5p3_dev", require_predicted_values=True, require_selected_action=True, separate_scientific_validity=True)
    assert row["action_valid"] is True
    assert row["top1_action_score"] > 0
    assert row["model_numeric_valid"] is False
    assert row["fully_scientifically_valid"] is False


def test_cd_keeps_stage1_hash_and_changes_forwarded_hash_for_nontrivial_mapping():
    artifact = {
        "shared_law_judgment": "same",
        "candidate_law_id": "EXP_DECAY",
        "hypothesized_shared_law": "decay",
        "source_evidence_ids": ["S01"],
        "target_evidence_ids": ["T01"],
        "variable_mapping": {"source_concentration": "target_state", "source_minutes": "target_time"},
        "status": "hypothesis",
        "brief_justification": "evidence",
    }
    c = route_shared_law_artifact(artifact, True)
    d = route_shared_law_artifact(artifact, False)
    assert c["stage1_artifact_sha256"] == d["stage1_artifact_sha256"]
    assert d["forwarded_artifact_sha256"] != c["forwarded_artifact_sha256"]
    assert d["artifact"]["source_evidence_ids"] == []


def test_kimi_fake_http_contract_model_usage_and_no_retry(monkeypatch, tmp_path):
    key_file = tmp_path / "key.txt"
    key_file.write_text("offline-fixture-key", encoding="utf-8")

    class FakeResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps({"id": "offline", "model": "kimi-k2.6", "choices": [{"message": {"content": '{"status":"ok"}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}}).encode("utf-8")

    class FakeOpener:
        calls = 0
        def open(self, *_args, **_kwargs):
            self.calls += 1
            return FakeResponse()

    opener = FakeOpener()
    monkeypatch.setattr("urllib.request.build_opener", lambda *_args, **_kwargs: opener)
    adapter = Kimi26Adapter(allow_paid_api=True, key_file=key_file, timeout=1, max_output_tokens=32)
    response = adapter.complete([{"role": "user", "content": "offline"}], 8)
    result = check_api_response(response, requested_model="kimi-k2.6", request_attempts=1)
    assert result["gate_result"] == "PASS"
    assert result["usage_source"] == "provider_usage"
    assert opener.calls == 1


def test_kimi_fake_http_model_mismatch_and_cost_cap_fail_before_followup(monkeypatch, tmp_path):
    key_file = tmp_path / "key.txt"
    key_file.write_text("offline-fixture-key", encoding="utf-8")
    calls = {"count": 0}

    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self):
            return b'{"model":"other-model","choices":[{"message":{"content":"{}"}}],"usage":{"prompt_tokens":5,"completion_tokens":3}}'

    class FakeOpener:
        def open(self, *_args, **_kwargs):
            calls["count"] += 1
            return FakeResponse()

    opener = FakeOpener()
    monkeypatch.setattr("urllib.request.build_opener", lambda *_args, **_kwargs: opener)
    adapter = Kimi26Adapter(allow_paid_api=True, key_file=key_file, timeout=1, max_output_tokens=32)
    try:
        adapter.complete([{"role": "user", "content": "offline"}], 8)
    except RuntimeError as error:
        assert "MODEL_IDENTITY_MISMATCH" in str(error)
    else:
        raise AssertionError("model mismatch must fail")
    assert calls["count"] == 1
    capped = Kimi26Adapter(allow_paid_api=True, key_file=key_file, timeout=1, max_output_tokens=32, max_cost_usd=0.0000001)
    try:
        capped.complete([{"role": "user", "content": "offline"}], 8)
    except RuntimeError as error:
        assert "hard cost cap" in str(error)
    else:
        raise AssertionError("cost cap must fail before transport")
    assert calls["count"] == 1
