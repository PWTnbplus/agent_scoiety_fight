from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path

from mini_science.config import load_config
from mini_science.prompt_audit import find_prompt_leaks
from mini_science.prompts import seq2_stage1_messages, seq2_stage2_messages, single_messages
from mini_science.public_loader import load_world
from mini_science.schema import sha256_json


ROOT = Path(__file__).resolve().parents[1]


def prompt_record(world_id: str, condition: str, stage: str, messages: list[dict[str, str]]) -> dict[str, object]:
    findings = find_prompt_leaks(messages, stage="stage1" if stage == "stage1" else None)
    serialized = "\n".join(str(item.get("content", "")) for item in messages)
    return {
        "world_id": world_id,
        "condition": condition,
        "stage": stage,
        "message_count": len(messages),
        "prompt_sha256": sha256_json(messages),
        "content_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "leak_status": "FAIL" if findings else "PASS",
        "findings": " | ".join(findings),
        "contains_private_path": bool(re.search(r"(?:[A-Za-z]:[/\\]|^|\n)[^\n]*[/\\]private[/\\]", serialized, re.IGNORECASE)),
        "contains_hidden_truth_key": any(key in serialized for key in ("true_law", "expected_relation", "oracle_mapping", "hidden_truth")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/v5p4_offline_dev.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    rows: list[dict[str, object]] = []
    for world_id in config.allowed_worlds:
        related = load_world(ROOT, world_id, "related", worlds_subdir=config.worlds_subdir)
        irrelevant = load_world(ROOT, world_id, "irrelevant", worlds_subdir=config.worlds_subdir)
        rows.append(prompt_record(world_id, "A_TARGET_ONLY", "stage2", single_messages(irrelevant, "A_TARGET_ONLY", protocol_version="v5p4")))
        rows.append(prompt_record(world_id, "B_SINGLE_RELATED", "stage2", single_messages(related, "B_SINGLE_RELATED", protocol_version="v5p4")))
        rows.append(prompt_record(world_id, "C_SEQ2_TRANSFER", "stage1", seq2_stage1_messages(related, protocol_version="v5p4")))
        rows.append(prompt_record(world_id, "C_SEQ2_TRANSFER", "stage2_preview", seq2_stage2_messages(related, {"shared_law_judgment": "unknown", "candidate_law_id": "UNKNOWN", "source_evidence_ids": [], "target_evidence_ids": [], "variable_mapping": {}}, "C_SEQ2_TRANSFER", protocol_version="v5p4")))
        rows.append(prompt_record(world_id, "D_SEQ2_BLOCK", "stage2_blocked", seq2_stage2_messages(related, {"shared_law_judgment": "unknown", "candidate_law_id": "UNKNOWN", "source_evidence_ids": [], "target_evidence_ids": [], "variable_mapping": {}, "status": "not_available"}, "D_SEQ2_BLOCK", protocol_version="v5p4")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(args.output)


if __name__ == "__main__":
    main()
