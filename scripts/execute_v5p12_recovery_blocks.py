from __future__ import annotations

"""Execute only independent V5-P12 recovery blocks after a transport stop.

The already-attempted IV002/R0 A and B requests are never replayed. Each
recovery block gets a fresh proposal, authorization session, request namespace,
and run directory. A free DNS/TCP/TLS check is recorded before every block.
"""

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
CONFIG_PATH = ROOT / "config" / "v5p11_main.json"
CONDITIONS = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
CAP_USD = 0.25

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.authorization import create_v5p11_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.proposal_fingerprint import proposal_digest
from mini_science.stable_fingerprint import stable_tree_hash


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def network_diagnostics() -> dict[str, Any]:
    host = "token.ctflow.cn"
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            return {
                "host": host,
                "addresses": addresses,
                "tcp_443": True,
                "tls_version": tls.version(),
                "cipher": tls.cipher()[0],
                "credentials_sent": False,
                "http_probe": False,
            }


def run(command: list[str], log_name: str) -> tuple[int, str, str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
    )
    (REPORT / "logs").mkdir(parents=True, exist_ok=True)
    (REPORT / "logs" / log_name).write_text(
        "$ " + " ".join(command) + "\n\nSTDOUT\n" + result.stdout + "\nSTDERR\n" + result.stderr,
        encoding="utf-8",
    )
    return result.returncode, result.stdout, result.stderr


def proposal_for(config: Any, *, worlds: list[str], replicate_indices: list[int], namespace: str, output: Path) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    plan = pilot_request_plan(
        ROOT,
        config,
        worlds=worlds,
        conditions=CONDITIONS,
        repeats=2,
        replicate_indices=replicate_indices,
        request_namespace=namespace,
        input_rate=0.00095,
        output_rate=0.004,
    )
    expected = len(worlds) * len(replicate_indices) * 5
    if len(plan) != expected or len({str(row["request_id"]) for row in plan}) != expected:
        raise RuntimeError(f"recovery plan is not unique: expected {expected}, got {len(plan)}")
    proposal = proposed = __import__("mini_science.authorization", fromlist=["proposed_v5p11_authorization"]).proposed_v5p11_authorization(
        ROOT,
        config,
        request_plan=plan,
        worlds=worlds,
        conditions=CONDITIONS,
        repeats=2,
        request_namespace=namespace,
        max_unique_provider_attempts=expected,
        max_estimated_cost_usd=CAP_USD,
    )
    tree_bindings = {
        "source_tree_hash": ROOT / "src",
        "tests_tree_hash": ROOT / "tests",
        "scripts_tree_hash": ROOT / "scripts",
        "public_world_tree_hash": ROOT / "data" / config.worlds_subdir,
        "private_fixture_tree_hash": ROOT / "private" / config.private_worlds_subdir,
        "docs_tree_hash": ROOT / "docs",
    }
    proposal.update({field: stable_tree_hash(path) for field, path in tree_bindings.items()})
    proposal["generated_at"] = datetime.now(timezone.utc).isoformat()
    proposal["proposal_sha256"] = proposal_digest(proposal)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "REQUEST_PLAN.jsonl").open("w", encoding="utf-8") as handle:
        for row in plan:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    write_json(output / "PROPOSAL.json", proposal)
    (output / "PROPOSAL_SHA256.txt").write_text(proposal["proposal_sha256"] + "\n", encoding="utf-8")
    (output / "REQUEST_PLAN_SHA256.txt").write_text(proposal["request_plan_hash"] + "\n", encoding="utf-8")
    write_json(output / "NETWORK_DIAGNOSTICS_BEFORE_AUTH.json", network_diagnostics())
    return plan, proposal, str(proposal["proposal_sha256"])


def classify_stop(run_dir: Path, stderr: str) -> str:
    text = stderr.lower()
    if any(token in text for token in ("security", "authorization", "unauthorized", "budget", "scope", "billing", "api key")):
        return "STOP_SECURITY_OR_BUDGET"
    manifest = run_dir / "manifest.json"
    if manifest.exists():
        status = str(json.loads(manifest.read_text(encoding="utf-8")).get("call_policy", {}).get("real_api_status", ""))
        if status == "COMPLETED":
            return "COMPLETED"
    return "STOP_TRANSPORT_OR_TECHNICAL"


def execute_block(config: Any, *, label: str, worlds: list[str], replicate_indices: list[int], namespace: str) -> dict[str, Any]:
    block_dir = REPORT / "recovery" / label
    plan, proposal, proposal_sha = proposal_for(config, worlds=worlds, replicate_indices=replicate_indices, namespace=namespace, output=block_dir)
    expected = len(plan)
    auth_path = create_v5p11_authorization(
        ROOT,
        config,
        approved_by="user_explicit",
        confirmation="V5P11_REAL_API_AUTHORIZED",
        authorization_note=(
            f"User-authorized V5-P12 recovery block {label}: {worlds}, repeats {replicate_indices}, "
            f"A/B/C/D, {expected} unique kimi-k2.6 requests, serial, no retry, cap USD {CAP_USD}; "
            f"new proposal {proposal_sha}."
        ),
        request_plan=plan,
        proposal_path=block_dir / "PROPOSAL.json",
        proposal_sha256=proposal_sha,
        require_proposal_binding=True,
        worlds=worlds,
        conditions=CONDITIONS,
        repeats=2,
        request_namespace=namespace,
        max_unique_provider_attempts=expected,
        max_estimated_cost_usd=CAP_USD,
    )
    session_dir = auth_path.parent.resolve()
    auth_record = json.loads(auth_path.read_text(encoding="utf-8"))
    write_json(block_dir / "AUTHORIZATION_RESULT.json", {key: value for key, value in auth_record.items() if key not in {"key", "api_key"}})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "runs" / f"real_v5p12_recovery_{label}_{stamp}"
    command = [
        sys.executable,
        "-m",
        "mini_science.cli",
        "pilot",
        "--config",
        str(CONFIG_PATH),
        "--provider",
        "kimi26",
        "--worlds",
        ",".join(worlds),
        "--conditions",
        ",".join(CONDITIONS),
        "--repeats",
        "2",
        "--replicate-indices",
        ",".join(str(value) for value in replicate_indices),
        "--request-namespace",
        namespace,
        "--allow-paid-api",
        "--max-calls",
        str(expected),
        "--max-estimated-cost-usd",
        str(CAP_USD),
        "--kimi26-max-cost-usd",
        str(CAP_USD),
        "--kimi26-max-output-tokens",
        "900",
        "--kimi26-timeout",
        "240",
        "--session-dir",
        str(session_dir),
        "--run-dir",
        str(run_dir),
    ]
    (block_dir / "EXECUTION_COMMAND.txt").write_text("python " + " ".join(f'\"{arg}\"' if " " in arg else arg for arg in command[1:]) + "\n", encoding="utf-8")
    code, stdout, stderr = run(command, f"{label}_REAL_API.log")
    status = "UNKNOWN"
    if (run_dir / "manifest.json").exists():
        status = str(json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")).get("call_policy", {}).get("real_api_status", "UNKNOWN"))
    stop_class = classify_stop(run_dir, stderr)
    write_json(block_dir / "EXECUTION_STATUS.json", {
        "label": label,
        "worlds": worlds,
        "replicate_indices": replicate_indices,
        "request_count": expected,
        "proposal_sha256": proposal_sha,
        "request_plan_hash": proposal["request_plan_hash"],
        "authorization_id": auth_record.get("authorization_id"),
        "session_dir": str(session_dir),
        "run_dir": str(run_dir),
        "pilot_exit_code": code,
        "pilot_status": status,
        "stop_class": stop_class,
        "automatic_retry": False,
        "stdout_tail": stdout[-3000:],
        "stderr_tail": stderr[-3000:],
    })
    return {"label": label, "run_dir": str(run_dir), "session_dir": str(session_dir), "status": status, "stop_class": stop_class, "pilot_exit_code": code, "request_count": expected, "proposal_sha256": proposal_sha}


def main() -> int:
    REPORT.mkdir(parents=True, exist_ok=True)
    config = load_config(CONFIG_PATH)
    blocks = [
        ("IV002_R1", ["IV002"], [1], "V5P12RECIV002R1"),
        ("IV003_R01", ["IV003"], [0, 1], "V5P12RECIV003R01"),
        ("IV004_R01", ["IV004"], [0, 1], "V5P12RECIV004R01"),
    ]
    outcomes: list[dict[str, Any]] = []
    for label, worlds, repeats, namespace in blocks:
        try:
            preflight = network_diagnostics()
            write_json(REPORT / "recovery" / label / "NETWORK_DIAGNOSTICS_BEFORE_BLOCK.json", preflight)
            outcome = execute_block(config, label=label, worlds=worlds, replicate_indices=repeats, namespace=namespace)
        except Exception as exc:
            outcome = {"label": label, "status": "AUTH_OR_PREFLIGHT_ERROR", "error_type": type(exc).__name__, "error": str(exc), "automatic_retry": False}
            write_json(REPORT / "recovery" / label / "EXECUTION_STATUS.json", outcome)
            outcomes.append(outcome)
            break
        outcomes.append(outcome)
        if outcome["stop_class"] == "STOP_SECURITY_OR_BUDGET":
            break
        # A transport failure ends this block, but independent blocks may
        # continue after their own free network diagnostic.
    write_json(REPORT / "RECOVERY_EXECUTION_STATUS.json", {"blocks": outcomes, "total_requested_by_recovery_proposals": sum(int(item.get("request_count", 0)) for item in outcomes), "automatic_retries": False})
    finalize_code, finalize_stdout, finalize_stderr = run([sys.executable, "scripts/finalize_v5p12_remainder.py"], "P5_finalize_after_recovery.log")
    if finalize_code != 0:
        raise RuntimeError(finalize_stderr[-2000:] or finalize_stdout[-2000:])
    print(json.dumps({"blocks": outcomes, "finalization": finalize_stdout[-5000:]}, ensure_ascii=False, sort_keys=True))
    return 0 if all(item.get("status") == "COMPLETED" for item in outcomes) else 2


if __name__ == "__main__":
    raise SystemExit(main())
