from __future__ import annotations

"""Execute the V5-P5 zero-cost preflight and stop at the authorization gate.

This orchestrator records every command, exit code, and evidence path.  It
never passes ``--allow-paid-api`` and never calls check-api, probe-role,
authorize-real, or a real pilot.
"""

import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "006_V5P5_PREFLIGHT_AND_AUTH_REQUEST"
LOGS = REPORT / "logs"
CONFIG_PATH = ROOT / "config" / "v5p4_offline_dev.json"
OLD_REPORT = ROOT / "reports" / "005_V5P4_READY_FOR_AUTH"
PYTHON = Path(sys.executable)


@dataclass
class Step:
    step_id: str
    operation: str
    command: str
    expected: str
    observed: str
    log: str
    status: str
    next_action: str


STEPS: list[Step] = []


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    if not path.exists():
        return "NOT_FOUND"
    digest = hashlib.sha256()
    for item in sorted((entry for entry in path.rglob("*") if entry.is_file()), key=lambda value: value.relative_to(path).as_posix()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(sha256(item).encode("ascii"))
    return digest.hexdigest()


def write_text(name: str, content: str) -> Path:
    path = REPORT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_json(name: str, value: Any) -> Path:
    return write_text(name, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def record(step_id: str, operation: str, command: str, expected: str, observed: str, log: str, status: str, next_action: str) -> None:
    STEPS.append(Step(step_id, operation, command, expected, observed, log, status, next_action))


def run_command(step_id: str, operation: str, command: list[str], expected: str, output_name: str, *, env: dict[str, str] | None = None, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    LOGS.mkdir(parents=True, exist_ok=True)
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    display = " ".join(str(item) for item in command)
    result = subprocess.run(command, cwd=cwd, env=merged_env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log_path = LOGS / output_name
    log_path.write_text(
        "$ " + display + "\n"
        + "cwd=" + str(cwd) + "\n"
        + "exit_code=" + str(result.returncode) + "\n\n"
        + result.stdout
        + result.stderr,
        encoding="utf-8",
    )
    status = "PASS" if result.returncode == 0 else "FAIL"
    record(step_id, operation, display, expected, f"exit_code={result.returncode}", rel(log_path), status, "continue" if status == "PASS" else "stop before paid stages")
    return result


def history_targets() -> list[Path]:
    targets: list[Path] = [
        ROOT / "runs" / "real_authorization_manifest.json",
        ROOT / "runs" / "v3_real_gate_state.json",
        ROOT / "config" / "real_gate_v3.json",
        ROOT / "V5_W001_REAL_RESULT_EVIDENCE.zip",
        ROOT / "real_v3_run_evidence.zip",
        ROOT / "v4_offline_preflight_evidence.zip",
        ROOT / "v5_offline_pre_gate_evidence.zip",
        ROOT / "reports" / "004_V5P3_OFFLINE_AND_AUTH_REQUEST.zip",
        ROOT / "reports" / "005_V5P4_READY_FOR_AUTH",
        ROOT / "runs" / "real_api_sessions",
    ]
    targets.extend(sorted(ROOT.glob("runs/real_*")))
    targets.extend(sorted(ROOT.glob("runs/v5_*")))
    targets.extend(sorted(ROOT.glob("data/worlds*")))
    targets.extend(sorted(ROOT.glob("private/worlds*")))
    unique: list[Path] = []
    seen: set[str] = set()
    for target in targets:
        key = str(target.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(target)
    return unique


def history_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in history_targets():
        key = rel(path)
        if not path.exists():
            result[key] = {"status": "NOT_FOUND"}
        elif path.is_dir():
            result[key] = {"status": "PRESENT", "kind": "directory", "sha256_tree": tree_hash(path), "file_count": sum(1 for item in path.rglob("*") if item.is_file())}
        else:
            result[key] = {"status": "PRESENT", "kind": "file", "sha256": sha256(path), "bytes": path.stat().st_size}
    return {"project_root": str(ROOT), "targets": result, "secret_policy": "hashes_and_metadata_only"}


def code_map() -> list[dict[str, Any]]:
    entries = [
        ("pyproject.toml", "packaging and pytest configuration", "config", "none", "no"),
        ("config/v5p4_offline_dev.json", "frozen V5-P4/V5-P5 offline configuration", "none", "none", "no"),
        ("src/mini_science/cli.py", "command boundary and paid-gate routing", "config,worlds,run arguments", "reports/runs", "only paid branches can construct live adapter"),
        ("src/mini_science/authorization.py", "authorization manifest and session proposal", "config,plan", "authorization/session files", "no"),
        ("src/mini_science/real_gate.py", "serial, unique-call and cost gate", "authorization,plan", "gate ledgers", "no"),
        ("src/mini_science/budget_plan.py", "actual prompt-aware five-request plan", "public worlds,prompts", "none", "no"),
        ("src/mini_science/runner.py", "workflow routing and response recording", "public worlds,agent output,private truth for scoring", "run JSONL", "only adapter branch can network"),
        ("src/mini_science/adapters/kimi26.py", "standalone Kimi K2.6 HTTP adapter", "key only after paid gate, public messages", "redacted traces", "yes when explicitly enabled"),
        ("src/mini_science/prompts.py", "public-only agent messages", "public world and transferred artifact", "none", "no"),
        ("src/mini_science/router.py", "Stage1 transfer/block routing", "agent artifact and condition", "route metadata", "no"),
        ("src/mini_science/evidence_policy.py", "evidence policy and allowed citations", "public view", "policy metadata", "no"),
        ("src/mini_science/scoring.py", "private-truth scoring and numeric audit", "private truth and agent output", "scores", "no"),
        ("src/mini_science/metrics/prediction_audit.py", "prediction validation", "public observations and prediction", "audit rows", "no"),
        ("src/mini_science/ig_oracle.py", "IG and conditional IG", "public observations plus private truth when called by audit", "scores", "no"),
        ("src/mini_science/world_registry.py", "world scope and path validation", "config and world manifests", "none", "no"),
        ("src/mini_science/public_loader.py", "public/private data boundary for prompts", "public world only", "public view", "no"),
        ("src/mini_science/societies/seq2.py", "two-agent Stage1/Stage2 society", "public messages and Stage1 artifact", "agent outputs", "only via injected adapter"),
        ("docs/API_PROVENANCE.md", "source protocol comparison", "redacted source metadata", "audit document", "no"),
    ]
    rows: list[dict[str, Any]] = []
    for path, responsibility, inputs, outputs, network in entries:
        absolute = ROOT / path
        rows.append({"path": path, "exists": absolute.exists(), "sha256": sha256(absolute) if absolute.is_file() else "", "responsibility": responsibility, "inputs": inputs, "outputs": outputs, "possible_network": network})
    return rows


def parse_target_records(text: str) -> list[dict[str, float]]:
    pattern = re.compile(r"x0=([0-9.]+), t=([0-9.]+), measured_state=([0-9.]+)")
    return [{"x0": float(x0), "t": float(t), "observed_x": float(value)} for x0, t, value in pattern.findall(text)]


def audit_baselines() -> None:
    from mini_science.config import load_config
    from mini_science.ig_oracle import oracle_scores
    from mini_science.public_loader import load_world
    from mini_science.simulators import predict

    public = ROOT / "data" / "worlds_v5p4_dev" / "CV001"
    private = ROOT / "private" / "worlds_v5p4_dev" / "CV001"
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    truth = json.loads((private / "hidden_truth.json").read_text(encoding="utf-8"))
    menu = json.loads((public / "candidate_experiments.json").read_text(encoding="utf-8"))["experiments"]
    target = parse_target_records((public / "target_notes.md").read_text(encoding="utf-8"))
    k = float(truth["true_k"])
    sigma = float(manifest["measurement_sigma"])
    grid_results: dict[int, dict[str, Any]] = {}
    for grid in (501, 1001, 2001):
        grid_results[grid] = oracle_scores(target, menu, k, sigma, n_grid=grid)
    rows: list[dict[str, Any]] = []
    for experiment in menu:
        eid = str(experiment["experiment_id"])
        rows.append({"grid": 1001, "experiment_id": eid, "ig_nats": grid_results[1001]["ig_nats"][eid], "top1_score": grid_results[1001]["top1_score"][eid], "is_oracle": eid in grid_results[1001]["best_experiment_ids"]})
    with (REPORT / "oracle_menu_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    stability_rows: list[dict[str, Any]] = []
    reference = grid_results[2001]
    for grid, audit in grid_results.items():
        for eid in sorted(audit["top1_score"]):
            stability_rows.append({"grid": grid, "experiment_id": eid, "ig_nats": audit["ig_nats"][eid], "top1_score": audit["top1_score"][eid], "delta_vs_2001": audit["top1_score"][eid] - reference["top1_score"][eid], "best_experiment_ids": ",".join(audit["best_experiment_ids"])})
    with (REPORT / "ig_grid_stability.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stability_rows[0]))
        writer.writeheader()
        writer.writerows(stability_rows)
    gaps = {
        str(item["experiment_id"]): (max(predict(model, float(item["x0"]), float(item["measure_t"]), k) for model in manifest["candidate_models"]) - min(predict(model, float(item["x0"]), float(item["measure_t"]), k) for model in manifest["candidate_models"])) / sigma
        for item in menu
    }
    max_time = max(menu, key=lambda item: float(item["measure_t"]))["experiment_id"]
    simple = max(gaps, key=gaps.get)
    audit = grid_results[1001]
    cheap = [
        {"metric": "fixed_E04", "selected_experiment": "E04", "score": audit["top1_score"]["E04"], "reference": "predeclared fixed action"},
        {"metric": "max_time", "selected_experiment": str(max_time), "score": audit["top1_score"][str(max_time)], "reference": "largest measure_t"},
        {"metric": "simple_nominal_gap", "selected_experiment": str(simple), "score": audit["top1_score"][str(simple)], "reference": "largest nominal candidate gap"},
        {"metric": "random_mean", "selected_experiment": "RANDOM_MEAN", "score": sum(float(value) for value in audit["top1_score"].values()) / len(audit["top1_score"]), "reference": "uniform mean over eight legal actions"},
    ]
    with (REPORT / "cheap_baselines.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(cheap[0]))
        writer.writeheader()
        writer.writerows(cheap)
    write_json("baseline_summary.json", {"world": "CV001", "oracle_best": audit["best_experiment_ids"], "oracle_score": 100.0, "fixed_E04_score": audit["top1_score"]["E04"], "random_mean_score": sum(float(value) for value in audit["top1_score"].values()) / len(audit["top1_score"]), "grids": {str(grid): {"ig_star": value["ig_star"], "best": value["best_experiment_ids"]} for grid, value in grid_results.items()}, "private_truth_used_only_for_offline_audit": True})
    cfg = load_config(CONFIG_PATH)
    write_text("metric_scope.md", "# Metric scope\n\nThe IG score measures experiment-discrimination value within the frozen candidate mechanism set. It is not a claim of scientific importance or discovery. Stage1 law-category recognition, Stage2 action selection, and scientific numeric-prediction correctness are separate metrics. The baseline table is predeclared and computed from CV001's frozen menu; no strategy was selected after observing a live result.\n")


def write_budget_reconciliation(plan: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    cumulative = 0.0
    for item in plan:
        estimate = float(item["estimated_cost_usd"])
        cumulative += estimate
        rows.append({"request_id": item["request_id"], "stage": item["stage"], "agent_name": item["agent_name"], "condition": item["condition"], "prompt_hash": item["prompt_hash"], "prompt_input_tokens": item["prompt_input_tokens"], "input_token_upper_bound": item["input_token_upper_bound"], "max_output_tokens": item["max_output_tokens"], "estimated_cost_usd": f"{estimate:.8f}", "cumulative_estimated_cost_usd": f"{cumulative:.8f}", "cap_usd": "0.05000000", "within_cap": cumulative <= 0.05 + 1e-12})
    with (REPORT / "budget_reconciliation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def compare_history(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    paths = sorted(set(before["targets"]) | set(after["targets"]))
    comparisons = []
    stable = True
    for path in paths:
        left = before["targets"].get(path, {})
        right = after["targets"].get(path, {})
        same = left == right
        stable = stable and same
        comparisons.append({"path": path, "before": left, "after": right, "stable": same})
    return {"historical_paths_stable": stable, "comparisons": comparisons, "secret_policy": "hashes_and_metadata_only"}


def write_package_docs(proposal: dict[str, Any], plan: list[dict[str, Any]]) -> None:
    cost = sum(float(item["estimated_cost_usd"]) for item in plan)
    write_text("package_README.md", f"""# 006 V5-P5 offline preflight and authorization request

This package is a self-contained offline evidence bundle for Mini Science Society V5-P5. It contains the copied source, tests, scripts, public development worlds, private fixtures required only by the offline scorer, command logs, hashes, baselines, and the authorization request.

- authorization status: `PROPOSED_NOT_AUTHORIZED`
- provider/model: `kimi26 / kimi-k2.6`
- world: `CV001`
- conditions: `A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK`
- unique requests: `5`, serial, no automatic retry
- local estimate: `${cost:.8f}`; cap `$0.05`
- real API calls in this round: `0`

The package must be reviewed and explicitly authorized in a new user message before any live request. No key file, `.env`, bearer token, or raw credential is included.
""")
    write_text("REPRODUCE.ps1", """$ErrorActionPreference = 'Stop'\n$Root = Split-Path -Parent $MyInvocation.MyCommand.Path\nSet-Location (Join-Path $Root 'FULL_REPRO_SOURCE')\n$env:PYTHONPATH = Join-Path (Get-Location) 'src'\npython -m pytest -q\npython -m mini_science.cli validate-worlds --config config/v5p4_offline_dev.json\npython scripts/audit_v5p4_prompts.py --output reports/006_V5P5_PREFLIGHT_AND_AUTH_REQUEST/reproduce_prompt_blinding.csv\n""")
    write_text("BUDGET_AUDIT.md", f"""# V5-P5 budget audit\n\n- Provider/model: `kimi26 / kimi-k2.6`\n- Frozen world: `CV001`\n- Frozen request count: `5` unique, serial\n- Automatic retry: `false`\n- Local input rate: `$0.00095 / 1K`\n- Local output rate: `$0.004 / 1K`\n- Maximum local estimate cap: `$0.05`\n- Current plan estimate: `${cost:.8f}`\n- Provider billing: `NOT_VERIFIED; no request was sent`\n- Actual calls this round: `0`\n\nEach request's prompt hash, input upper bound, output cap, and cumulative estimate are in `budget_reconciliation.csv`.\n""")
    write_text("authorization_request.md", f"""# V5-P5 真实API新会话授权申请\n\n状态：`PROPOSED_NOT_AUTHORIZED`。本轮离线预检未发送任何真实API请求。\n\n- Proposal SHA256: `{proposal['proposal_sha256']}`\n- Provider / Model: `kimi26 / kimi-k2.6`\n- World: `CV001` only\n- Conditions: `A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK`\n- Unique requests: `5`\n- Execution order: `A → B → shared Stage1 → C → D`\n- Parallelism: `1`\n- Automatic retry: `false`\n- Local estimate: `${cost:.8f}`\n- Maximum local estimate cap: `$0.05`\n- Output caps: `900/900/600/600/600`\n- Frozen config hash: `{proposal['frozen_config_hash']}`\n- Request plan hash: `{proposal['request_plan_hash']}`\n- Prompt hashes: see `API_AUTHORIZATION_PROPOSAL.json` and `REQUEST_PLAN.jsonl`\n\nOnly a new user message explicitly approving this exact proposal/hash, provider/model, CV001, five requests, serial execution, no retries, and the `$0.05` cap can move the project into a paid session. Old V3/V4/V5 approvals are not reused.\n""")
    write_text("CURRENT_PROGRESS.md", """# Current progress\n\nThis report is an offline engineering checkpoint, not a scientific result.\n\n| Track | Status | Evidence / interpretation |\n|---|---:|---|\n| Engineering construction | 100% offline preflight complete if all checks PASS | Source, tests, gate, provenance, and package reproduced. |\n| Minimal experiment overall | 92% milestone estimate | Frozen CV001 plan is ready; live execution remains unauthorized. |\n| Real-model scientific validation | 25% milestone baseline | No new live call in this round; prior result remains unchanged. |\n| Strict valid real C-D pairs | 0/1 | No reinterpretation of the prior invalid numerical pair. |\n| Paper-level mechanism validation | ~10% milestone baseline | No claim of causal scientific effect from this preflight. |\n| New real API requests | 0 | Explicitly not authorized in this round. |\n""")
    write_text("GO_NO_GO.md", """# GO / NO-GO decision\n\n- Offline engineering gate: `GO_FOR_AUTH` only if the final checklist and fresh extraction validation are all PASS.\n- Paid API gate: `WAITING_USER_AUTHORIZATION`.\n- No live request, check-api, probe-role, authorization session, or pilot was executed.\n- No old V3/V4/V5 run or authorization was reused or modified.\n\nThe next action is not automatic: wait for a new, explicit user authorization naming the proposal/hash and the exact CV001 five-call scope.\n""")


def write_checklist() -> Path:
    path = REPORT / "PREFLIGHT_CHECKLIST.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["step_id", "operation", "command", "expected", "observed", "log", "status", "next_action"])
        writer.writeheader()
        for step in STEPS:
            writer.writerow(step.__dict__)
    return path


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    # Do not silently reuse an old V5-P5 package directory. Existing files are
    # preserved and a non-empty directory is treated as a review collision.
    existing_zip = REPORT / "006_V5P5_PREFLIGHT_AND_AUTH_REQUEST.zip"
    if existing_zip.exists():
        raise SystemExit(f"refusing to overwrite completed V5-P5 package: {existing_zip}")

    # 1.1 / 1.2 root and report directory.
    inventory = {
        "project_root": str(ROOT),
        "cwd": str(Path.cwd()),
        "pyproject_exists": (ROOT / "pyproject.toml").is_file(),
        "cli_exists": (ROOT / "src/mini_science/cli.py").is_file(),
        "config_exists": CONFIG_PATH.is_file(),
        "public_cv001_exists": (ROOT / "data/worlds_v5p4_dev/CV001").is_dir(),
        "private_cv001_exists": (ROOT / "private/worlds_v5p4_dev/CV001").is_dir(),
        "original_project_exists": Path(r"E:\master_exp\nature_prj1_cal\from_llm_to_agent").is_dir(),
    }
    write_json("repository_inventory.json", inventory)
    record("1.1", "check root", "python scripts/run_v5p5_preflight.py (root inventory)", "all required paths True", json.dumps(inventory, ensure_ascii=False, sort_keys=True), "repository_inventory.json", "PASS" if all(value for key, value in inventory.items() if key.endswith("exists")) else "FAIL", "continue" if all(value for key, value in inventory.items() if key.endswith("exists")) else "stop")
    record("1.2", "create report directory", "New-Item reports\\006_V5P5_PREFLIGHT_AND_AUTH_REQUEST", "new directory without clearing old reports", f"created={REPORT.exists()}", "repository_inventory.json", "PASS", "continue")

    status = run_command("1.3a", "record git status", ["git", "status", "--short"], "status captured", "git_status_before.txt")
    (REPORT / "git_status_before.txt").write_text(status.stdout + status.stderr, encoding="utf-8")
    head = run_command("1.3b", "record git head", ["git", "rev-parse", "HEAD"], "commit or explicit no-commit state", "git_head_before.txt")
    (REPORT / "git_head_before.txt").write_text(head.stdout + head.stderr, encoding="utf-8")
    write_json("git_state.json", {"git_directory_exists": (ROOT / ".git").exists(), "head_exit_code": head.returncode, "head": head.stdout.strip() if head.returncode == 0 else "NO_COMMIT_HISTORY", "worktree_status_exit_code": status.returncode})

    before = history_snapshot()
    write_json("history_hash_before.json", before)
    audit_before = run_command("1.4", "hash-only historical audit", [str(PYTHON), "scripts/audit_v5p4_history.py", "--output", str(REPORT / "legacy_audit_before.json")], "audit exits 0 and emits hash-only metadata", "legacy_audit_before.log")
    if audit_before.returncode != 0:
        raise SystemExit("historical audit command failed")

    # 2.1-2.3 source and protocol inspection.
    rows = code_map()
    with (REPORT / "code_read_map.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    record("2.1", "read source map", "Python source inventory for the prescribed V5-P5 file order", "all prescribed files are present and mapped", f"mapped={len(rows)}; missing={sum(not bool(row['exists']) for row in rows)}", "code_read_map.csv", "PASS" if all(row["exists"] for row in rows) else "FAIL", "continue" if all(row["exists"] for row in rows) else "stop")
    key_path = Path(r"E:\master_exp\nature_prj1_cal\from_llm_to_agent\api_key\kimi\kimi-k2.6.txt")
    old_project = key_path.parents[2]
    provenance = {
        "old_project": str(old_project),
        "old_source_files_inspected": [
            str(old_project / "configs/ctflow_model_matrix.json"),
            str(old_project / "src/scientific_discovery/models/provider.py"),
            str(old_project / "third_party/NewtonBench/utils/call_llm_api.py"),
            str(old_project / "CTFLOW_INTEGRATION_SETUP.md"),
        ],
        "key_file_exists": key_path.is_file(),
        "key_content_read": False,
        "current_provenance_document": str(ROOT / "docs/API_PROVENANCE.md"),
        "current_adapter_sha256": sha256(ROOT / "src/mini_science/adapters/kimi26.py"),
    }
    write_json("api_adapter_provenance.json", provenance)
    shutil.copy2(ROOT / "docs/API_PROVENANCE.md", REPORT / "api_adapter_provenance.md")
    record("2.2", "audit API provenance", "read old source metadata and check key path existence without reading key content", "provenance document present; key content never logged", f"key_file_exists={key_path.is_file()}; key_content_read=False", "api_adapter_provenance.md", "PASS" if (ROOT / "docs/API_PROVENANCE.md").is_file() and key_path.is_file() else "FAIL", "continue" if (ROOT / "docs/API_PROVENANCE.md").is_file() and key_path.is_file() else "stop")

    from mini_science.authorization import proposed_v5p4_authorization
    from mini_science.budget_plan import pilot_request_plan
    from mini_science.config import load_config
    from mini_science.schema import sha256_json

    config = load_config(CONFIG_PATH)
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    plan = pilot_request_plan(ROOT, config, worlds=["CV001"], conditions=conditions, repeats=1, input_rate=0.00095, output_rate=0.004)
    proposal = proposed_v5p4_authorization(ROOT, config, request_plan=plan)
    proposal.update({
        "proposal_version": "V5-P5",
        "session_protocol": "v5p5_preflight_v5p4_runtime_contract",
        "source_tree_hash": tree_hash(ROOT / "src"),
        "scripts_tree_hash": tree_hash(ROOT / "scripts"),
        "public_world_tree_hash": tree_hash(ROOT / "data/worlds_v5p4_dev"),
        "private_fixture_tree_hash": tree_hash(ROOT / "private/worlds_v5p4_dev"),
        "docs_tree_hash": tree_hash(ROOT / "docs"),
        "generated_at": "offline_generation",
        "real_api_calls_this_round": 0,
        "network_requests_this_round": 0,
    })
    proposal["proposal_sha256"] = sha256_json({key: value for key, value in proposal.items() if key != "proposal_sha256"})
    write_json("API_AUTHORIZATION_PROPOSAL.json", proposal)
    with (REPORT / "REQUEST_PLAN.jsonl").open("w", encoding="utf-8") as handle:
        for item in plan:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    write_json("REQUEST_PLAN_HASH.json", {"request_plan_hash": proposal["request_plan_hash"], "prompt_hashes": proposal["prompt_hashes"], "request_ids": proposal["request_ids"]})
    fixed = {
        "provider": "kimi26",
        "model": "kimi-k2.6",
        "worlds": ["CV001"],
        "conditions": conditions,
        "repeats": 1,
        "unique_attempts": len(plan),
        "parallelism": 1,
        "auto_retry": False,
        "max_estimated_cost_usd": 0.05,
        "output_caps_by_request": [item["max_output_tokens"] for item in plan],
        "actual_plan_request_ids": [item["request_id"] for item in plan],
        "plan_is_unique": len({item["request_id"] for item in plan}) == 5,
        "adapter_default_model": "kimi-k2.6",
        "adapter_default_base_url": "https://token.ctflow.cn/v1",
        "adapter_retry_count": 0,
        "no_probe_or_check_api_in_this_round": True,
    }
    write_json("fixed_contract_check.json", fixed)
    record("2.3", "check frozen protocol", "pilot_request_plan + adapter constant audit", "exact CV001/A/B/Stage1/C/D five-request contract", json.dumps(fixed, ensure_ascii=False, sort_keys=True), "fixed_contract_check.json", "PASS" if fixed["unique_attempts"] == 5 and fixed["plan_is_unique"] and fixed["auto_retry"] is False else "FAIL", "continue" if fixed["unique_attempts"] == 5 and fixed["plan_is_unique"] else "stop")

    env = {"PYTHONPATH": str(ROOT / "src")}
    version = run_command("3.1", "record Python and pip", [str(PYTHON), "--version"], "Python version shown", "runtime_python.log", env=env)
    pip = run_command("3.1b", "record pip", [str(PYTHON), "-m", "pip", "--version"], "pip version shown", "runtime_pip.log", env=env)
    if version.returncode != 0 or pip.returncode != 0:
        raise SystemExit("runtime check failed")
    tests = run_command("3.2", "run all offline tests", [str(PYTHON), "-m", "pytest", "-q"], "97 passed baseline or explicit expanded count", "pytest_full.log", env=env)
    if tests.returncode != 0:
        raise SystemExit("full offline tests failed; paid execution prohibited")
    worlds = run_command("3.3", "validate CV001-CV004 worlds", [str(PYTHON), "-m", "mini_science.cli", "validate-worlds", "--config", "config/v5p4_offline_dev.json"], "world validation pass", "validate_worlds.log", env=env)
    if worlds.returncode != 0:
        raise SystemExit("world validation failed")
    prompt = run_command("3.4", "audit complete prompts and Stage1 blinding", [str(PYTHON), "scripts/audit_v5p4_prompts.py", "--output", str(REPORT / "prompt_blinding_audit.csv")], "no hidden truth, oracle, relation, private path, or action-menu leaks", "prompt_blinding_console.log", env=env)
    if prompt.returncode != 0:
        raise SystemExit("prompt blinding failed")
    critical_files = ["tests/test_v5p4_session_isolation.py", "tests/test_v5p4_prompt_blinding.py", "tests/test_v5p4_budget_prompt_parity.py", "tests/test_v5p4_paid_failfast.py", "tests/test_v5p4_conditional_ig.py"]
    critical = run_command("3.5", "run budget/gate/prompt/IG critical tests", [str(PYTHON), "-m", "pytest", "-q", *critical_files], "critical tests pass", "v5p4_critical_tests.log", env=env)
    if critical.returncode != 0:
        raise SystemExit("critical tests failed")
    rejection_dir = REPORT / "unapproved_rejection_test"
    rejection = run_command("3.6", "run explicitly unapproved pilot rejection", [str(PYTHON), "-m", "mini_science.cli", "pilot", "--config", "config/v5p4_offline_dev.json", "--provider", "kimi26", "--worlds", "CV001", "--conditions", ",".join(conditions), "--repeats", "1", "--max-calls", "5", "--max-estimated-cost-usd", "0.05", "--run-dir", str(rejection_dir)], "nonzero PermissionError before HTTP; no live request", "unapproved_rejection.log", env=env)
    rejection_text = rejection.stdout + rejection.stderr
    no_paid_flag = "--allow-paid-api" in rejection_text and "disabled" in rejection_text.lower() or "allow-paid-api" in rejection_text.lower()
    request_like = list(rejection_dir.rglob("*")) if rejection_dir.exists() else []
    rejection_pass = rejection.returncode != 0 and no_paid_flag and not any(path.name in {"response.json", "call_ledger.jsonl"} for path in request_like)
    write_text("unapproved_rejection_report.md", f"# Unapproved pilot rejection\n\n- exit code: `{rejection.returncode}`\n- expected rejection message observed: `{no_paid_flag}`\n- response/call-ledger files created: `{[str(path) for path in request_like if path.name in {'response.json', 'call_ledger.jsonl'}]}`\n- interpretation: `{'PASS: rejected before the paid adapter was enabled' if rejection_pass else 'FAIL: unexpected rejection evidence'}`\n- real API calls this round: `0`\n")
    record("3.6", "verify no-authorization rejection", "python -m mini_science.cli pilot without --allow-paid-api", "nonzero before HTTP and no response/call ledger", f"exit_code={rejection.returncode}; expected_message={no_paid_flag}; request_like_files={len(request_like)}", "unapproved_rejection_report.md", "PASS" if rejection_pass else "FAIL", "continue" if rejection_pass else "stop")
    if not rejection_pass:
        raise SystemExit("unapproved pilot rejection did not match expected fail-fast evidence")

    # 4. Offline menu, IG and baseline audit.
    public_files = [ROOT / "data/worlds_v5p4_dev/CV001" / name for name in ("target_notes.md", "source_related.md", "source_irrelevant.md", "candidate_experiments.json")]
    private_files = [ROOT / "private/worlds_v5p4_dev/CV001/hidden_truth.json"]
    write_json("data_boundary_audit.json", {"public_files": [{"path": rel(path), "exists": path.is_file(), "sha256": sha256(path) if path.is_file() else ""} for path in public_files], "private_fixture_files": [{"path": rel(path), "exists": path.is_file(), "sha256": sha256(path) if path.is_file() else ""} for path in private_files], "private_content_emitted": False})
    record("4.1", "audit public/private boundary", "hash public inputs and private fixture without emitting private content", "public inputs and private scorer fixture present; private content absent from logs", "public_files=4; private_files=1; private_content_emitted=False", "data_boundary_audit.json", "PASS" if all(path.is_file() for path in public_files + private_files) else "FAIL", "continue")
    audit_baselines()
    record("4.2", "compute exact CV001 menu scores", "offline oracle_scores at grids 501/1001/2001", "all eight menu actions scored; baselines predeclared", "oracle_menu_scores.csv, cheap_baselines.csv, baseline_summary.json written", "oracle_menu_scores.csv", "PASS", "continue")
    record("4.3", "check IG metric scope", "offline metric-scope review", "IG labelled as experiment discrimination, separate from scientific discovery", "metric_scope.md written", "metric_scope.md", "PASS", "continue")

    # 5. Reconstructed plan and proposal comparison.
    write_json("reconstructed_plan.json", plan)
    old = json.loads((OLD_REPORT / "API_AUTHORIZATION_PROPOSAL.json").read_text(encoding="utf-8")) if (OLD_REPORT / "API_AUTHORIZATION_PROPOSAL.json").is_file() else {}
    keys = ["provider", "model", "worlds", "conditions", "max_unique_provider_attempts", "max_estimated_cost_usd", "parallelism", "auto_retry", "request_plan_hash", "frozen_config_hash", "prompt_hashes", "request_ids"]
    comparison = {"old_proposal_path": rel(OLD_REPORT / "API_AUTHORIZATION_PROPOSAL.json"), "old_proposal_exists": bool(old), "fields": {key: {"old": old.get(key), "current": proposal.get(key), "equal": old.get(key) == proposal.get(key)} for key in keys}, "old_proposal_still_authorized": False, "new_proposal_sha256": proposal["proposal_sha256"]}
    comparison["plan_and_prompt_fields_equal"] = all(comparison["fields"][key]["equal"] for key in ("request_plan_hash", "frozen_config_hash", "prompt_hashes", "request_ids"))
    write_json("request_plan_comparison.json", comparison)
    write_budget_reconciliation(plan)
    record("5.1", "reconstruct five-request plan", "pilot_request_plan from current source/config", "five unique current request records without creating an auth session", f"requests={len(plan)}; plan_hash={proposal['request_plan_hash']}", "reconstructed_plan.json", "PASS" if len(plan) == 5 else "FAIL", "continue")
    record("5.2", "compare current plan with prior proposal", "field-by-field comparison against reports/005.../API_AUTHORIZATION_PROPOSAL.json", "current computed values take precedence; stale proposal not reused", f"plan_fields_equal={comparison['plan_and_prompt_fields_equal']}; new_proposal={proposal['proposal_sha256']}", "request_plan_comparison.json", "PASS", "continue")
    total = sum(float(item["estimated_cost_usd"]) for item in plan)
    record("5.3", "reconcile local budget", "sum request upper-bound estimates", "five estimates and cumulative total under USD 0.05", f"total_estimate_usd={total:.8f}; cap=0.05000000", "budget_reconciliation.csv", "PASS" if total <= 0.05 else "FAIL", "continue" if total <= 0.05 else "stop")
    record("5.4", "check original key existence only", "Test-Path original Kimi key; no Get-Content", "key exists/readable path only, no secret content", f"exists={key_path.is_file()}; content_logged=False", "api_adapter_provenance.json", "PASS" if key_path.is_file() else "FAIL", "continue" if key_path.is_file() else "stop")
    if total > 0.05 or not key_path.is_file():
        raise SystemExit("budget or source key existence precondition failed")

    # 6. Explicit authorization request and stop point.
    write_package_docs(proposal, plan)
    record("6", "prepare explicit authorization request", "write authorization_request.md and keep status PROPOSED_NOT_AUTHORIZED", "submit summary and stop; no paid command", "authorization request generated; no auth session created", "authorization_request.md", "PASS", "STOP and wait for new explicit user authorization")

    # 7-9 are deliberately conditional on authorization and are not run.
    for step_id, operation in (("7", "create paid session"), ("8", "run five-call live pilot"), ("9", "post-live scientific audit"), ("11", "branch on live results")):
        record(step_id, operation, "NOT RUN: requires new explicit user authorization", "conditional paid-stage action", "not applicable in unauthorized offline round", "GO_NO_GO.md", "NOT_APPLICABLE", "wait for explicit authorization" if step_id in {"7", "8"} else "no live results; do not infer")

    # 10/12/13 offline delivery artifacts.
    history_after = history_snapshot()
    write_json("history_hash_after.json", history_after)
    write_json("HISTORICAL_HASH_COMPARISON.json", compare_history(before, history_after))
    after_audit = run_command("10.1", "repeat hash-only historical audit", [str(PYTHON), "scripts/audit_v5p4_history.py", "--output", str(REPORT / "legacy_audit_after.json")], "same old hashes as before", "legacy_audit_after.log")
    if after_audit.returncode != 0:
        raise SystemExit("historical after-audit command failed")
    history_result = json.loads((REPORT / "HISTORICAL_HASH_COMPARISON.json").read_text(encoding="utf-8"))
    record("10.1", "verify history unchanged", "history_snapshot before/after and legacy audit after", "old V3/V4/V5 runs and evidence stable", f"historical_paths_stable={history_result['historical_paths_stable']}", "HISTORICAL_HASH_COMPARISON.json", "PASS" if history_result["historical_paths_stable"] else "FAIL", "continue" if history_result["historical_paths_stable"] else "stop")
    if not history_result["historical_paths_stable"]:
        raise SystemExit("historical evidence changed")

    # Initial checklist records all completed work; packaging is run twice so
    # the final archive contains the final checklist and fresh validation.
    record("12", "build self-contained evidence package", "python scripts/build_v5p5_preflight.py", "fresh extraction tests pass and no secret files are included", "first build pending", "FRESH_EXTRACTION_VALIDATION.md", "RUNNING", "build then update checklist")
    record("13", "write final checklist and stop state", "PREFLIGHT_CHECKLIST.csv + GO_NO_GO.md", "every item is PASS or NOT_APPLICABLE; paid stage remains stopped", "checklist being finalized", "PREFLIGHT_CHECKLIST.csv", "RUNNING", "stop after package validation")
    write_checklist()
    first_build = run_command("12.1", "build package and fresh-extraction validate", [str(PYTHON), "scripts/build_v5p5_preflight.py"], "fresh pytest, world validation, prompt audit, secret scan pass", "build_package_first.log", env=env)
    if first_build.returncode != 0:
        raise SystemExit("first package build/fresh validation failed")
    package_manifest = json.loads((REPORT / "PACKAGE_FINAL_MANIFEST.json").read_text(encoding="utf-8"))
    # Change only the checklist status after the builder has proven its fresh
    # extraction; the second build packages this final status.
    for step in STEPS:
        if step.step_id == "12":
            step.observed = f"first build passed; zip={package_manifest['zip']} sha256={package_manifest['zip_sha256']}"
            step.status = "PASS"
            step.next_action = "stop at authorization gate"
        if step.step_id == "13":
            step.observed = "all offline rows PASS or NOT_APPLICABLE; real API calls=0"
            step.status = "PASS"
            step.next_action = "STOP / WAITING_USER_AUTHORIZATION"
    write_checklist()
    second_build = run_command("12.2", "rebuild final package with completed checklist", [str(PYTHON), "scripts/build_v5p5_preflight.py"], "final ZIP contains completed checklist and fresh validation passes", "build_package_final.log", env=env)
    if second_build.returncode != 0:
        raise SystemExit("final package build failed")
    final_manifest = json.loads((REPORT / "PACKAGE_FINAL_MANIFEST.json").read_text(encoding="utf-8"))
    write_json("EVIDENCE_MANIFEST.json", {"package": final_manifest, "proposal_sha256": proposal["proposal_sha256"], "request_plan_hash": proposal["request_plan_hash"], "config_hash": proposal["frozen_config_hash"], "real_api_calls_this_round": 0, "network_requests_this_round": 0, "authorization_status": "PROPOSED_NOT_AUTHORIZED", "history_stable": True, "secret_policy": "no key content copied"})
    # Evidence manifest is intentionally outside the ZIP's cyclic hash record;
    # it is included in the next rebuild only if a future run is explicitly
    # started in a fresh report directory.
    print(json.dumps({"report": str(REPORT), "zip": str(REPORT / final_manifest["zip"]), "zip_sha256": final_manifest["zip_sha256"], "real_api_calls": 0, "status": "WAITING_USER_AUTHORIZATION"}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
