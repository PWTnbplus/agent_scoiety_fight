from __future__ import annotations

import csv

from mini_science.analysis import write_baselines_by_world
from mini_science.config import load_config


def test_v5p11_baselines_cover_five_named_rules(tmp_path):
    config = load_config("config/v5p11_main.json")
    output = write_baselines_by_world(".", config, tmp_path / "baselines.csv", random_seed=20261113)
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert len(rows) == 20
    assert {row["baseline"] for row in rows} == {"ORACLE_UPPER", "FIXED_E04", "RANDOM", "PUBLIC_HEURISTIC", "TARGET_ONLY_HEURISTIC"}
    assert all(row["public_only_verified"] == "True" for row in rows if row["baseline"] != "ORACLE_UPPER")
