from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from mini_science.science_audit import audit_numeric_predictions, audit_pairs, audit_transfer_and_context, ledger_audit


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "real_v5p9_cv001_20261113T051128Z"
SESSION = ROOT / "runs" / "real_api_sessions" / "v5p8_20261113T051128Z_EaoUuJd3uipEyC_h"


def _rows():
    with (RUN / "results.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_ledger_has_five_unique_requests_and_no_retry():
    audit = ledger_audit(RUN, SESSION)
    assert audit["request_count"] == 5
    assert audit["unique_request_count"] == 5
    assert audit["automatic_retries"] == 0
    assert audit["session_unique_attempt_count"] == 5
    assert audit["session_completed_count"] == 5


def test_ledger_token_totals_match_v5p9():
    audit = ledger_audit(RUN, SESSION)
    assert audit["unique_provider_input_tokens"] == 5384
    assert audit["unique_provider_output_tokens"] == 1225
    assert audit["unique_provider_tokens"] == 6609
    assert audit["attributed_condition_tokens"] == 7620


def test_usage_and_reserved_costs_are_separate():
    audit = ledger_audit(RUN, SESSION)
    assert audit["provider_usage_local_estimate_usd"] == pytest.approx(0.0100148)
    assert audit["request_reserved_estimate_usd"] == pytest.approx(0.02448805)
    assert audit["provider_billing_verified"] is False
    assert all(value is None for value in audit["provider_billed_cost_or_null"])


def test_stage1_unknown_is_abstention_not_content_success():
    rows = audit_transfer_and_context(RUN)
    c = next(row for row in rows if row["condition"] == "C_SEQ2_TRANSFER")
    assert c["stage1_abstained"] is True
    assert c["law_content_specific"] is False
    assert c["informative_transfer_observed"] is False
    assert c["informative_correct_transfer_observed"] is False


def test_c_d_share_stage1_hash_but_only_c_transfers():
    rows = audit_transfer_and_context(RUN)
    c = next(row for row in rows if row["condition"] == "C_SEQ2_TRANSFER")
    d = next(row for row in rows if row["condition"] == "D_SEQ2_BLOCK")
    assert c["stage1_artifact_sha256"] == d["stage1_artifact_sha256"]
    assert c["routing_transfer_applied"] is True
    assert d["routing_transfer_applied"] is False
    assert d["route_intervention"] == "blocked"
    assert d["forwarded_artifact_sha256"] != d["stage1_artifact_sha256"]


def test_a_b_context_is_reported_as_irrelevant_vs_related_source():
    rows = audit_transfer_and_context(RUN)
    by = {row["condition"]: row for row in rows}
    assert by["A_TARGET_ONLY"]["actual_context"] == "target_plus_irrelevant_source"
    assert by["B_SINGLE_RELATED"]["actual_context"] == "target_plus_related_source"


def test_d_prompt_has_no_stage1_content_and_length_is_recorded():
    rows = audit_transfer_and_context(RUN)
    d = next(row for row in rows if row["condition"] == "D_SEQ2_BLOCK")
    c = next(row for row in rows if row["condition"] == "C_SEQ2_TRANSFER")
    assert int(d["prompt_chars"]) < int(c["prompt_chars"])
    assert int(d["prompt_input_tokens"]) < int(c["prompt_input_tokens"])


def test_numeric_diagnostic_preserves_raw_model_values():
    rows = audit_numeric_predictions(ROOT, RUN)
    a = next(row for row in rows if row["condition"] == "A_TARGET_ONLY")
    assert a["raw_model_predicted_values"]
    assert a["calculation_mode"].startswith("public_formula_audit_only")
    assert a["calculator_numeric_accuracy"] == "NOT_RUN_ASSISTED_PROTOCOL"
    assert a["agent_numeric_accuracy"] == 0.0


def test_b_numeric_accuracy_is_one_of_four():
    rows = audit_numeric_predictions(ROOT, RUN)
    b = next(row for row in rows if row["condition"] == "B_SINGLE_RELATED")
    assert b["agent_numeric_correct_count"] == 1
    assert b["agent_numeric_total"] == 4
    assert b["agent_numeric_accuracy"] == 0.25


def test_all_selected_actions_are_menu_consistent():
    rows = audit_numeric_predictions(ROOT, RUN)
    assert all(row["selected_action_consistent"] for row in rows)


def test_action_and_strict_pairs_keep_undefined_strict_value():
    pairs = audit_pairs(RUN)
    cd = next(row for row in pairs if row["contrast"] == "C_minus_D_action")
    ba = next(row for row in pairs if row["contrast"] == "B_minus_A_action")
    assert cd["action_delta"] == 0.0
    assert cd["strict_delta"] is None
    assert cd["strict_status"] == "UNDEFINED"
    assert ba["action_delta"] == pytest.approx(9.656722596631312)


def test_stage1_artifact_is_recorded_once_per_pair():
    rows = audit_transfer_and_context(RUN)
    hashes = {row["stage1_artifact_sha256"] for row in rows if row["condition"] in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}}
    assert hashes == {"3f6fe01cadee85f96fb41fef0adc954f071ca3f42be1c07d7c4a43855be86bf7"}


def test_no_failed_or_unexecuted_rows_in_historical_v5p9():
    assert all(row["run_status"] == "COMPLETED" for row in _rows())


def test_raw_results_are_not_rewritten_by_audit():
    raw = (RUN / "results.csv").read_text(encoding="utf-8")
    audit_numeric_predictions(ROOT, RUN)
    assert (RUN / "results.csv").read_text(encoding="utf-8") == raw

