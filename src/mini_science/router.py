from __future__ import annotations

from copy import deepcopy
from typing import Any

from .schema import sha256_json


def route_shared_law_artifact(artifact: dict[str, Any], transfer_applied: bool, *, intervention: str = "real") -> dict[str, Any]:
    """Serialize route interventions; blocked routes contain no source IDs."""
    stage1_hash = sha256_json(artifact)
    if transfer_applied and intervention == "real":
        forwarded = deepcopy(artifact)
    elif transfer_applied and intervention == "misaligned":
        forwarded = deepcopy(artifact)
        forwarded["variable_mapping"] = {"source_state": "target_time", "source_time": "target_state"}
        forwarded["status"] = "controlled_misalignment"
        forwarded["brief_justification"] = "A length-matched route with a controlled variable mismatch was supplied."
    elif transfer_applied and intervention == "irrelevant":
        forwarded = {
            "shared_law_judgment": "unknown",
            "candidate_law_id": "UNKNOWN",
            "hypothesized_shared_law": "an unrelated public pattern record with the same structural length",
            "source_evidence_ids": [],
            "target_evidence_ids": [],
            "variable_mapping": {},
            "status": "irrelevant_intermediate",
            "brief_justification": "A length-matched but non-transportable record was supplied.",
        }
    else:
        forwarded = {
            "shared_law_judgment": "unknown",
            "candidate_law_id": "UNKNOWN",
            "hypothesized_shared_law": "no intermediate record was transferred in this condition",
            "source_evidence_ids": [],
            "target_evidence_ids": [],
            "variable_mapping": {},
            "status": "not_available",
            "brief_justification": "The routing layer supplied a neutral placeholder.",
        }
    return {
        "artifact": forwarded,
        "stage1_artifact_sha256": stage1_hash,
        "forwarded_artifact_sha256": sha256_json(forwarded),
        "transfer_applied": transfer_applied,
        "intervention": intervention,
    }
