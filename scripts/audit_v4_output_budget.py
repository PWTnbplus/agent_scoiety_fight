from __future__ import annotations

import json
from pathlib import Path

from mini_science.budget import estimate_tokens
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    config = load_config(ROOT / "config" / "v4_pilot_offline.json")
    final_sample = {
        "experiment_id": "E04",
        "scientific_question": "Which candidate mechanisms make the most different predictions under the selected measurement and why is that distinction scientifically informative?",
        "hypotheses_to_discriminate": ["EXP_DECAY", "HYPERBOLIC_DECAY", "STRETCHED_EXP", "BI_EXP"],
        "predicted_values": {"EXP_DECAY": 0.19, "HYPERBOLIC_DECAY": 0.37, "STRETCHED_EXP": 0.13, "BI_EXP": 0.18},
        "measurement": "normalized_state",
        "predicted_difference": "The four candidate models produce distinct normalized-state predictions at the selected time; the values are computed from the public nominal parameter and are subject to observation noise.",
        "evidence_ids": ["T01", "T02", "S01", "S02"],
        "uncertainty": "The public nominal rate is an estimate and the source/target domain mapping is provisional.",
    }
    stage1_sample = {
        "shared_law_judgment": "same",
        "candidate_law_id": "EXP_DECAY",
        "hypothesized_shared_law": "A decay relationship with a provisional time/state mapping.",
        "source_evidence_ids": ["S01", "S02", "S03", "S04"],
        "target_evidence_ids": ["T01", "T02"],
        "variable_mapping": {"source_state": "target_state", "source_time": "target_time"},
        "status": "hypothesis",
        "brief_justification": "The observed source and target trajectories show a provisional structural correspondence, but the mapping and quantitative predictions remain uncertain and no optimal experiment is claimed.",
    }
    plan = pilot_request_plan(ROOT, config, worlds=["W001"], conditions=list(config.conditions), repeats=1)
    seq2_cap = max(int(item["max_output_tokens"]) for item in plan if item["stage"] in {"stage1", "stage2"} and item["agent_name"] != "single_question_designer")
    samples = {"final_question_typical": (final_sample, seq2_cap), "shared_law_typical": (stage1_sample, seq2_cap)}
    rows = []
    for name, (value, cap) in samples.items():
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        tokens = estimate_tokens(encoded)
        rows.append((name, tokens, cap, tokens / cap, tokens < cap * 0.8))
    lines = [
        "# V4 schema/output budget audit",
        "",
        "The estimator is the same conservative character/token estimator used by the local budget planner. This is a preflight bound, not a provider billing statement.",
        "",
        "## Frozen schemas",
        "",
        "- final question required fields: `experiment_id`, `scientific_question`, `hypotheses_to_discriminate`, `predicted_values`, `measurement`, `predicted_difference`, `evidence_ids`, `uncertainty`;",
        "- stage1 required fields: `shared_law_judgment`, `candidate_law_id`, `hypothesized_shared_law`, `source_evidence_ids`, `target_evidence_ids`, `variable_mapping`, `status`, `brief_justification`;",
        "- stage1 may not carry an oracle action, IG, or `predicted_values` field;",
        "- final mechanism and evidence fields are exact IDs; Markdown fences and explanatory prefixes are invalid.",
        "",
        "## Typical complete JSON sizes",
        "",
        "| sample | estimated output tokens | cap | fraction | below 80% cap |",
        "|---|---:|---:|---:|---|",
    ]
    for name, tokens, cap, fraction, safe in rows:
        lines.append(f"| {name} | {tokens} | {cap} | {fraction:.3f} | {safe} |")
    lines.extend([
        "",
        "The legacy 450-token cap leaves only a narrow margin for the typical final JSON (389 tokens, 86.4% of cap), so it is not retained for V4. V4 freezes 600 tokens for stage1/C/D; A/B retain 900 tokens. No output normalization or post-hoc completion is permitted.",
        "",
        f"- exact plan requests: `{len(plan)}`",
        f"- planned local upper-bound estimate: `${sum(float(item['estimated_cost_usd']) for item in plan):.7f}`",
        f"- plan output caps: `{sorted(set(int(item['max_output_tokens']) for item in plan))}`",
        "- truncation handling: `finish_reason` length/max_tokens/truncated is rejected and counted as a failed attempt.",
    ])
    destination = ROOT / "reports" / "v4_real_pre_gate" / "SCHEMA_OUTPUT_BUDGET_AUDIT.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
