from __future__ import annotations

from mini_science.analysis_v5p11 import _cluster_bootstrap


def test_cluster_bootstrap_counts_worlds_not_repeats():
    rows = [{"world_id": "IV001", "delta": 1}, {"world_id": "IV001", "delta": 3}, {"world_id": "IV002", "delta": 5}, {"world_id": "IV002", "delta": 7}]
    result = _cluster_bootstrap(rows, draws=100)
    assert result["world_clusters"] == 2
    assert result["bootstrap_draws"] == 100


def test_cluster_bootstrap_empty_is_explicit():
    assert _cluster_bootstrap([], draws=10)["ci95"] is None


def test_cluster_bootstrap_one_world_refuses_inferential_ci():
    result = _cluster_bootstrap([{"world_id": "IV001", "delta": 0}, {"world_id": "IV001", "delta": 2}], draws=100)
    assert result["world_clusters"] == 1
    assert result["ci95"] is None
    assert result["ci_status"] == "INSUFFICIENT_WORLD_CLUSTERS"
