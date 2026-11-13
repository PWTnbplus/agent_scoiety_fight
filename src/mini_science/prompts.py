from __future__ import annotations

import json
from typing import Any

from .schema import WorldPublicView


COMMON_POLICY = (
    "You work in a synthetic, computable scientific world. Use only the public records in this request. "
    "Do not request hidden answers, private paths, oracle scores, or outside facts. "
    "Return exactly one JSON object and no Markdown fences, prose, or code fences. "
    "Mechanism fields must use exact candidate_models IDs, never explanatory sentences. Evidence IDs must be a list of individual visible IDs exactly as shown, never a range or natural-language collection."
)

SYSTEM_PROMPT = (
    "You work in a synthetic, computable scientific world. Use only the public records in this request. "
    "Do not request hidden answers, private paths, oracle scores, or outside facts. "
    "Choose only one legal experiment from the menu. Return exactly one JSON object and no Markdown fences, prose, or code fences. "
    "Mechanism fields must use exact candidate_models IDs, never explanatory sentences. Evidence IDs must be a list of individual visible IDs exactly as shown, never a range or natural-language collection."
)

PATTERN_EXTRACTOR_SYSTEM = COMMON_POLICY + " The pattern-extractor role must not select an experiment or rank actions."

QUESTION_DESIGNER_SYSTEM = COMMON_POLICY + " The question-designer role may select exactly one legal experiment from the supplied menu."


FINAL_OUTPUT_CONTRACT = (
    "The final JSON object must contain exactly these scientific fields: experiment_id, scientific_question, "
    "hypotheses_to_discriminate, predicted_values, measurement, predicted_difference, evidence_ids, uncertainty. "
    "hypotheses_to_discriminate must contain at least two exact IDs from candidate_models. "
    "predicted_values must be an object mapping each listed hypothesis ID to a finite numeric prediction for the selected menu action. "
    "Do not put units, explanations, or mechanism names outside the exact IDs in those fields. "
    "evidence_ids must contain individual visible IDs only."
)

V5P2_FINAL_OUTPUT_CONTRACT = (
    FINAL_OUTPUT_CONTRACT + " selected_action. selected_action must be an object with exactly experiment_id, x0, and measure_t copied from the same menu item."
)

V5P8_FINAL_OUTPUT_CONTRACT = (
    V5P2_FINAL_OUTPUT_CONTRACT +
    " Before emitting JSON, choose the experiment_id and copy its exact x0 and measure_t from the same menu item. "
    "Then substitute that selected x0 and measure_t into each public candidate equation using the public nominal candidate-rate k. "
    "Compute one finite numeric predicted_values entry for every listed candidate model, keep at least six decimal places, "
    "and do not reuse values from a different menu action or from the observed data."
)

V5P11_FINAL_OUTPUT_CONTRACT = V5P8_FINAL_OUTPUT_CONTRACT


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


def _stage1_context(view: WorldPublicView) -> str:
    """Observation-only context for Stage1; no candidate action menu is exposed."""
    observation_lines = []
    for line in view.target_notes.splitlines():
        lowered = line.lower()
        if "choose exactly one experiment" in lowered or "public menu" in lowered:
            continue
        observation_lines.append(line)
    payload = {
        "world_id": view.world_id,
        "target_domain": view.target_domain,
        "source_domain": view.source_domain,
        "target_observations": "\n".join(observation_lines),
        "source_note": view.source_note,
        "candidate_models": list(view.candidate_models),
        "measurement": view.measurement,
        "public_variable_mapping_schema": {
            "source": list(view.source_variable_ids),
            "target": list(view.target_variable_ids),
            "mapping_rule": "map each source slot to exactly one target slot; use only these exact fields",
        },
    }
    return _json(payload)


def single_messages(view: WorldPublicView, condition: str | None = None, *, protocol_version: str = "v4") -> list[dict[str, str]]:
    system = SYSTEM_PROMPT if protocol_version == "v4" else QUESTION_DESIGNER_SYSTEM
    contract = FINAL_OUTPUT_CONTRACT if protocol_version == "v4" else (V5P8_FINAL_OUTPUT_CONTRACT if protocol_version in {"v5p8", "v5p11"} else V5P2_FINAL_OUTPUT_CONTRACT)
    include_source = not (protocol_version == "v5p11" and condition == "A_TARGET_ONLY")
    materials = "Read the target observations only." if not include_source else "Read the target observations and the public source note."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            materials + " Independently identify a useful distinction between at least two candidate mechanisms, then select one legal experiment. "
            + contract + "\n\n"
            + _public_context(view, include_source=include_source)
        )},
    ]


def seq2_stage1_messages(view: WorldPublicView, *, protocol_version: str = "v4") -> list[dict[str, str]]:
    if protocol_version == "v4":
        context = _public_context(view)
        system = SYSTEM_PROMPT
    else:
        context = _stage1_context(view)
        system = PATTERN_EXTRACTOR_SYSTEM
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            "Role: cross-disciplinary pattern extractor. Compare the target notes and source note as observations. "
            "Return exactly a shared_law_artifact JSON object with keys: shared_law_judgment (same/different/unknown), candidate_law_id (one candidate or UNKNOWN), hypothesized_shared_law, source_evidence_ids, target_evidence_ids, variable_mapping, status, brief_justification. "
            "Stage1 must not select an optimal experiment or claim an oracle ranking. It should report only the provisional law, mapping, evidence, and limitations. This is a hypothesis, not a confirmed truth.\n\n" + context
        )},
    ]


def routed_artifact(artifact: dict[str, Any]) -> str:
    return _json(artifact)


def seq2_stage2_messages(view: WorldPublicView, artifact: dict[str, Any], condition: str | None = None, *, protocol_version: str = "v4") -> list[dict[str, str]]:
    system = SYSTEM_PROMPT if protocol_version == "v4" else QUESTION_DESIGNER_SYSTEM
    contract = FINAL_OUTPUT_CONTRACT if protocol_version == "v4" else (V5P8_FINAL_OUTPUT_CONTRACT if protocol_version in {"v5p8", "v5p11"} else V5P2_FINAL_OUTPUT_CONTRACT)
    target_context = _public_context(view, include_source=False)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            "Role: question designer. You receive public target observations, the candidate mechanisms, the legal experiment menu, and one routed intermediate record. "
            "Use the routed record only as available evidence; do not infer hidden truth. " + contract + "\n\n"
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
            "Role: synthesis designer. Combine the two explicit public intermediate records with the target menu and choose one legal experiment. " + FINAL_OUTPUT_CONTRACT + "\n\n"
            "TARGET AND MENU:\n" + _public_context(view, include_source=False) +
            "\n\nSOURCE PATTERN:\n" + _json(source_pattern) +
            "\n\nTARGET GAP:\n" + _json(target_gap)
        )},
    ]


def compete_proposer_messages(view: WorldPublicView, proposer_id: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Role: independent proposer {proposer_id}. Read the same public materials independently and propose one legal experiment. " + FINAL_OUTPUT_CONTRACT + "\n\n"
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
