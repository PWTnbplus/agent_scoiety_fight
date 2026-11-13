from __future__ import annotations

from mini_science.router import route_shared_law_artifact


def test_d_route_removes_informative_fields():
    artifact = {
        "shared_law_judgment": "same",
        "candidate_law_id": "EXP_DECAY",
        "hypothesized_shared_law": "decay",
        "source_evidence_ids": ["S01"],
        "target_evidence_ids": ["T01"],
        "variable_mapping": {"source_state": "target_state"},
        "status": "supported_or_uncertain",
        "brief_justification": "evidence",
    }
    c = route_shared_law_artifact(artifact, True)
    d = route_shared_law_artifact(artifact, False)
    assert c["stage1_artifact_sha256"] == d["stage1_artifact_sha256"]
    assert c["forwarded_artifact_sha256"] != d["forwarded_artifact_sha256"]
    assert c["artifact"]["source_evidence_ids"] == ["S01"]
    assert d["artifact"]["source_evidence_ids"] == []
    assert "decay" not in str(d["artifact"]["hypothesized_shared_law"])
