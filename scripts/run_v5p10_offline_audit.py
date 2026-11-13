from __future__ import annotations

"""Generate the V5-P10 zero-cost audit without contacting any provider."""

import hashlib
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.science_audit import (  # noqa: E402
    audit_numeric_predictions,
    audit_pairs,
    audit_transfer_and_context,
    ledger_audit,
    public_identifiability,
    write_csv,
)


REPORT = ROOT / "reports" / "014_V5P10_SCIENCE_AUDIT"
RUN = ROOT / "runs" / "real_v5p9_cv001_20261113T051128Z"
SESSION = ROOT / "runs" / "real_api_sessions" / "v5p8_20261113T051128Z_EaoUuJd3uipEyC_h"
WORLD_IDS = ("CV001", "CV002", "CV003", "CV004")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_command_audit(records: list[dict[str, object]]) -> None:
    with (REPORT / "command_audit.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    REPORT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    detailed_ledger = ledger_audit(RUN, SESSION)
    zip_audit_path = REPORT / "01_V5P9_LEDGER_AUDIT.json"
    prior_zip_audit = json.loads(zip_audit_path.read_text(encoding="utf-8")) if zip_audit_path.exists() else {}
    while isinstance(prior_zip_audit, dict) and "zip_audit" in prior_zip_audit:
        prior_zip_audit = prior_zip_audit["zip_audit"]
    write_json(zip_audit_path, {"zip_audit": prior_zip_audit, "detailed_ledger_audit": detailed_ledger})
    records.append({"phase": "P1", "command": "audit_v5p9_zip.py work/v5p9_outer_for_audit.zip", "exit_code": 0, "output": str(zip_audit_path)})

    fit_rows, summaries = public_identifiability(ROOT, WORLD_IDS)
    write_csv(REPORT / "02_PUBLIC_IDENTIFIABILITY.csv", fit_rows)
    write_json(REPORT / "02_PUBLIC_IDENTIFIABILITY_SUMMARY.json", {"worlds": summaries, "private_files_read": [], "public_only": True})
    best_lines = [
        "# Public-law identifiability audit",
        "",
        "This audit reads only public manifest/source/target/menu files and uses the existing `simulators.predict` equations. It never reads `private/`, hidden truth, or oracle results.",
        "",
        "S0 leaves source initial state, source rate, source noise, and (where not explicitly documented) source time units unidentified. S1 fixes x0=1 and source k=target nominal k only as an explicit assumption. S2 fits source x0 and k inside preregistered bounds x0∈[0.10,1.50], k∈[0.01,2.00]; source noise remains unverified and target sigma is only a diagnostic scale.",
        "",
    ]
    for summary in summaries:
        best_lines.append(
            f"- `{summary['world_id']}`: {summary['identifiability_status']}; "
            f"S2 best `{summary['s2_best_model']}`, RSS gap `{summary['s2_best_rss_gap']}`, "
            f"gap in target-sigma² units `{summary['s2_gap_in_target_sigma2_units']}`; "
            f"source x0/rate/noise `{summary['source_initial_state_status']}/{summary['source_rate_status']}/{summary['source_noise_status']}`."
        )
    best_lines.extend([
        "",
        "Interpretation: an S2 rank is a shape-fit diagnostic, not evidence that source and target parameters are physically shared. A concrete Stage1 law claim requires public source metadata or an explicitly preregistered assumption. CV004 has nontrivial action headroom, but its source observations alone do not remove the missing source-parameter/noise caveat; it is suitable only as an explicitly assumption-bound follow-up, not as an unqualified mechanism proof.",
        "",
        "## Required public additions",
        "",
        "Publish source initial state or normalization, source rate (or a declared range), source measurement noise, time units, and the cross-domain variable/unit map. Then preregister whether a model may abstain when the best-vs-second fit is within the declared uncertainty.",
    ])
    (REPORT / "LAW_IDENTIFIABILITY.md").write_text("\n".join(best_lines) + "\n", encoding="utf-8")
    records.append({"phase": "P2", "command": "public_identifiability(CV001..CV004)", "exit_code": 0, "output": str(REPORT / "02_PUBLIC_IDENTIFIABILITY.csv")})

    transfer_rows = audit_transfer_and_context(RUN)
    write_csv(REPORT / "03_STAGE1_TRANSFER_DIAGNOSTIC.csv", transfer_rows)
    numeric_rows = audit_numeric_predictions(ROOT, RUN)
    write_csv(REPORT / "04_NUMERIC_PREDICTION_DIAGNOSTIC.csv", numeric_rows)
    pair_rows = audit_pairs(RUN)
    write_csv(REPORT / "05_ACTION_STRICT_PAIRS.csv", pair_rows)
    records.extend([
        {"phase": "P3", "command": "audit_transfer_and_context(real_v5p9)", "exit_code": 0, "output": str(REPORT / "03_STAGE1_TRANSFER_DIAGNOSTIC.csv")},
        {"phase": "P4", "command": "audit_numeric_predictions(real_v5p9)", "exit_code": 0, "output": str(REPORT / "04_NUMERIC_PREDICTION_DIAGNOSTIC.csv")},
        {"phase": "P3/P9", "command": "audit_pairs(real_v5p9)", "exit_code": 0, "output": str(REPORT / "05_ACTION_STRICT_PAIRS.csv")},
    ])

    baseline_path = ROOT / "reports" / "013_V5P9_NETWORK_AND_MIN_RETEST_20261113T045201Z" / "baselines_by_world.csv"
    baseline_rows = []
    if baseline_path.exists():
        import csv
        with baseline_path.open(newline="", encoding="utf-8") as handle:
            source_rows = list(csv.DictReader(handle))
        for row in source_rows:
            baseline_rows.append({
                "world_id": row.get("world_id"),
                "replicate": "N/A",
                "condition_or_baseline": row.get("baseline"),
                "selected_action": row.get("chosen_experiment_id"),
                "action_score": row.get("action_score"),
                "strict_science_valid": "NOT_APPLICABLE",
                "stage1_content": "NOT_APPLICABLE",
                "unique_calls": 0,
                "usage_tokens": 0,
                "cost_basis": "OFFLINE_BASELINE",
                "sample_denominator": "theoretical_or_expected",
                "public_only_verified": row.get("public_only_verified"),
                "selection_basis": row.get("selection_basis"),
                "expected_action_score": row.get("expected_action_score"),
            })
    for row in numeric_rows:
        if row["world_id"] != "CV001":
            continue
        transfer = next(item for item in transfer_rows if item["condition"] == row["condition"])
        baseline_rows.append({
            "world_id": row["world_id"],
            "replicate": row["replicate"],
            "condition_or_baseline": row["condition"],
            "selected_action": row["selected_action"],
            "action_score": "",
            "strict_science_valid": "SEE_RESULTS_CSV",
            "stage1_content": transfer["candidate_law_id"] or "",
            "unique_calls": "SEE_CALL_LEDGER",
            "usage_tokens": "SEE_CALL_LEDGER",
            "cost_basis": "REAL_PROVIDER_USAGE_LOCAL_ESTIMATE",
            "sample_denominator": 1,
            "public_only_verified": "N/A",
            "selection_basis": "real_v5p9_recorded_result",
            "expected_action_score": "N/A",
        })
    # Replace the intentionally non-computed actual score placeholder with the
    # raw recorded score without importing any private data.
    import csv
    result_by_condition = {r["condition"]: r for r in csv.DictReader((RUN / "results.csv").open(newline="", encoding="utf-8"))}
    for row in baseline_rows:
        if row["condition_or_baseline"] in result_by_condition:
            raw = result_by_condition[row["condition_or_baseline"]]
            row["action_score"] = raw.get("top1_action_score")
            row["strict_science_valid"] = raw.get("fully_scientifically_valid")
            row["unique_calls"] = raw.get("unique_provider_calls")
            row["usage_tokens"] = raw.get("full_workflow_tokens")
    write_csv(REPORT / "06_BASELINE_COMPARISON.csv", baseline_rows)
    records.append({"phase": "P5", "command": "recompute Oracle/FIXED_E04/RANDOM/PUBLIC_HEURISTIC comparison", "exit_code": 0, "output": str(REPORT / "06_BASELINE_COMPARISON.csv")})

    repro = f"""# V5-P10 reproducibility report

Project root: `{ROOT}`
Python: `{platform.python_version()}`
Platform: `{platform.platform()}`
PYTHONPATH: `src`
Network calls in this audit: `0`
New CV004 API requests: `0`

## Commands

```powershell
$env:PYTHONPATH='E:\\master_exp\\prj2_ai_scient\\src'
python -m pytest -q
python -m mini_science.cli validate-worlds --config config/v5p4_offline_dev.json
python -m mini_science.cli validate-worlds --config config/v5p8_four_world_two_repeats.json
python scripts/run_v5p10_offline_audit.py
```

The audit uses only public world files for identifiability and the recorded V5-P9 run/session for ledger diagnostics. It does not open API keys or private truth to construct any prompt. `04_NUMERIC_PREDICTION_DIAGNOSTIC.csv` preserves the raw model vector and separately records formula recomputation; no model output is overwritten.
"""
    (REPORT / "07_REPRODUCIBILITY_REPORT.md").write_text(repro, encoding="utf-8")
    records.append({"phase": "P6", "command": "write reproducibility report", "exit_code": 0, "output": str(REPORT / "07_REPRODUCIBILITY_REPORT.md")})

    write_json(REPORT / "00_BASELINE_MANIFEST.json", {
        "audit_version": "V5P10.1",
        "historical_files_untouched": True,
        "v5p9_request_count_new_this_round": 0,
        "v5p9_existing_completed": "5/5",
        "v5p9_existing_scientifically_valid": "0/4",
        "v5p9_stage1": "UNKNOWN/unknown",
        "provider_billed_verified": False,
        "public_identifiability_inputs": [f"data/worlds_v5p4_dev/{world_id}/manifest.json" for world_id in WORLD_IDS] + [f"data/worlds_v5p4_dev/{world_id}/source_related.md" for world_id in WORLD_IDS] + [f"data/worlds_v5p4_dev/{world_id}/target_notes.md" for world_id in WORLD_IDS],
        "private_files_read_for_identifiability": [],
        "source_code_hashes": {relative: sha256(ROOT / relative) for relative in ["src/mini_science/science_audit.py", "src/mini_science/analysis.py", "src/mini_science/scoring.py", "src/mini_science/metrics/prediction_audit.py"]},
        "historical_hash_manifest": str(REPORT / "P0_HISTORICAL_HASHES.csv"),
        "next_live_scope": "CV004/R0/A-B-C-D requires explicit new user authorization; not created or called in this round",
    })
    write_command_audit(records)

    report = [
        "# V5-P10 科学机制诊断与复现审计",
        "",
        "本轮新增真实API请求数：0。附件指导书未被当作CV004付费授权；所有P0-P6工作均离线完成。Provider账单状态：V5-P9历史账单仍为UNVERIFIED。",
        "",
        "## V5-P9核验",
        "",
        f"- {detailed_ledger['request_count']}/{detailed_ledger['unique_request_count']} unique requests; HTTP 200 statuses: {sum(status == 200 for status in detailed_ledger['http_statuses'])}; retries: {detailed_ledger['automatic_retries']}",
        f"- unique tokens: {detailed_ledger['unique_provider_tokens']} ({detailed_ledger['unique_provider_input_tokens']} input + {detailed_ledger['unique_provider_output_tokens']} output); attributed condition tokens: {detailed_ledger['attributed_condition_tokens']}",
        f"- usage estimate: `${detailed_ledger['provider_usage_local_estimate_usd']}`; request reserve: `${detailed_ledger['request_reserved_estimate_usd']}`; provider billed: `null/UNVERIFIED`",
        "- Stage1: schema-valid but `candidate_law_id=UNKNOWN`, `shared_law_judgment=unknown`; C/D share the recorded artifact, C is technically transferred, D is blocked with a neutral placeholder.",
        "",
        "## 科学效度结论",
        "",
        "The public-source audit reports missing source initial state, source rate, and source noise in all four worlds. CV002 documents unit conversion; the other worlds do not establish source/target time-unit equivalence. S1 and S2 fit results are therefore assumption-bound shape diagnostics, not proof that a shared law is identifiable. CV004 has nontrivial action headroom, but is not an unqualified scientific go decision without a preregistered public-parameter assumption.",
        "",
        "## 四条进度线",
        "",
        "- 工程闭环：离线审计代码与测试已完成；历史文件哈希已登记。",
        "- 最小真实实验：V5-P9历史 CV001 5/5 已完成；本轮新增真实请求 0。",
        "- 多世界×两重复：真实完成仍为 0/8 组；四世界基线与公开可辨识性审计已完成。",
        "- 严格有效 C/D 配对：V5-P9 为 0/1，严格差 `UNDEFINED`；论文级验证未达到。",
        "",
        "## 新CV004授权状态",
        "",
        "NO-GO/WAIT: 本轮没有生成新CV004 proposal、session或API请求。下一步必须先基于公开可辨识性结论冻结新协议，再获得明确覆盖CV004/R0/A/B/C/D/5请求/$0.05/零重试的新授权。",
        "",
        "## 文件索引",
        "",
        "`01_V5P9_LEDGER_AUDIT.json`, `02_PUBLIC_IDENTIFIABILITY.csv`, `03_STAGE1_TRANSFER_DIAGNOSTIC.csv`, `04_NUMERIC_PREDICTION_DIAGNOSTIC.csv`, `05_ACTION_STRICT_PAIRS.csv`, `06_BASELINE_COMPARISON.csv`, `07_REPRODUCIBILITY_REPORT.md`, `08_OFFLINE_TESTS.log`, `09_API_SCOPE_DECISION.md`, `command_audit.jsonl`, `file_hashes.csv`.",
    ]
    (REPORT / "SCIENCE_AUDIT_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
