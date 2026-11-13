from __future__ import annotations

"""Checks the exact public messages for relation/answer leakage."""

import re
from typing import Iterable


class PromptBlindingError(ValueError):
    pass


_LEAK_PATTERNS = (
    r"shared\s+dynamics\s+domain",
    r"matched\s+but\s+non[- ]comparable",
    r"non[- ]comparable\s+process",
    r"\brelated\s+source\b",
    r"\bunrelated\s+source\b",
    r"\bsource\s+is\s+(?:related|unrelated)\b",
    r"\bthis\s+is\s+the\s+(?:related|unrelated)\s+source\b",
    r"\bmatched\s+control\b",
    r"\bshared\s+law\s+is\s+(?:same|different)\b",
    r"\b(?:true_law|expected_relation|expected_candidate_law_id|oracle_mapping|oracle_results|hidden_truth|ig_star|best_experiment)\b",
    r"(?:^|[/\\])private(?:[/\\])",
)

_COMPILED = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _LEAK_PATTERNS)
_ACTION_IDS = re.compile(r"\bE(?:0[1-8])\b", re.IGNORECASE)


def find_prompt_leaks(messages: Iterable[dict[str, str]], *, stage: str | None = None) -> list[str]:
    """Return concrete leakage findings for the messages actually sent."""
    findings: list[str] = []
    for index, message in enumerate(messages):
        content = str(message.get("content", ""))
        for pattern in _COMPILED:
            match = pattern.search(content)
            if match:
                findings.append(f"message[{index}]::{match.group(0)}")
        if stage == "stage1" and _ACTION_IDS.search(content):
            findings.append(f"message[{index}]::candidate_action_id_in_stage1")
    return findings


def assert_prompt_blinded(messages: Iterable[dict[str, str]], *, stage: str | None = None) -> None:
    findings = find_prompt_leaks(messages, stage=stage)
    if findings:
        raise PromptBlindingError("public prompt blinding failed: " + "; ".join(findings[:8]))
