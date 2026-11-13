from __future__ import annotations

import json

from mini_science.config import load_config
from mini_science.prompts import seq2_stage1_messages, seq2_stage2_messages, single_messages
from mini_science.public_loader import load_world
from mini_science.router import route_shared_law_artifact


def test_v5p11_a_excludes_source_b_includes_source(tmp_path):
    config = load_config("config/v5p11_main.json")
    view = load_world(".", "IV001", "related", worlds_subdir=config.worlds_subdir)
    a = json.dumps(single_messages(view, "A_TARGET_ONLY", protocol_version="v5p11"), ensure_ascii=False)
    b = json.dumps(single_messages(view, "B_SINGLE_RELATED", protocol_version="v5p11"), ensure_ascii=False)
    assert "source_note" not in a
    assert "source_note" in b
    assert "source_related" not in a


def test_v5p11_stage1_has_no_action_menu_and_d_blocks_in_code():
    config = load_config("config/v5p11_main.json")
    view = load_world(".", "IV001", "related", worlds_subdir=config.worlds_subdir)
    stage1 = json.dumps(seq2_stage1_messages(view, protocol_version="v5p11"), ensure_ascii=False)
    assert '"experiments"' not in stage1
    assert "E01" not in stage1
    artifact = {"shared_law_judgment": "same", "candidate_law_id": "EXP_DECAY", "source_evidence_ids": ["S01"], "target_evidence_ids": ["T01"], "variable_mapping": {"source_state": "target_state", "source_time": "target_time"}, "status": "supported_or_uncertain", "brief_justification": "shape"}
    routed = route_shared_law_artifact(artifact, False, intervention="blocked")
    assert routed["transfer_applied"] is False
    assert routed["artifact"]["candidate_law_id"] == "UNKNOWN"
    assert routed["artifact"]["source_evidence_ids"] == []
    stage2 = json.dumps(seq2_stage2_messages(view, routed["artifact"], "D_SEQ2_BLOCK", protocol_version="v5p11"), ensure_ascii=False)
    assert "EXP_DECAY" not in stage2.split("ROUTED INTERMEDIATE RECORD:", 1)[-1]
