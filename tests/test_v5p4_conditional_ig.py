from __future__ import annotations

from mini_science.ig_oracle import conditional_oracle_scores, oracle_scores


def test_conditional_ig_is_explicitly_separate_from_frozen_target_only_metric():
    target = [{"x0": 1.0, "t": 0.08, "observed_x": 0.95}, {"x0": 1.0, "t": 0.18, "observed_x": 0.89}]
    source = [{"x0": 1.0, "t": 0.30, "observed_x": 0.84}, {"x0": 1.0, "t": 0.75, "observed_x": 0.66}]
    menu = [{"experiment_id": "E01", "x0": 0.7, "measure_t": 0.5}, {"experiment_id": "E03", "x0": 0.7, "measure_t": 1.8}]
    primary = oracle_scores(target, menu, 0.535, 0.04)
    conditional = conditional_oracle_scores(target, source, menu, 0.535, 0.04)
    assert "metric" not in primary
    assert conditional["metric"] == "IG(q|K_target,K_source)"
    assert conditional["target_observation_count"] == 2
    assert conditional["source_observation_count"] == 2
