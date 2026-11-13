from __future__ import annotations

import json

from mini_science.config import load_config
from mini_science.evidence_policy import policy_for_route
from mini_science.public_loader import load_world
from mini_science.router import route_shared_law_artifact
from mini_science.schema import validate_final_question
from mini_science.worldgen import generate_worlds


def _final(evidence_ids: list[str]) -> str:
    return json.dumps({
        "experiment_id": "E04",
        "scientific_question": "Which action separates two candidate mechanisms?",
        "hypotheses_to_discriminate": ["EXP_DECAY", "HYPERBOLIC_DECAY"],
        "measurement": "normalized_state",
        "predicted_difference": "The predictions differ.",
        "evidence_ids": evidence_ids,
        "uncertainty": "moderate",
    })


def test_d_rejects_unseen_source_citation_and_c_accepts_mediated_source(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    view = load_world(tmp_path, "W001", "related")
    artifact = {
        "shared_law_judgment": "same",
        "candidate_law_id": "EXP_DECAY",
        "hypothesized_shared_law": "decay",
        "source_evidence_ids": ["S01"],
        "target_evidence_ids": ["T01"],
        "variable_mapping": {"source_state": "target_state", "source_time": "target_time"},
        "status": "supported_or_uncertain",
        "brief_justification": "public evidence",
    }
    blocked = route_shared_law_artifact(artifact, False)
    blocked_policy = policy_for_route(view, route=blocked, condition="D_SEQ2_BLOCK")
    assert not validate_final_question(_final(["T01", "S01"]), view, evidence_policy=blocked_policy).valid
    assert validate_final_question(_final(["T01"]), view, evidence_policy=blocked_policy).valid
    transferred = route_shared_law_artifact(artifact, True)
    transferred_policy = policy_for_route(view, route=transferred, condition="C_SEQ2_TRANSFER")
    assert validate_final_question(_final(["T01", "S01"]), view, evidence_policy=transferred_policy).valid


def test_blocked_prompt_has_no_source_evidence_text(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    view = load_world(tmp_path, "W001", "related")
    blocked = route_shared_law_artifact({"source_evidence_ids": ["S01"], "hypothesized_shared_law": "private-looking text"}, False)
    from mini_science.prompts import seq2_stage2_messages
    prompt = json.dumps(seq2_stage2_messages(view, blocked["artifact"], "D_SEQ2_BLOCK"), ensure_ascii=False)
    assert "S01" not in prompt
    assert "private-looking text" not in prompt
