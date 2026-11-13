from __future__ import annotations

"""Proposal-level fingerprint helpers shared by preflight and authorization."""

from typing import Any

from .schema import sha256_json


def proposal_digest(proposal: dict[str, Any]) -> str:
    """Compute the full proposal digest without trusting its stored digest."""

    return sha256_json({key: value for key, value in proposal.items() if key != "proposal_sha256"})


def verify_proposal_digest(proposal: dict[str, Any], expected: str | None = None) -> str:
    actual = proposal_digest(proposal)
    supplied = expected if expected is not None else proposal.get("proposal_sha256")
    if not isinstance(supplied, str) or supplied != actual:
        raise ValueError(f"proposal SHA256 mismatch: expected={supplied!r}; actual={actual}")
    return actual
