from __future__ import annotations

"""Conservative, prompt-aware budget plans for real-provider stages."""

import json
from pathlib import Path
import re
from typing import Any

from .budget import estimate_tokens
from .config import ExperimentConfig
from .prompts import (
    collab_source_messages,
    collab_synthesis_messages,
    collab_target_messages,
    compete_judge_messages,
    compete_proposer_messages,
    seq2_stage1_messages,
    seq2_stage2_messages,
    single_messages,
)
from .public_loader import load_world
from .schema import sha256_json


DEFAULT_INPUT_COST_PER_1K = 0.00095
DEFAULT_OUTPUT_COST_PER_1K = 0.004
SINGLE_OUTPUT_TOKENS = 900
SEQ2_OUTPUT_TOKENS = 450
STAGE1_ARTIFACT_TOKEN_CAP = 450
V4_SEQ2_OUTPUT_TOKENS = 600
V5P4_SEQ2_OUTPUT_TOKENS = 600


def _input_tokens(messages: list[dict[str, str]]) -> int:
    return estimate_tokens(json.dumps(messages, ensure_ascii=False))


def _record(
    *,
    request_id: str,
    stage: str,
    agent_name: str,
    world_id: str,
    condition: str,
    messages: list[dict[str, str]],
    max_output_tokens: int,
    input_token_upper_bound: int | None = None,
    input_rate: float = DEFAULT_INPUT_COST_PER_1K,
    output_rate: float = DEFAULT_OUTPUT_COST_PER_1K,
) -> dict[str, Any]:
    exact_input = _input_tokens(messages)
    input_upper = max(exact_input, int(input_token_upper_bound or exact_input))
    estimated_cost = (input_upper / 1000.0) * input_rate + (max_output_tokens / 1000.0) * output_rate
    return {
        "request_id": request_id,
        "stage": stage,
        "agent_name": agent_name,
        "world_id": world_id,
        "condition": condition,
        "prompt_hash": sha256_json(messages),
        "prompt_input_tokens": exact_input,
        "input_token_upper_bound": input_upper,
        "max_output_tokens": max_output_tokens,
        "estimated_cost_usd": estimated_cost,
        "cost_basis": "LOCAL_ESTIMATE_UPPER_BOUND",
    }


def check_api_request_plan(
    *,
    max_output_tokens: int,
    input_rate: float = DEFAULT_INPUT_COST_PER_1K,
    output_rate: float = DEFAULT_OUTPUT_COST_PER_1K,
) -> list[dict[str, Any]]:
    messages = [{"role": "user", "content": 'Reply with exactly {"status":"ok"}.'}]
    return [_record(request_id="check-api:attempt1", stage="check-api", agent_name="contract_check", world_id="-", condition="-", messages=messages, max_output_tokens=max_output_tokens, input_rate=input_rate, output_rate=output_rate)]


def probe_request_plan(
    project_root: str | Path,
    config: ExperimentConfig,
    *,
    world_id: str,
    role: str,
    max_output_tokens: int,
    input_rate: float = DEFAULT_INPUT_COST_PER_1K,
    output_rate: float = DEFAULT_OUTPUT_COST_PER_1K,
) -> list[dict[str, Any]]:
    view = load_world(project_root, world_id, "related", worlds_subdir=config.worlds_subdir)
    if role == "single_question_designer":
        messages = single_messages(view)
        stage = "stage2"
    elif role == "pattern_extractor":
        messages = seq2_stage1_messages(view)
        stage = "stage1"
    elif role == "question_designer":
        messages = seq2_stage2_messages(view, {"status": "not_available", "source_evidence_ids": [], "target_evidence_ids": []})
        stage = "stage2"
    else:
        raise ValueError(f"unsupported probe role: {role}")
    return [_record(request_id=f"{world_id}_PROBE:PROBE:{stage}:{role}:attempt1", stage="probe-role", agent_name=role, world_id=world_id, condition="PROBE", messages=messages, max_output_tokens=max_output_tokens, input_rate=input_rate, output_rate=output_rate)]


def _condition_view(project_root: Path, world_id: str, condition: str, config: ExperimentConfig):
    source_variant = "irrelevant" if condition == "A_TARGET_ONLY" else "related"
    return load_world(project_root, world_id, source_variant=source_variant, worlds_subdir=config.worlds_subdir)


def pilot_request_plan(
    project_root: str | Path,
    config: ExperimentConfig,
    *,
    worlds: list[str],
    conditions: list[str],
    repeats: int,
    request_namespace: str | None = None,
    replicate_indices: list[int] | None = None,
    input_rate: float = DEFAULT_INPUT_COST_PER_1K,
    output_rate: float = DEFAULT_OUTPUT_COST_PER_1K,
) -> list[dict[str, Any]]:
    """Build the complete real request plan before any adapter call.

    A/B use their actual public prompts with 900 output tokens. The seq2
    stage-1 and stage-2 requests use their actual public prompt bases with
    450 output tokens for the historical V5-P3 protocol and 600 output tokens
    for V5-P4. Stage-2 input adds the full stage-1 output cap so the
    estimate cannot undercount C/D before stage-1 exists.
    """
    root = Path(project_root).resolve()
    if request_namespace is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,100}", str(request_namespace)):
        raise ValueError("request_namespace must be a stable alphanumeric namespace")
    v5_protocol = str(config.score_version).startswith("v5p")
    protocol_version = "v5p11" if str(config.score_version).startswith("v5p11") else ("v5p8" if str(config.score_version).startswith("v5p8") else ("v5p4" if str(config.score_version).startswith("v5p4") else ("v5p3" if str(config.score_version).startswith("v5p3") else ("v5p2" if v5_protocol else "v4"))))
    seq2_output_tokens = V5P4_SEQ2_OUTPUT_TOKENS if str(config.score_version).startswith(("v5p4", "v5p8", "v5p11")) else (V4_SEQ2_OUTPUT_TOKENS if str(config.score_version).startswith("v4") else SEQ2_OUTPUT_TOKENS)
    stage1_artifact_cap = V5P4_SEQ2_OUTPUT_TOKENS if str(config.score_version).startswith(("v5p4", "v5p8", "v5p11")) else (V4_SEQ2_OUTPUT_TOKENS if str(config.score_version).startswith("v4") else STAGE1_ARTIFACT_TOKEN_CAP)
    records: list[dict[str, Any]] = []
    supported = {"A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK", "E_SEQ2_IRRELEVANT_TRANSFER", "F_SEQ2_MISALIGNED_TRANSFER", "S_COLLAB3", "S_COMPETE3"}
    unknown = sorted(set(conditions) - supported)
    if unknown:
        raise ValueError(f"real pilot preflight does not support conditions: {', '.join(unknown)}")
    selected_replicates = list(range(repeats)) if replicate_indices is None else sorted({int(value) for value in replicate_indices})
    if not selected_replicates or (replicate_indices is not None and any(value < 0 or value >= repeats for value in selected_replicates)):
        raise ValueError("replicate_indices must select positive absolute repeat indices within the configured design")
    for world_id in worlds:
        for replicate in selected_replicates:
            pair_prefix = f"{request_namespace}_" if request_namespace else ("V5P11_" if str(config.score_version).startswith("v5p11") else ("V5P8_" if str(config.score_version).startswith("v5p8") else ""))
            pair_id = f"{pair_prefix}{world_id}_R{replicate}"
            for condition in conditions:
                if condition in {"A_TARGET_ONLY", "B_SINGLE_RELATED"}:
                    view = _condition_view(root, world_id, condition, config)
                    records.append(_record(request_id=f"{pair_id}:{condition}:stage2:single_question_designer:attempt1", stage="stage2", agent_name="single_question_designer", world_id=world_id, condition=condition, messages=single_messages(view, condition, protocol_version=protocol_version), max_output_tokens=SINGLE_OUTPUT_TOKENS, input_rate=input_rate, output_rate=output_rate))
                elif condition in {"S_COLLAB3", "S_COMPETE3"}:
                    view = _condition_view(root, world_id, condition, config)
                    if condition == "S_COLLAB3":
                        society_calls = (
                            ("source_analyst", collab_source_messages(view)),
                            ("target_analyst", collab_target_messages(view)),
                            ("synthesis_designer", collab_synthesis_messages(view, {}, {})),
                        )
                    else:
                        society_calls = (
                            ("proposer_1", compete_proposer_messages(view, "P1")),
                            ("proposer_2", compete_proposer_messages(view, "P2")),
                            ("evidence_judge", compete_judge_messages(view, {}, {})),
                        )
                    for agent_name, messages in society_calls:
                        records.append(_record(request_id=f"{pair_id}:{condition}:stage2:{agent_name}:attempt1", stage="stage2", agent_name=agent_name, world_id=world_id, condition=condition, messages=messages, max_output_tokens=300, input_token_upper_bound=_input_tokens(messages) + 1200 if agent_name in {"synthesis_designer", "evidence_judge"} else None, input_rate=input_rate, output_rate=output_rate))
            seq2 = [condition for condition in conditions if condition in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK", "E_SEQ2_IRRELEVANT_TRANSFER", "F_SEQ2_MISALIGNED_TRANSFER"}]
            if seq2:
                owner = "C_SEQ2_TRANSFER" if "C_SEQ2_TRANSFER" in seq2 else seq2[0]
                view = _condition_view(root, world_id, owner, config)
                stage1_messages = seq2_stage1_messages(view, protocol_version=protocol_version)
                records.append(_record(request_id=f"{pair_id}:{owner}:stage1:pattern_extractor:attempt1", stage="stage1", agent_name="pattern_extractor", world_id=world_id, condition=owner, messages=stage1_messages, max_output_tokens=seq2_output_tokens, input_rate=input_rate, output_rate=output_rate))
                worst_artifact = {
                    "shared_law_judgment": "unknown",
                    "candidate_law_id": "UNKNOWN",
                    "hypothesized_shared_law": "x" * 120,
                    "source_evidence_ids": ["S01", "S02"],
                    "target_evidence_ids": ["T01", "T02"],
                    "variable_mapping": {"source_state": "target_state", "source_time": "target_time"},
                    "status": "supported_or_uncertain",
                    "brief_justification": "x" * 120,
                }
                for condition in seq2:
                    view = _condition_view(root, world_id, condition, config)
                    blocked_artifact = {
                        "shared_law_judgment": "unknown",
                        "candidate_law_id": "UNKNOWN",
                        "hypothesized_shared_law": "no intermediate record was transferred in this condition",
                        "source_evidence_ids": [],
                        "target_evidence_ids": [],
                        "variable_mapping": {},
                        "status": "not_available",
                        "brief_justification": "The routing layer supplied a neutral placeholder.",
                    }
                    stage2_artifact = worst_artifact if condition == "C_SEQ2_TRANSFER" else blocked_artifact
                    stage2_messages = seq2_stage2_messages(view, stage2_artifact, condition, protocol_version=protocol_version)
                    records.append(_record(request_id=f"{pair_id}:{condition}:stage2:question_designer:attempt1", stage="stage2", agent_name="question_designer", world_id=world_id, condition=condition, messages=stage2_messages, max_output_tokens=seq2_output_tokens, input_token_upper_bound=_input_tokens(stage2_messages) + stage1_artifact_cap, input_rate=input_rate, output_rate=output_rate))
    for item in records:
        pair_id = str(item["request_id"]).split(":", 1)[0]
        item["pair_id"] = pair_id
        item["replicate"] = int(pair_id.rsplit("_R", 1)[1])
        item["stage1_shared_key"] = pair_id
    return records
