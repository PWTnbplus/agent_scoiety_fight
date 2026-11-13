from __future__ import annotations

"""Evidence visibility and citation permissions derived from routed payloads."""

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class EvidencePolicy:
    direct_ids: frozenset[str]
    mediated_ids: frozenset[str] = frozenset()

    @property
    def allowed_ids(self) -> frozenset[str]:
        return self.direct_ids | self.mediated_ids

    def validate_citation(self, evidence_id: str) -> bool:
        return evidence_id in self.allowed_ids

    def classify(self, evidence_id: str) -> str:
        if evidence_id in self.direct_ids:
            return "direct"
        if evidence_id in self.mediated_ids:
            return "mediated"
        return "unseen"

    def validate_citations(self, evidence_ids: Iterable[str]) -> tuple[bool, list[str]]:
        unseen = sorted({str(value) for value in evidence_ids} - self.allowed_ids)
        return not unseen, unseen


def _valid_public_ids(values: Any, valid_source_ids: set[str]) -> frozenset[str]:
    if not isinstance(values, list):
        return frozenset()
    return frozenset(str(value) for value in values if str(value) in valid_source_ids)


def policy_for_route(view: Any, *, route: dict[str, Any] | None = None, condition: str | None = None, intermediate_records: Iterable[dict[str, Any]] = ()) -> EvidencePolicy:
    """Build permissions from what was actually routed, not from a label alone."""
    direct = set(view.target_evidence_ids)
    condition = condition or ""
    if condition in {"A_TARGET_ONLY", "B_SINGLE_RELATED", "COMPETE3", "S_COMPETE3"}:
        direct.update(view.source_evidence_ids)
    mediated: set[str] = set()
    if route and route.get("transfer_applied"):
        artifact = route.get("artifact") or {}
        mediated.update(_valid_public_ids(artifact.get("source_evidence_ids"), set(view.source_evidence_ids)))
    for record in intermediate_records:
        mediated.update(_valid_public_ids(record.get("source_evidence_ids"), set(view.source_evidence_ids)))
        mediated.update(_valid_public_ids(record.get("target_evidence_ids"), set(view.target_evidence_ids)))
    return EvidencePolicy(frozenset(direct), frozenset(mediated - direct))


def policy_from_payload(view: Any, payload: dict[str, Any], *, direct_ids: Iterable[str] = ()) -> EvidencePolicy:
    direct = set(str(value) for value in direct_ids)
    mediated = set()
    for key in ("source_evidence_ids", "target_evidence_ids", "evidence_ids"):
        value = payload.get(key)
        if isinstance(value, list):
            mediated.update(str(item) for item in value)
    valid = set(view.target_evidence_ids) | set(view.source_evidence_ids)
    return EvidencePolicy(frozenset(direct & valid), frozenset((mediated & valid) - direct))
