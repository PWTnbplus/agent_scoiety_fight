from __future__ import annotations

import json

from mini_science.config import load_config
from mini_science.prompts import seq2_stage1_messages
from mini_science.public_loader import load_world
from mini_science.runner import stage1_truth_checks
from mini_science.schema import validate_shared_law


def _artifact(view, relation, law, mapping, *, source_ids=None):
    return {
        "shared_law_judgment": relation,
        "candidate_law_id": law,
        "hypothesized_shared_law": "A provisional observation-level comparison.",
        "source_evidence_ids": source_ids if source_ids is not None else list(view.source_evidence_ids[:2]),
        "target_evidence_ids": list(view.target_evidence_ids),
        "variable_mapping": mapping,
        "status": "supported_or_uncertain",
        "brief_justification": "The public records provide a limited comparison.",
    }


def test_correct_same_with_nontrivial_mapping_is_schema_valid():
    config = load_config("config/v5p3_offline_dev.json")
    view = load_world(".", "CV002", "related", worlds_subdir=config.worlds_subdir)
    artifact = _artifact(view, "same", "EXP_DECAY", {"source_concentration": "target_state", "source_minutes": "target_time"})
    assert validate_shared_law(json.dumps(artifact), view).valid


def test_correct_different_and_unknown_allow_scientific_abstention():
    config = load_config("config/v5p3_offline_dev.json")
    different = load_world(".", "CV003", "related", worlds_subdir=config.worlds_subdir)
    unknown = load_world(".", "CV004", "related", worlds_subdir=config.worlds_subdir)
    assert validate_shared_law(json.dumps(_artifact(different, "different", "UNKNOWN", {})), different).valid
    assert validate_shared_law(json.dumps(_artifact(unknown, "unknown", "UNKNOWN", "not_applicable")), unknown).valid


def test_invalid_candidate_and_mapping_are_rejected():
    config = load_config("config/v5p3_offline_dev.json")
    view = load_world(".", "CV002", "related", worlds_subdir=config.worlds_subdir)
    bad_candidate = _artifact(view, "same", "NOT_A_MODEL", {"source_concentration": "target_state", "source_minutes": "target_time"})
    bad_mapping = _artifact(view, "same", "EXP_DECAY", {"source_concentration": "target_state", "source_minutes": "private_truth"})
    assert validate_shared_law(json.dumps(bad_candidate), view).reason == "invalid_candidate_law_id"
    assert not validate_shared_law(json.dumps(bad_mapping), view).valid


def test_stage1_prompt_contains_public_schema_but_no_private_labels_or_menu():
    config = load_config("config/v5p3_offline_dev.json")
    view = load_world(".", "CV002", "related", worlds_subdir=config.worlds_subdir)
    text = json.dumps(seq2_stage1_messages(view, protocol_version="v5p3"), ensure_ascii=False).lower()
    assert "source_concentration" in text and "source_minutes" in text
    assert "experiments" not in text and "oracle_results" not in text and "true_law" not in text
    assert all(f"e{index:02d}" not in text for index in range(1, 9))


def test_private_relation_oracle_scores_same_different_unknown_without_forcing_same():
    config = load_config("config/v5p3_offline_dev.json")
    for world_id, relation, law, mapping, expected_key in [
        ("CV001", "same", "EXP_DECAY", {"source_state": "target_state", "source_time": "target_time"}, "stage1_relation_correct"),
        ("CV003", "different", "UNKNOWN", {}, "stage1_abstention_appropriate"),
        ("CV004", "unknown", "UNKNOWN", {}, "stage1_abstention_appropriate"),
    ]:
        view = load_world(".", world_id, "related", worlds_subdir=config.worlds_subdir)
        truth = json.loads((__import__("pathlib").Path("private") / config.private_worlds_subdir / world_id / "hidden_truth.json").read_text(encoding="utf-8"))
        artifact = _artifact(view, relation, law, mapping)
        checks = stage1_truth_checks(artifact, truth, view)
        assert checks[expected_key] is True
    view = load_world(".", "CV003", "related", worlds_subdir=config.worlds_subdir)
    truth = json.loads((__import__("pathlib").Path("private") / config.private_worlds_subdir / "CV003" / "hidden_truth.json").read_text(encoding="utf-8"))
    forced_same = _artifact(view, "same", "EXP_DECAY", {"source_state": "target_state", "source_time": "target_time"})
    assert stage1_truth_checks(forced_same, truth, view)["stage1_relation_correct"] is False
