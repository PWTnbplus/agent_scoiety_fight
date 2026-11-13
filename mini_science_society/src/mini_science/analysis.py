from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


RESULT_FIELDS = [
    "run_id", "experiment_id", "world_id", "law_family", "seed", "condition", "society_type", "agent_count", "provider", "model_snapshot", "replicate", "question_text", "experiment_id_selected", "valid", "invalid_reason", "top1_score", "ig_selected", "ig_star", "shared_law_text", "shared_law_judgment", "candidate_law_id", "law_id_correct", "shared_law_correct", "mapping_valid", "transfer_applied", "stage1_artifact_sha256", "forwarded_artifact_sha256", "input_tokens", "output_tokens", "total_tokens", "api_calls", "billed_cost", "attributed_full_workflow_cost", "latency_ms", "run_status", "non_evidence",
]


def write_results(run_dir: str | Path, rows: list[dict[str, Any]]) -> Path:
    path = Path(run_dir) / "results.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in RESULT_FIELDS})
    return path


def read_results(run_dir: str | Path) -> list[dict[str, str]]:
    path = Path(run_dir) / "results.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_comparisons(run_dir: str | Path, rows: list[dict[str, Any]]) -> Path:
    grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for row in rows:
        try:
            grouped[(row["world_id"], str(row["replicate"]))][row["condition"]] = float(row.get("top1_score", 0.0) or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
    records: list[dict[str, Any]] = []
    for (world_id, replicate), values in sorted(grouped.items()):
        get = lambda key: values.get(key)
        def delta(left: str, right: str) -> float | str:
            return round(values[left] - values[right], 6) if left in values and right in values else ""
        records.append({
            "world_id": world_id,
            "replicate": replicate,
            "B_minus_A": delta("B_SINGLE_RELATED", "A_TARGET_ONLY"),
            "C_minus_D": delta("C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"),
            "C_minus_B": delta("C_SEQ2_TRANSFER", "B_SINGLE_RELATED"),
            "collab3_minus_B": delta("S_COLLAB3", "B_SINGLE_RELATED"),
            "compete3_minus_B": delta("S_COMPETE3", "B_SINGLE_RELATED"),
        })
    path = Path(run_dir) / "paired_deltas.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        fields = ["world_id", "replicate", "B_minus_A", "C_minus_D", "C_minus_B", "collab3_minus_B", "compete3_minus_B"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    return path


def write_report(run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    rows = read_results(run_dir)
    manifest = {}
    if (run_dir / "manifest.json").exists():
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    by_condition: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_condition[row.get("condition", "")].append(row)
    lines = [
        "# Mini Science Society run report",
        "",
        f"- run_id: `{manifest.get('run_id', run_dir.name)}`",
        f"- provider: `{manifest.get('provider', 'unknown')}`",
        f"- evidence status: `{'NON_EVIDENCE' if manifest.get('provider') == 'mock' else 'REAL_PROVIDER_PILOT'}`",
        "- scientific status: engineering pilot only; no significance or general mechanism claim",
        "",
        "## Condition summary",
        "",
        "| condition | n | valid rate | mean top-1 score | API calls | cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for condition in sorted(by_condition):
        group = by_condition[condition]
        scores = [float(row.get("top1_score", 0.0) or 0.0) for row in group]
        valid = sum(row.get("valid", "").lower() == "true" for row in group)
        calls = sum(int(float(row.get("api_calls", 0) or 0)) for row in group)
        costs = [float(row["billed_cost"]) for row in group if row.get("billed_cost") not in {"", "None"}]
        cost_text = f"{sum(costs):.8f}" if costs else "unknown"
        lines.append(f"| {condition} | {len(group)} | {valid / len(group):.3f} | {sum(scores) / len(scores):.3f} | {calls} | {cost_text} |")
    lines.extend([
        "",
        "## Fixed contrasts",
        "",
        "`B-A` is the related-source versus matched-unrelated-source contrast; `C-D` is the same stage-1 artifact with transfer enabled versus router-blocked; `C-B` is an exploratory organization contrast.",
        "",
        "The independent oracle scores discrimination within the frozen candidate set. It does not evaluate scientific novelty. `COLLAB3` and `COMPETE3` use more model calls and are not equal-compute superiority tests.",
        "",
    ])
    if any(row.get("billed_cost", "") in {"", "None"} for row in rows):
        lines.append("`BUDGET_NOT_VERIFIED`: at least one row has no provider-reported billed cost.")
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_comparisons(run_dir, rows)
    return run_dir / "report.md"
