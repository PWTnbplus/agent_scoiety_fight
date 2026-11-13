from __future__ import annotations

import math

from mini_science.ig_oracle import expected_information_gain, oracle_scores


def test_oracle_bounds_and_convergence():
    priors = [0.25] * 4
    assert expected_information_gain(priors, [0.2] * 4, 0.04) == 0.0
    one = expected_information_gain(priors, [0.1, 0.25, 0.4, 0.8], 0.05, n_grid=801)
    two = expected_information_gain(priors, [0.1, 0.25, 0.4, 0.8], 0.05, n_grid=1601)
    assert abs(one - two) < 0.001
    menu = [{"experiment_id": "E01", "x0": 0.7, "measure_t": 1.8}, {"experiment_id": "E02", "x0": 1.4, "measure_t": 2.6}]
    result = oracle_scores([{"x0": 1.0, "t": 0.08, "observed_x": 0.962}, {"x0": 1.0, "t": 0.18, "observed_x": 0.918}], menu, 0.5, 0.04)
    assert math.isclose(max(result["top1_score"].values()), 100.0)
    assert all(0 <= value <= 100 for value in result["top1_score"].values())
