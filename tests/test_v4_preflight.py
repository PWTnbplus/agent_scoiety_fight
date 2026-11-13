from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from mini_science.analysis import write_comparisons
from mini_science.authorization import V4_CONFIRMATION_PHRASE, create_v4_authorization, proposed_v4_authorization
from mini_science.config import load_config
from mini_science.metrics.prediction_audit import audit_prediction_values
from mini_science.protocol_checks import response_is_truncated
from mini_science.public_loader import load_world
from mini_science.real_gate import GateDenied, V4SessionGate
from mini_science.router import route_shared_law_artifact
from mini_science.runner import _real_result_failure_reason, _stage1_has_action_oracle_leak, run_pilot
from mini_science.schema import ValidationResult, validate_final_question, validate_predicted_values, validate_shared_law
from mini_science.simulators import predict
from mini_science.adapters.base import LLMResponse
from mini_science.adapters.kimi26 import Kimi26Adapter, KimiRequestError
from mini_science.worldgen import generate_worlds


def _config():
    return load_config("config/v4_pilot_offline.json")


def _view(tmp_path):
    config = _config()
    generate_worlds(tmp_path, config)
    return config, load_world(tmp_path, "W001", "related", worlds_subdir=config.worlds_subdir)


def _payload(view, evidence=None, experiment="E04"):
    item = next(item for item in view.experiments if item["experiment_id"] == experiment)
    k = 0.494
    hypotheses = ["EXP_DECAY", "HYPERBOLIC_DECAY"]
    return {
        "experiment_id": experiment,
        "scientific_question": "Which mechanisms differ under this measurement?",
        "hypotheses_to_discriminate": hypotheses,
        "predicted_values": {model: predict(model, float(item["x0"]), float(item["measure_t"]), k) for model in hypotheses},
        "measurement": view.measurement,
        "predicted_difference": "The candidates predict different normalized states.",
        "evidence_ids": evidence or ["T01", "T02"],
        "uncertainty": "moderate",
    }


def test_v4_strict_json_with_numeric_predictions(tmp_path):
    _, view = _view(tmp_path)
    assert validate_final_question(json.dumps(_payload(view)), view, require_predicted_values=True).valid


def test_v4_markdown_fence_is_strictly_invalid(tmp_path):
    _, view = _view(tmp_path)
    assert validate_final_question("```json\n" + json.dumps(_payload(view)) + "\n```", view, require_predicted_values=True).reason.startswith("invalid_json")


def test_v4_explanatory_hypothesis_name_is_rejected(tmp_path):
    _, view = _view(tmp_path)
    payload = _payload(view)
    payload["hypotheses_to_discriminate"][0] = "EXP_DECAY: single exponential"
    assert validate_final_question(json.dumps(payload), view, require_predicted_values=True).reason == "invalid_hypotheses_to_discriminate"


def test_v4_range_evidence_is_rejected(tmp_path):
    _, view = _view(tmp_path)
    assert validate_final_question(json.dumps(_payload(view, ["S01-S04"])), view, require_predicted_values=True).reason == "invalid_evidence_ids"


def test_v4_visible_source_evidence_is_allowed(tmp_path):
    _, view = _view(tmp_path)
    assert validate_final_question(json.dumps(_payload(view, ["S01", "S02"])), view, require_predicted_values=True).valid


def test_v4_d_route_has_no_source_evidence(tmp_path):
    artifact = {"shared_law_judgment": "same", "candidate_law_id": "EXP_DECAY", "hypothesized_shared_law": "decay", "source_evidence_ids": ["S01"], "target_evidence_ids": ["T01"], "variable_mapping": {}, "status": "hypothesis", "brief_justification": "evidence"}
    c = route_shared_law_artifact(artifact, True)
    d = route_shared_law_artifact(artifact, False)
    assert c["stage1_artifact_sha256"] == d["stage1_artifact_sha256"]
    assert d["artifact"]["source_evidence_ids"] == []
    assert d["forwarded_artifact_sha256"] != c["forwarded_artifact_sha256"]


def test_v4_prediction_above_x0_is_rejected(tmp_path):
    _, view = _view(tmp_path)
    payload = _payload(view)
    payload["predicted_values"]["EXP_DECAY"] = 1.0
    assert validate_final_question(json.dumps(payload), view, require_predicted_values=True).reason == "predicted_value_out_of_bounds:EXP_DECAY"


def test_v4_e04_public_predictions_are_frozen(tmp_path):
    _, view = _view(tmp_path)
    item = next(item for item in view.experiments if item["experiment_id"] == "E04")
    values = {model: predict(model, float(item["x0"]), float(item["measure_t"]), 0.494) for model in view.candidate_models}
    assert values["EXP_DECAY"] == pytest.approx(0.1937716367)
    assert values["HYPERBOLIC_DECAY"] == pytest.approx(0.3685995324)
    assert audit_prediction_values(view, "E04", values)["prediction_consistency"] == "PASS"


def test_v4_a_invalid_b_valid_comparison_is_missing(tmp_path):
    path = write_comparisons(tmp_path, [{"world_id": "W001", "replicate": 0, "model_snapshot": "m", "config_hash": "c", "condition": "A_TARGET_ONLY", "valid": False, "top1_score": 0}, {"world_id": "W001", "replicate": 0, "model_snapshot": "m", "config_hash": "c", "condition": "B_SINGLE_RELATED", "valid": True, "proposal_valid": True, "top1_score": 93.3}])
    row = next(csv.DictReader(path.open(encoding="utf-8")))
    assert row["B_minus_A"] == ""


def test_v4_c_valid_d_missing_comparison_is_missing(tmp_path):
    path = write_comparisons(tmp_path, [{"world_id": "W001", "replicate": 0, "model_snapshot": "m", "config_hash": "c", "condition": "C_SEQ2_TRANSFER", "valid": True, "proposal_valid": True, "top1_score": 50}])
    row = next(csv.DictReader(path.open(encoding="utf-8")))
    assert row["C_minus_D"] == ""


def test_v4_c_invalid_d_valid_comparison_is_missing(tmp_path):
    path = write_comparisons(tmp_path, [{"world_id": "W001", "replicate": 0, "model_snapshot": "m", "config_hash": "c", "condition": "C_SEQ2_TRANSFER", "valid": False, "top1_score": 0}, {"world_id": "W001", "replicate": 0, "model_snapshot": "m", "config_hash": "c", "condition": "D_SEQ2_BLOCK", "valid": True, "proposal_valid": True, "top1_score": 50}])
    row = next(csv.DictReader(path.open(encoding="utf-8")))
    assert row["C_minus_D"] == ""


def test_v4_valid_same_e04_comparison_is_zero(tmp_path):
    path = write_comparisons(tmp_path, [{"world_id": "W001", "replicate": 0, "model_snapshot": "m", "config_hash": "c", "condition": "A_TARGET_ONLY", "valid": True, "proposal_valid": True, "top1_score": 93.3}, {"world_id": "W001", "replicate": 0, "model_snapshot": "m", "config_hash": "c", "condition": "B_SINGLE_RELATED", "valid": True, "proposal_valid": True, "top1_score": 93.3}])
    row = next(csv.DictReader(path.open(encoding="utf-8")))
    assert row["B_minus_A"] == "0.0"


def test_v4_stage1_cannot_select_oracle_action(tmp_path):
    _, view = _view(tmp_path)
    payload = {"shared_law_judgment": "same", "candidate_law_id": "EXP_DECAY", "hypothesized_shared_law": "decay", "source_evidence_ids": ["S01"], "target_evidence_ids": ["T01"], "variable_mapping": {}, "status": "hypothesis", "brief_justification": "evidence", "experiment_id": "E04"}
    assert validate_shared_law(json.dumps(payload), view).reason == "stage1_must_not_select_oracle_action"


def test_v4_length_finish_is_truncated():
    response = LLMResponse(text="{}", model="kimi-k2.6", input_tokens=1, output_tokens=1, latency_ms=1, metadata={"finish_reason": "length"})
    assert response_is_truncated(response)


def test_v4_fake_http_error_is_structured_and_not_retried(monkeypatch, tmp_path):
    key_file = tmp_path / "key.txt"
    key_file.write_text("offline-fixture-key", encoding="utf-8")

    class FakeOpener:
        def open(self, *_args, **_kwargs):
            raise HTTPError("https://token.ctflow.cn/v1/chat/completions", 429, "rate limited", {}, io.BytesIO(b"rate"))

    monkeypatch.setattr("urllib.request.build_opener", lambda *_args, **_kwargs: FakeOpener())
    adapter = Kimi26Adapter(allow_paid_api=True, key_file=key_file, timeout=1, max_output_tokens=32)
    with pytest.raises(KimiRequestError) as error:
        adapter.complete([{"role": "user", "content": "offline"}], 8)
    assert error.value.http_status == 429
    assert error.value.failure_kind == "HTTP_ERROR"
    assert len(adapter.calls) == 0


def _authorized_session(tmp_path, cap=5):
    config = _config()
    path = create_v4_authorization(tmp_path, config, approved_by="user_explicit", confirmation=V4_CONFIRMATION_PHRASE, authorization_note="offline fake session", max_unique_provider_attempts=cap, max_estimated_cost_usd=0.05)
    return config, path.parent, V4SessionGate(tmp_path, path.parent)


def _plan(n=5):
    return [{"request_id": f"r{i}", "estimated_cost_usd": 0.001} for i in range(n)]


def test_v4_session_cap_is_checked_before_network(tmp_path):
    _, _, gate = _authorized_session(tmp_path)
    with pytest.raises(GateDenied):
        gate.preflight(provider="kimi26", model="kimi-k2.6", request_plan=_plan(6), worlds=["W001"], conditions=["A_TARGET_ONLY"])


def test_v4_session_recovery_plans_only_remaining_requests(tmp_path):
    _, _, gate = _authorized_session(tmp_path)
    gate.preflight(provider="kimi26", model="kimi-k2.6", request_plan=_plan(5), worlds=["W001"], conditions=["A_TARGET_ONLY"])
    reservation = gate.reserve(request_id="r0", provider="kimi26", model="kimi-k2.6", stage="pilot", estimated_cost_usd=0.001, world_id="W001", condition="A_TARGET_ONLY")
    gate.finish(reservation, status="COMPLETED", billing_verified=False)
    result = gate.preflight(provider="kimi26", model="kimi-k2.6", request_plan=_plan(5), worlds=["W001"], conditions=["A_TARGET_ONLY"])
    assert result["planned_calls"] == 4
    assert result["skipped_request_ids"] == ["r0"]


def test_v4_session_does_not_touch_v3_files(tmp_path):
    v3 = tmp_path / "runs" / "v3_real_gate_state.json"
    v3.parent.mkdir(parents=True)
    v3.write_text("v3-sentinel", encoding="utf-8")
    _authorized_session(tmp_path)
    assert v3.read_text(encoding="utf-8") == "v3-sentinel"


def test_v4_missing_provider_billing_is_unverified(tmp_path):
    _, _, gate = _authorized_session(tmp_path)
    reservation = gate.reserve(request_id="r0", provider="kimi26", model="kimi-k2.6", stage="pilot", estimated_cost_usd=0.001, world_id="W001", condition="A_TARGET_ONLY")
    gate.finish(reservation, status="COMPLETED", actual_cost_usd=None, billing_verified=False)
    summary = gate.summary()
    assert summary["completed_attempts"] == 1
    assert summary["cost_remaining"] > 0


def test_v4_proposal_is_not_authorized(tmp_path):
    proposal = proposed_v4_authorization(tmp_path, _config())
    assert proposal["authorization_status"] == "PROPOSED_NOT_AUTHORIZED"
    assert not (tmp_path / "runs" / "real_api_sessions").exists()


def test_v4_constant_behavioral_mock_has_zero_cd(tmp_path):
    config = _config()
    generate_worlds(tmp_path, config)
    run_dir = run_pilot(tmp_path, config, provider="behavioral-mock", behavioral_scenario="constant", worlds=["W001"], conditions=list(config.conditions), repeats=1)
    row = next(csv.DictReader((run_dir / "paired_deltas.csv").open(encoding="utf-8")))
    assert row["C_minus_D"] == "0.0"
    rows = list(csv.DictReader((run_dir / "results.csv").open(encoding="utf-8")))
    c = next(item for item in rows if item["condition"] == "C_SEQ2_TRANSFER")
    d = next(item for item in rows if item["condition"] == "D_SEQ2_BLOCK")
    assert c["stage1_artifact_sha256"] == d["stage1_artifact_sha256"]


def test_v4_transfer_sensitive_behavioral_control_is_positive(tmp_path):
    config = _config()
    generate_worlds(tmp_path, config)
    run_dir = run_pilot(tmp_path, config, provider="behavioral-mock", behavioral_scenario="transfer_sensitive", worlds=["W001"], conditions=["C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"], repeats=1)
    rows = list(csv.DictReader((run_dir / "results.csv").open(encoding="utf-8")))
    c = next(item for item in rows if item["condition"] == "C_SEQ2_TRANSFER")
    d = next(item for item in rows if item["condition"] == "D_SEQ2_BLOCK")
    assert float(c["top1_score"]) > float(d["top1_score"])


def test_v4_real_numeric_failure_stops_before_next_paid_call():
    row = {"valid": True, "prediction_consistency": "FAIL", "mapping_valid": True}
    assert _real_result_failure_reason(row) == "stage2_numeric_consistency_failure"


def test_v4_real_stage1_mapping_failure_stops_transfer():
    row = {"valid": True, "prediction_consistency": "PASS", "mapping_valid": False}
    assert _real_result_failure_reason(row, require_stage1_mapping=True) == "stage1_mapping_check_failed"


def test_v4_real_stage1_action_text_cannot_select_an_experiment():
    artifact = {"brief_justification": "Selecting E04 would maximize discrimination."}
    assert _stage1_has_action_oracle_leak(artifact)

