from __future__ import annotations

import csv
from pathlib import Path

from mini_science.science_audit import write_csv


def test_write_csv_preserves_union_of_derived_fields(tmp_path):
    path = write_csv(tmp_path / "derived.csv", [{"world_id": "CV001", "metric": "a"}, {"world_id": "CV002", "metric": "b", "extra": "x"}])
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["world_id"] == "CV001"
    assert rows[1]["extra"] == "x"


def test_report_directory_is_new_and_historical_reports_remain_separate():
    root = Path(__file__).resolve().parents[1]
    assert (root / "reports/014_V5P10_SCIENCE_AUDIT").is_dir()
    assert (root / "reports/013_V5P9_NETWORK_AND_MIN_RETEST_20261113T045201Z").is_dir()


def test_public_identifiability_output_exists_after_audit():
    root = Path(__file__).resolve().parents[1]
    assert (root / "reports/014_V5P10_SCIENCE_AUDIT/02_PUBLIC_IDENTIFIABILITY.csv").exists()


def test_transfer_output_has_explicit_content_dimensions():
    root = Path(__file__).resolve().parents[1]
    header = (root / "reports/014_V5P10_SCIENCE_AUDIT/03_STAGE1_TRANSFER_DIAGNOSTIC.csv").read_text(encoding="utf-8").splitlines()[0]
    for field in ("routing_transfer_applied", "law_content_specific", "informative_correct_transfer_observed", "stage1_abstained"):
        assert field in header


def test_numeric_output_has_raw_and_audit_columns():
    root = Path(__file__).resolve().parents[1]
    header = (root / "reports/014_V5P10_SCIENCE_AUDIT/04_NUMERIC_PREDICTION_DIAGNOSTIC.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "raw_model_predicted_values" in header
    assert "formula_audit_accuracy" in header
    assert "calculator_numeric_accuracy" in header


def test_scope_decision_blocks_unapproved_cv004_request():
    root = Path(__file__).resolve().parents[1]
    text = (root / "reports/014_V5P10_SCIENCE_AUDIT/09_API_SCOPE_DECISION.md").read_text(encoding="utf-8")
    assert "NO-GO" in text
    assert "zero new API requests" in text


def test_audit_report_mentions_provider_billing_status():
    root = Path(__file__).resolve().parents[1]
    text = (root / "reports/014_V5P10_SCIENCE_AUDIT/SCIENCE_AUDIT_REPORT.md").read_text(encoding="utf-8")
    assert "UNVERIFIED" in text
    assert "新增真实API请求数：0" in text
