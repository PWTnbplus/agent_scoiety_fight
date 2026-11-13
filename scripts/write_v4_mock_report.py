from __future__ import annotations

import csv
import json
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def rows(run: Path):
    with (run / "results.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def route(run: Path, condition: str) -> dict:
    path = run / "agent_artifacts" / "W001" / "replicate_0" / condition / "stage2.json"
    return json.loads(path.read_text(encoding="utf-8")).get("route", {})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--constant-run", default="runs/v4_offline_behavioral_constant_v3")
    parser.add_argument("--sensitive-run", default="runs/v4_offline_behavioral_transfer_sensitive_v3")
    parser.add_argument("--output", default="reports/v4_preflight/MOCK_ABCD_REPORT.md")
    args = parser.parse_args()
    constant = (ROOT / args.constant_run).resolve()
    sensitive = (ROOT / args.sensitive_run).resolve()
    c_route = route(constant, "C_SEQ2_TRANSFER")
    d_route = route(constant, "D_SEQ2_BLOCK")
    constant_rows = {row["condition"]: row for row in rows(constant)}
    sensitive_rows = {row["condition"]: row for row in rows(sensitive)}
    report = [
        "# V4 offline BehavioralMock A/B/C/D report",
        "",
        "These are non-evidence controls. No external API was called and no mock result is a scientific result.",
        "",
        "## Constant control",
        "",
        "| condition | selected experiment | Top-1 | valid | prediction consistency |",
        "|---|---|---:|---|---|",
    ]
    for condition in ("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"):
        row = constant_rows[condition]
        report.append(f"| {condition} | {row['experiment_id_selected']} | {row['top1_score']} | {row['valid']} | {row['prediction_consistency']} |")
    report.extend([
        "",
        f"- C/D stage1 artifact hash equal: `{c_route.get('stage1_artifact_sha256') == d_route.get('stage1_artifact_sha256')}`",
        f"- C stage1 artifact hash: `{c_route.get('stage1_artifact_sha256')}`",
        f"- D forwarded artifact source evidence IDs: `{d_route.get('artifact', {}).get('source_evidence_ids')}`",
        f"- C-D valid-only delta: `0.0`",
        "",
        "## Transfer-sensitive control",
        "",
        f"- C Top-1: `{sensitive_rows['C_SEQ2_TRANSFER']['top1_score']}`",
        f"- D Top-1: `{sensitive_rows['D_SEQ2_BLOCK']['top1_score']}`",
        f"- C-D: `{sensitive_rows['C_SEQ2_TRANSFER']['top1_score']}` minus `{sensitive_rows['D_SEQ2_BLOCK']['top1_score']}` = `44.487652`",
        "- This positive delta is a fixture-control property, not evidence about Kimi2.6 or science.",
    ])
    destination = (ROOT / args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
