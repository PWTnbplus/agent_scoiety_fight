from __future__ import annotations

"""Run the V5-P4 zero-cost acceptance commands and preserve raw output."""

import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "005_V5P4_READY_FOR_AUTH"


def execute(args: list[str]) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = "$ " + " ".join(args) + "\nexit_code=" + str(result.returncode) + "\nSTDOUT\n" + result.stdout + "\nSTDERR\n" + result.stderr + "\n"
    return result.returncode, output


def unique_run_dir(name: str) -> Path:
    base = REPORT / "offline_runs" / name
    candidate = base
    counter = 2
    while candidate.exists():
        candidate = base.with_name(f"{name}_{counter}")
        counter += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []
    code, output = execute([sys.executable, "-m", "pytest", "-q"])
    (REPORT / "OFFLINE_TESTS.log").write_text(output, encoding="utf-8")
    checks.append(f"pytest_exit_code={code}")
    code, output = execute([sys.executable, "-m", "mini_science.cli", "validate-worlds", "--config", "config/v5p4_offline_dev.json"])
    (REPORT / "VALIDATE_WORLDS.log").write_text(output, encoding="utf-8")
    checks.append(f"validate_worlds_exit_code={code}")
    code, output = execute([sys.executable, "-m", "pytest", "-q", "tests/test_v5p4_session_isolation.py", "tests/test_v5p4_prompt_blinding.py", "tests/test_v5p4_budget_prompt_parity.py", "tests/test_v5p4_paid_failfast.py", "tests/test_v5p4_conditional_ig.py"])
    (REPORT / "SESSION_ISOLATION_TEST.log").write_text(output, encoding="utf-8")
    checks.append(f"new_regression_exit_code={code}")

    positive_dir = unique_run_dir("positive_transfer_sensitive")
    code, output = execute([sys.executable, "-m", "mini_science.cli", "pilot", "--config", "config/v5p4_offline_dev.json", "--provider", "behavioral-mock", "--worlds", "CV001", "--conditions", "A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK", "--run-dir", str(positive_dir), "--behavioral-scenario", "transfer_sensitive"])
    checks.append(f"positive_mock_exit_code={code}")
    (REPORT / "POSITIVE_MOCK.log").write_text(output, encoding="utf-8")

    negative_lines = ["V5P4 offline negative/contrast runs; provider=behavioral-mock; NON_EVIDENCE only.", ""]
    for scenario in ("constant", "bad_stage1", "bad_final", "citation_leak"):
        run_dir = unique_run_dir(scenario)
        code, output = execute([sys.executable, "-m", "mini_science.cli", "pilot", "--config", "config/v5p4_offline_dev.json", "--provider", "behavioral-mock", "--worlds", "CV001", "--conditions", "A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK", "--run-dir", str(run_dir), "--behavioral-scenario", scenario])
        negative_lines.append(f"SCENARIO={scenario} exit_code={code} run_dir={run_dir}")
        negative_lines.append(output)
        results = run_dir / "results.csv"
        if results.exists():
            rows = list(csv.DictReader(results.open(encoding="utf-8")))
            negative_lines.append(f"rows={len(rows)} valid={sum(row.get('valid') == 'True' for row in rows)} invalid={sum(row.get('valid') == 'False' for row in rows)}")
        negative_lines.append("")
    (REPORT / "OFFLINE_NEGATIVE_TESTS.log").write_text("\n".join(negative_lines), encoding="utf-8")
    checks.append("negative_scenarios=4")
    (REPORT / "OFFLINE_CHECK_SUMMARY.txt").write_text("V5P4 offline checks\n" + "\n".join(checks) + "\nreal_api_calls_this_round=0\ncompleted_at=" + datetime.now(timezone.utc).isoformat() + "\n", encoding="utf-8")
    print("\n".join(checks))


if __name__ == "__main__":
    main()
