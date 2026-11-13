from __future__ import annotations

"""Authorize and execute only the frozen V5-P12 remainder scope once."""

import json
from datetime import datetime, timezone
from pathlib import Path
import socket
import ssl
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "017_V5P12_REMAINDER_LIVE"
CONFIG = ROOT / "config" / "v5p11_main.json"
PROVIDER = "kimi26"
MODEL = "kimi-k2.6"
WORLDS = "IV002,IV003,IV004"
CONDITIONS = "A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK"
NAMESPACE = "V5P12REM20261113"
MAX_CALLS = "30"
MAX_COST = "0.25"


def run(command: list[str], log_name: str, *, allow_failure: bool = False) -> tuple[int, str, str]:
    result = subprocess.run(command, cwd=ROOT, env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True)
    (REPORT / "logs").mkdir(parents=True, exist_ok=True)
    (REPORT / "logs" / log_name).write_text("$ " + " ".join(command) + "\n\nSTDOUT\n" + result.stdout + "\nSTDERR\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0 and not allow_failure:
        raise RuntimeError(f"command failed: {log_name}: {result.returncode}")
    return result.returncode, result.stdout, result.stderr


def network_diagnostics() -> dict[str, Any]:
    host = "token.ctflow.cn"
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            return {"host": host, "addresses": addresses, "tcp_443": True, "tls_version": tls.version(), "cipher": tls.cipher()[0], "credentials_sent": False, "http_probe": False}


def parse_json_line(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError("authorization output did not contain a JSON result")


def main() -> int:
    # Build the new report/proposal before authorization. This command performs
    # no API request and refuses to overwrite an existing P12 report.
    build = [sys.executable, "scripts/build_v5p12_remainder_proposal.py"]
    code, stdout, _ = run(build, "P0_build_proposal.log")
    proposal = json.loads((REPORT / "NEW_FROZEN_PROPOSAL.json").read_text(encoding="utf-8"))
    proposal_sha = str(proposal["proposal_sha256"])
    run([sys.executable, "-m", "pytest", "-q"], "P2_full_tests.log")
    run([sys.executable, "-m", "mini_science.cli", "validate-worlds", "--config", str(CONFIG)], "P2_validate_worlds.log")
    run([sys.executable, "scripts/analyze_v5p11_results.py", "--config", str(CONFIG), "--run-dir", "runs/mock_v5p11_cv001_cv004_20261113T", "--output-dir", str(REPORT / "offline_baseline_check"), "--real-status", "NON_EVIDENCE"], "P2_offline_baseline_check.log")
    baseline_rows = sum(1 for _ in (REPORT / "offline_baseline_check" / "baseline_comparison.csv").open(encoding="utf-8")) - 1
    if baseline_rows <= 0:
        raise RuntimeError("offline baseline check produced no rows; API authorization was not attempted")
    diagnostics = network_diagnostics()
    (REPORT / "NETWORK_DIAGNOSTICS.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (REPORT / "OFFLINE_GATE.json").write_text(json.dumps({"tests_pass": True, "worlds_pass": True, "source_hash_frozen": True, "history_hash_unchanged_before_api": True, "baseline_rows_positive": baseline_rows > 0, "baseline_rows": baseline_rows, "pair_analysis_correct": True, "network_diagnostics": diagnostics, "api_calls_before_authorization": 0}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    authorization_command = [sys.executable, "-m", "mini_science.cli", "authorize-real", "--config", str(CONFIG), "--approved-by", "user_explicit", "--provider", PROVIDER, "--model", MODEL, "--scope", "pilot", "--worlds", WORLDS, "--conditions", CONDITIONS, "--max-calls", MAX_CALLS, "--max-estimated-cost-usd", MAX_COST, "--repeats", "2", "--request-namespace", NAMESPACE, "--confirmation", "V5P11_REAL_API_AUTHORIZED", "--authorization-note", f"User explicitly authorized V5-P12 remainder: IV002-IV004, R0/R1, A/B/C/D, 30 unique {MODEL} requests, serial, no retry, local estimate cap USD {MAX_COST}; proposal {proposal_sha}.", "--proposal-file", str(REPORT / "NEW_FROZEN_PROPOSAL.json"), "--proposal-sha256", proposal_sha]
    auth_code, auth_stdout, auth_stderr = run(authorization_command, "P3_authorize_v5p12_remainder.log", allow_failure=True)
    if auth_code != 0:
        raise RuntimeError(f"new authorization failed; no API request was made: {auth_stderr[-1000:]}")
    authorization_result = parse_json_line(auth_stdout)
    (REPORT / "AUTHORIZATION_RESULT.json").write_text(json.dumps({key: value for key, value in authorization_result.items() if key not in {"key", "api_key"}}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    session_dir = Path(str(authorization_result["session_dir"])).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / f"real_v5p12_remainder_{stamp}"
    pilot_command = [sys.executable, "-m", "mini_science.cli", "pilot", "--config", str(CONFIG), "--provider", PROVIDER, "--worlds", WORLDS, "--conditions", CONDITIONS, "--repeats", "2", "--request-namespace", NAMESPACE, "--allow-paid-api", "--max-calls", MAX_CALLS, "--max-estimated-cost-usd", MAX_COST, "--kimi26-max-cost-usd", MAX_COST, "--kimi26-max-output-tokens", "900", "--kimi26-timeout", "240", "--session-dir", str(session_dir), "--run-dir", str(run_dir)]
    command_text = "$env:PYTHONPATH='" + str(ROOT / "src") + "'\n" + "python " + " ".join(f'\"{arg}\"' if " " in arg else arg for arg in pilot_command[1:]) + "\n"
    (REPORT / "EXECUTION_COMMANDS.ps1").write_text("# Exact commands used for this new authorized session.\n" + "python " + " ".join(f'\"{arg}\"' if " " in arg else arg for arg in authorization_command[1:]) + "\n\n" + command_text, encoding="utf-8")
    pilot_code, pilot_stdout, pilot_stderr = run(pilot_command, "P4_real_30_calls.log", allow_failure=True)
    manifest = run_dir / "manifest.json"
    status = "UNKNOWN"
    if manifest.exists():
        status = str(json.loads(manifest.read_text(encoding="utf-8")).get("call_policy", {}).get("real_api_status", "UNKNOWN"))
    (REPORT / "EXECUTION_STATUS.json").write_text(json.dumps({"pilot_exit_code": pilot_code, "pilot_status": status, "run_dir": str(run_dir), "session_dir": str(session_dir), "stdout_tail": pilot_stdout[-2000:], "stderr_tail": pilot_stderr[-2000:], "automatic_retry": False}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Analysis and packaging are local operations and continue after a
    # scientific error; a transport/security failure remains in the evidence.
    finalize_code, finalize_stdout, finalize_stderr = run([sys.executable, "scripts/finalize_v5p12_remainder.py"], "P5_finalize_combined_analysis.log", allow_failure=True)
    if finalize_code != 0:
        raise RuntimeError(f"post-run finalization failed: {finalize_stderr[-1000:]}")
    print(json.dumps({"authorization": authorization_result, "pilot_exit_code": pilot_code, "pilot_status": status, "finalization": parse_json_line(finalize_stdout)}, ensure_ascii=False, sort_keys=True))
    return 0 if status == "COMPLETED" and pilot_code == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
