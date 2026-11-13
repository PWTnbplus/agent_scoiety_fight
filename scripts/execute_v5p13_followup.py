from __future__ import annotations

"""Authorize and execute only the new V5-P13 IV002/R2-R3 cohort."""

import json
from datetime import datetime, timezone
from pathlib import Path
import socket
import ssl
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "018_V5P13_SCIENCE_DIAG_AND_FINAL"
CONFIG = ROOT / "config" / "v5p11_main.json"
PROPOSAL = REPORT / "10_V5P13_NEW_FROZEN_PROPOSAL.json"
PROVIDER = "kimi26"
MODEL = "kimi-k2.6"
WORLDS = "IV002"
CONDITIONS = "A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK"
NAMESPACE = "V5P13IV002R23"
MAX_CALLS = "10"
MAX_COST = "0.15"


def run(command: list[str], log_name: str, *, allow_failure: bool = False) -> tuple[int, str, str]:
    result = subprocess.run(command, cwd=ROOT, env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True)
    (REPORT / "logs").mkdir(parents=True, exist_ok=True)
    (REPORT / "logs" / log_name).write_text("$ " + " ".join(command) + "\n\nSTDOUT\n" + result.stdout + "\nSTDERR\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0 and not allow_failure:
        raise RuntimeError(f"command failed: {log_name}: {result.returncode}")
    return result.returncode, result.stdout, result.stderr


def parse_json_line(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError("command did not produce a JSON result")


def network_diagnostics() -> dict[str, Any]:
    host = "token.ctflow.cn"
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            return {"host": host, "addresses": addresses, "tcp_443": True, "tls_version": tls.version(), "cipher": tls.cipher()[0], "credentials_sent": False, "http_probe": False}


def main() -> int:
    if not PROPOSAL.exists():
        raise RuntimeError("frozen V5-P13 proposal is missing")
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    proposal_sha = str(proposal["proposal_sha256"])
    (REPORT / "12_V5P13_NETWORK_BEFORE_AUTH.json").write_text(json.dumps(network_diagnostics(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    auth_command = [sys.executable, "-m", "mini_science.cli", "authorize-real", "--config", str(CONFIG), "--approved-by", "user_explicit", "--provider", PROVIDER, "--model", MODEL, "--scope", "pilot", "--worlds", WORLDS, "--conditions", CONDITIONS, "--max-calls", MAX_CALLS, "--max-estimated-cost-usd", MAX_COST, "--repeats", "4", "--replicate-indices", "2,3", "--request-namespace", NAMESPACE, "--confirmation", "V5P11_REAL_API_AUTHORIZED", "--authorization-note", f"User explicitly authorized a new V5-P13 IV002 R2/R3 cohort: A/B/C/D, 10 unique {MODEL} requests, serial, no automatic retry, local estimate cap USD {MAX_COST}; new proposal {proposal_sha}.", "--proposal-file", str(PROPOSAL), "--proposal-sha256", proposal_sha]
    auth_code, auth_stdout, auth_stderr = run(auth_command, "12_V5P13_AUTHORIZE.log", allow_failure=True)
    if auth_code != 0:
        raise RuntimeError(f"new authorization failed; no API request was made: {auth_stderr[-2000:]}")
    auth_result = parse_json_line(auth_stdout)
    safe_auth = {key: value for key, value in auth_result.items() if key not in {"key", "api_key", "token", "access_token"}}
    (REPORT / "12_V5P13_AUTHORIZATION_RESULT.json").write_text(json.dumps(safe_auth, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    session_dir = Path(str(auth_result["session_dir"])).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / f"real_v5p13_followup_IV002_R2_R3_{stamp}"
    pilot_command = [sys.executable, "-m", "mini_science.cli", "pilot", "--config", str(CONFIG), "--provider", PROVIDER, "--worlds", WORLDS, "--conditions", CONDITIONS, "--repeats", "4", "--replicate-indices", "2,3", "--request-namespace", NAMESPACE, "--allow-paid-api", "--max-calls", MAX_CALLS, "--max-estimated-cost-usd", MAX_COST, "--kimi26-max-cost-usd", MAX_COST, "--kimi26-max-output-tokens", "900", "--kimi26-timeout", "240", "--session-dir", str(session_dir), "--run-dir", str(run_dir)]
    (REPORT / "12_V5P13_EXECUTION_COMMANDS.ps1").write_text("# Exact commands for the independent V5-P13 session.\n" + "python " + " ".join(f'\"{arg}\"' if " " in arg else arg for arg in auth_command[1:]) + "\n\n$env:PYTHONPATH='" + str(ROOT / "src") + "'\npython " + " ".join(f'\"{arg}\"' if " " in arg else arg for arg in pilot_command[1:]) + "\n", encoding="utf-8")
    pilot_code, pilot_stdout, pilot_stderr = run(pilot_command, "13_V5P13_REAL_API_PILOT.log", allow_failure=True)
    status = "UNKNOWN"
    manifest = run_dir / "manifest.json"
    if manifest.exists():
        status = str(json.loads(manifest.read_text(encoding="utf-8")).get("call_policy", {}).get("real_api_status", "UNKNOWN"))
    (REPORT / "13_V5P13_EXECUTION_STATUS.json").write_text(json.dumps({"pilot_exit_code": pilot_code, "pilot_status": status, "run_dir": str(run_dir), "session_dir": str(session_dir), "stdout_tail": pilot_stdout[-3000:], "stderr_tail": pilot_stderr[-3000:], "automatic_retry": False, "new_request_namespace": NAMESPACE}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"authorization": safe_auth, "pilot_exit_code": pilot_code, "pilot_status": status, "run_dir": str(run_dir), "session_dir": str(session_dir)}, ensure_ascii=False, sort_keys=True))
    return 0 if pilot_code == 0 and status == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
