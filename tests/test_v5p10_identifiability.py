from __future__ import annotations

from pathlib import Path

import pytest

from mini_science.science_audit import _parse_public_world, public_identifiability
from mini_science.simulators import predict


ROOT = Path(__file__).resolve().parents[1]


def test_public_audit_reads_all_four_worlds_without_private_inputs():
    rows, summaries = public_identifiability(ROOT)
    assert {row["world_id"] for row in summaries} == {"CV001", "CV002", "CV003", "CV004"}
    assert all(row["world_id"] in {"CV001", "CV002", "CV003", "CV004"} for row in rows)
    assert all(row["source_initial_state_status"] == "UNIDENTIFIED" for row in rows)


def test_public_audit_does_not_record_private_files():
    _, summaries = public_identifiability(ROOT)
    assert all("private" not in row["public_source_files"] for row in summaries)


def test_cv002_public_unit_conversion_is_explicit():
    data = _parse_public_world(ROOT, "CV002")
    assert data["source_time_unit_status"] == "EXPLICIT_CONVERSION"
    assert data["source_rows"][0]["value"] == pytest.approx(0.840793)
    assert data["source_rows"][0]["time"] == pytest.approx(0.3)


def test_cv001_source_units_remain_unidentified():
    data = _parse_public_world(ROOT, "CV001")
    assert data["source_time_unit_status"] == "UNIDENTIFIED"
    assert data["source_rate_status"] == "UNIDENTIFIED"
    assert data["source_noise_status"] == "UNIDENTIFIED"


def test_s0_is_explicitly_unidentified():
    rows, _ = public_identifiability(ROOT, ("CV001",))
    s0 = [row for row in rows if row["scenario"] == "S0"]
    assert len(s0) == 4
    assert all(row["rss"] == "UNIDENTIFIED" for row in s0)
    assert all("source_k=UNIDENTIFIED" in row["assumptions"] for row in s0)


def test_s1_is_labeled_assumption_not_fact():
    rows, _ = public_identifiability(ROOT, ("CV001",))
    s1 = [row for row in rows if row["scenario"] == "S1"]
    assert len(s1) == 4
    assert all(row["fitted_x0"] == 1.0 for row in s1)
    assert all("source_x0=1.0" in row["assumptions"] for row in s1)


def test_s2_fit_parameters_stay_inside_preregistered_bounds():
    rows, _ = public_identifiability(ROOT)
    s2 = [row for row in rows if row["scenario"] == "S2"]
    assert len(s2) == 16
    assert all(row["valid_parameter_bounds"] in (True, "True") for row in s2)
    assert all(0.10 <= float(row["fitted_x0"]) <= 1.50 for row in s2)
    assert all(0.01 <= float(row["fitted_k"]) <= 2.00 for row in s2)


@pytest.mark.parametrize("model", ("EXP_DECAY", "HYPERBOLIC_DECAY", "STRETCHED_EXP", "BI_EXP"))
def test_public_formula_audit_uses_existing_simulator(model):
    value = predict(model, 0.7, 2.6, 0.535)
    assert value >= 0.0
    assert value == predict(model, 0.7, 2.6, 0.535)

