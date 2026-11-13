from __future__ import annotations

from copy import deepcopy
from typing import Any

from .schema import sha256_json


def route_shared_law_artifact(artifact: dict[str, Any], transfer_applied: bool) -> dict[str, Any]:
    """Serialize C/D routing; D receives no informative stage-1 fields."""
    stage1_hash = sha256_json(artifact)
    if transfer_applied:
        forwarded = deepcopy(artifact)
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
    }
