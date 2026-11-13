from __future__ import annotations

import json
from typing import Any

from .schema import WorldPublicView


SYSTEM_PROMPT = (
    "You work in a synthetic, computable scientific world. Use only the public records in this request. "
    "Do not request hidden answers, private paths, oracle scores, or outside facts. "
    "Choose only one legal experiment from the menu. Return one JSON object and no Markdown fences."
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _public_context(view: WorldPublicView, *, include_source: bool = True) -> str:
    payload = {
        "world_id": view.world_id,
        "target_domain": view.target_domain,
        "source_domain": view.source_domain,
        "target_notes": view.target_notes,
        "candidate_models": list(view.candidate_models),
        "measurement": view.measurement,
        "experiments": list(view.experiments),
    }
    if include_source:
        payload["source_note"] = view.source_note
    return _json(payload)


def single_messages(view: WorldPublicView, condition: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Condition: {condition}.\n"
            "Read the target observations and the matched source note. Independently identify a useful distinction between at least two candidate mechanisms, then select one legal experiment. "
            "Return exactly the final question schema with keys: experiment_id, scientific_question, hypotheses_to_discriminate, measurement, predicted_difference, evidence_ids, uncertainty.\n\n"
            + _public_context(view)
        )},
    ]


def seq2_stage1_messages(view: WorldPublicView) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "Role: cross-disciplinary pattern extractor. Compare the target notes and source note as observations. "
            "Return exactly a shared_law_artifact JSON object with keys: shared_law_judgment (same/different/unknown), candidate_law_id (one candidate or UNKNOWN), hypothesized_shared_law, source_evidence_ids, target_evidence_ids, variable_mapping, status, brief_justification. "
            "This is a hypothesis, not a confirmed truth.\n\n" + _public_context(view)
        )},
    ]


def routed_artifact(artifact: dict[str, Any]) -> str:
    return _json(artifact)


def seq2_stage2_messages(view: WorldPublicView, artifact: dict[str, Any], condition: str) -> list[dict[str, str]]:
    target_context = _public_context(view, include_source=False)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Role: question designer in {condition}. You receive public target observations, the candidate mechanisms, the legal experiment menu, and one routed intermediate record. "
            "Use the routed record only as available evidence; do not infer hidden truth. Return exactly the final question schema with keys: experiment_id, scientific_question, hypotheses_to_discriminate, measurement, predicted_difference, evidence_ids, uncertainty.\n\n"
            "PUBLIC TARGET AND MENU:\n" + target_context + "\n\nROUTED INTERMEDIATE RECORD:\n" + routed_artifact(artifact)
        )},
    ]


def collab_source_messages(view: WorldPublicView) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "Role: source analyst. Analyze only the source note and return a compact source_pattern JSON object with keys: trend, source_evidence_ids, possible_mechanism_categories, applicability_limits. Do not select a final experiment.\n\n"
            + _json({"source_domain": view.source_domain, "source_note": view.source_note, "source_evidence_ids": list(view.source_evidence_ids)})
        )},
    ]


def collab_target_messages(view: WorldPublicView) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "Role: target analyst. Analyze the target notes and menu. Return a compact target_gap JSON object with keys: unresolved_mechanism_pairs, target_evidence_ids, candidate_interventions, rationale. Do not select a final experiment.\n\n"
            + _public_context(view, include_source=False)
        )},
    ]


def collab_synthesis_messages(view: WorldPublicView, source_pattern: dict[str, Any], target_gap: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "Role: synthesis designer. Combine the two explicit public intermediate records with the target menu and choose one legal experiment. Return exactly the final question schema with keys: experiment_id, scientific_question, hypotheses_to_discriminate, measurement, predicted_difference, evidence_ids, uncertainty.\n\n"
            "TARGET AND MENU:\n" + _public_context(view, include_source=False) +
            "\n\nSOURCE PATTERN:\n" + _json(source_pattern) +
            "\n\nTARGET GAP:\n" + _json(target_gap)
        )},
    ]


def compete_proposer_messages(view: WorldPublicView, proposer_id: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Role: independent proposer {proposer_id}. Read the same public materials independently and propose one legal experiment. Return exactly the final question schema with keys: experiment_id, scientific_question, hypotheses_to_discriminate, measurement, predicted_difference, evidence_ids, uncertainty.\n\n"
            + _public_context(view)
        )},
    ]


def compete_judge_messages(view: WorldPublicView, proposal_one: dict[str, Any], proposal_two: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "Role: evidence judge. Review two public proposals against the public evidence and legal menu. Select one proposal only if it is executable and compares at least two candidates. Return the final question schema plus selected_proposer_id. Do not use oracle scores.\n\n"
            "PUBLIC MATERIALS:\n" + _public_context(view) +
            "\n\nPROPOSAL_1:\n" + _json(proposal_one) +
            "\n\nPROPOSAL_2:\n" + _json(proposal_two)
        )},
    ]
