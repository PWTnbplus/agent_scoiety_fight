from __future__ import annotations

import csv

from mini_science.analysis import write_baselines_by_world, write_world_difficulty_audit
from mini_science.config import load_config


def test_public_baselines_cover_cv_worlds_without_private_answer_fields(tmp_path):
    config = load_config("config/v5p4_offline_dev.json")
    output = write_baselines_by_world(".", config, tmp_path / "baselines.csv", random_seed=17)
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert len(rows) == 16
    assert {row["world_id"] for row in rows} == {"CV001", "CV002", "CV003", "CV004"}
    assert {row["baseline"] for row in rows} == {"ORACLE_UPPER", "FIXED_E04", "RANDOM", "PUBLIC_HEURISTIC"}
    assert all("true_k" not in row for row in rows)
    assert all(row["public_only_verified"] == "True" for row in rows if row["baseline"] != "ORACLE_UPPER")
    assert all(row["public_only_verified"] == "False" for row in rows if row["baseline"] == "ORACLE_UPPER")


def test_world_difficulty_audit_covers_all_cv_worlds(tmp_path):
    config = load_config("config/v5p4_offline_dev.json")
    output = write_world_difficulty_audit(".", config, tmp_path / "difficulty.csv")
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert len(rows) == 4
    assert all(int(row["menu_size"]) == 8 for row in rows)
