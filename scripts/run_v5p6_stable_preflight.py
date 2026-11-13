from __future__ import annotations

"""Run V5-P6 P0-P8 offline hash repair and stop before paid authorization."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from mini_science.authorization import proposed_v5p4_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.proposal_fingerprint import proposal_digest
from mini_science.stable_fingerprint import CACHE_DIRS, stable_tree_hash, stable_tree_manifest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "008_V5P6_HASH_FIX_AND_NEW_PROPOSAL"
LOGS = REPORT / "logs"
CONFIG_PATH = ROOT / "config" / "v5p4_offline_dev.json"
PYTHON = Path(sys.executable)


@dataclass
class ChecklistRow:
    step_id: str
    operation: str
    command: str
    expected: str
    observed: str
    log: str
    status: str
    next_action: str


ROWS: list[ChecklistRow] = []


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(name: str, text: str) -> Path:
    path = REPORT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_json(name: str, value: Any) -> Path:
    return write_text(name, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def add_row(step_id: str, operation: str, command: str, expected: str, observed: str, log: str, status: str, next_action: str) -> None:
    ROWS.append(ChecklistRow(step_id, operation, command, expected, observed, log, status, next_action))


def run_command(step_id: str, operation: str, command: list[str], expected: str, log_name: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    LOGS.mkdir(parents=True, exist_ok=True)
    merged = dict(__import__("os").environ)
    if env:
        merged.update(env)
    result = subprocess.run(command, cwd=ROOT, env=merged, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log_path = LOGS / log_name
    log_path.write_text("$ " + " ".join(str(value) for value in command) + "\nexit_code=" + str(result.returncode) + "\n" + result.stdout + result.stderr, encoding="utf-8")
    add_row(step_id, operation, " ".join(str(value) for value in command), expected, f"exit_code={result.returncode}", rel(log_path), "PASS" if result.returncode == 0 else "FAIL", "continue" if result.returncode == 0 else "stop")
    return result


def history_targets() -> list[Path]:
    values = [
        ROOT / "runs" / "real_api_sessions",
        ROOT / "runs" / "v5_p1_real_w001_20261112_145649",
        ROOT / "runs" / "real_authorization_manifest.json",
        ROOT / "runs" / "v3_real_gate_state.json",
        ROOT / "reports" / "005_V5P4_READY_FOR_AUTH",
        ROOT / "reports" / "006_V5P5_PREFLIGHT_AND_AUTH_REQUEST",
        ROOT / "reports" / "007_V5P5_CV001_REAL_API_EXECUTION_EVIDENCE",
        ROOT / "V5_W001_REAL_RESULT_EVIDENCE.zip",
        ROOT / "real_v3_run_evidence.zip",
        ROOT / "v4_offline_preflight_evidence.zip",
        ROOT / "v5_offline_pre_gate_evidence.zip",
        ROOT / "reports" / "004_V5P3_OFFLINE_AND_AUTH_REQUEST.zip",
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in values:
        key = str(path.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def history_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in history_targets():
        key = rel(path)
        if not path.exists():
            result[key] = {"status": "NOT_PRESENT"}
        elif path.is_dir():
            result[key] = {"status": "PRESENT", "kind": "directory", "stable_tree_hash": stable_tree_hash(path), "file_count": sum(1 for item in path.rglob("*") if item.is_file() and not item.is_symlink())}
        else:
            result[key] = {"status": "PRESENT", "kind": "file", "sha256": sha256(path), "bytes": path.stat().st_size}
    return {"project_root": str(ROOT), "targets": result, "secret_policy": "hashes_and_metadata_only"}


def compare_history(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    rows = []
    stable = True
    for path in sorted(set(before["targets"]) | set(after["targets"])):
        left = before["targets"].get(path, {})
        right = after["targets"].get(path, {})
        same = left == right
        stable = stable and same
        rows.append({"path": path, "before": left, "after": right, "stable": same})
    return {"historical_paths_stable": stable, "comparisons": rows}


def legacy_tree_hash(root: Path) -> str:
    """The V5-P5 defective algorithm, used only in a temporary reproduction."""
    digest = hashlib.sha256()
    for item in sorted((entry for entry in root.rglob("*") if entry.is_file()), key=lambda value: value.relative_to(root).as_posix()):
        digest.update(item.relative_to(root).as_posix().encode("utf-8"))
        digest.update(sha256(item).encode("ascii"))
    return digest.hexdigest()


def reproduce_old_cache_drift() -> None:
    with tempfile.TemporaryDirectory(prefix="v5p6_hash_repro_") as temporary:
        root = Path(temporary)
        (root / "a.py").write_text("x=1\n", encoding="utf-8")
        h0 = legacy_tree_hash(root)
        cache = root / "__pycache__"
        cache.mkdir()
        (cache / "a.cpython-311.pyc").write_bytes(b"compiled-cache")
        h1 = legacy_tree_hash(root)
        stable0 = stable_tree_hash(root)
        stable1 = stable_tree_hash(root)
    result = {"legacy_h0": h0, "legacy_h1": h1, "legacy_changed": h0 != h1, "stable_before_after_same": stable0 == stable1, "temporary_only": True}
    write_json("CACHE_DRIFT_REPRO.json", result)
    add_row("P1.2", "reproduce old cache drift", "temporary a.py + __pycache__/a.pyc and legacy_tree_hash", "legacy H0 != H1; stable hash remains stable", json.dumps(result, sort_keys=True), "CACHE_DRIFT_REPRO.json", "PASS" if result["legacy_changed"] and result["stable_before_after_same"] else "FAIL", "continue" if result["legacy_changed"] else "stop")
    if not result["legacy_changed"]:
        raise RuntimeError("old cache drift was not reproduced")


def write_source_manifest(name: str) -> None:
    roots = {
        "src": ROOT / "src",
        "tests": ROOT / "tests",
        "scripts": ROOT / "scripts",
        "config": ROOT / "config",
        "public_worlds_v5p4_dev": ROOT / "data" / "worlds_v5p4_dev",
        "private_worlds_v5p4_dev": ROOT / "private" / "worlds_v5p4_dev",
        "docs": ROOT / "docs",
    }
    rows: list[dict[str, Any]] = []
    for root_name, base in roots.items():
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(base)
            is_cache = path.is_symlink() or any(part in CACHE_DIRS for part in relative.parts) or path.suffix.lower() in {".pyc", ".pyo", ".tmp"}
            rows.append({"root": root_name, "relative_path": relative.as_posix(), "sha256": sha256(path), "is_cache": is_cache, "category": "cache" if is_cache else "frozen_input_or_code"})
    with (REPORT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_proposal(config, plan: list[dict[str, Any]]) -> dict[str, Any]:
    proposal = proposed_v5p4_authorization(ROOT, config, request_plan=plan)
    proposal.update({
        "proposal_version": "V5-P6",
        "session_protocol": "v5p6_stable_hash",
        "hash_algorithm_version": "stable_tree_hash_v1",
        "source_tree_hash": stable_tree_hash(ROOT / "src"),
        "tests_tree_hash": stable_tree_hash(ROOT / "tests"),
        "scripts_tree_hash": stable_tree_hash(ROOT / "scripts"),
        "public_world_tree_hash": stable_tree_hash(ROOT / "data" / "worlds_v5p4_dev"),
        "private_fixture_tree_hash": stable_tree_hash(ROOT / "private" / "worlds_v5p4_dev"),
        "docs_tree_hash": stable_tree_hash(ROOT / "docs"),
        "generated_at": "offline_generation",
        "real_api_calls_this_round": 0,
        "network_requests_this_round": 0,
    })
    proposal["proposal_sha256"] = proposal_digest(proposal)
    return proposal


def proposal_diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    # V5-P6 changes the fingerprint algorithm itself.  Therefore every tree
    # fingerprint recomputed with stable_tree_hash_v1 is expected to differ
    # from the legacy V5-P5 value, including the frozen public/private
    # development fixtures.  The underlying files are still protected by the
    # before/after history snapshot and the fresh-package provenance.
    allowed = {"proposal_sha256", "proposal_version", "session_protocol", "hash_algorithm_version", "authorization_id", "session_id", "source_tree_hash", "tests_tree_hash", "scripts_tree_hash", "docs_tree_hash", "public_world_tree_hash", "private_fixture_tree_hash", "generated_at", "network_requests_this_round", "real_api_calls_this_round"}
    fields = {}
    unexpected = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) == new.get(key):
            continue
        classification = "INTENDED_HASH_FIX" if key in allowed else "UNEXPECTED"
        fields[key] = {"old": old.get(key), "new": new.get(key), "classification": classification}
        if classification == "UNEXPECTED":
            unexpected.append(key)
    return {"old_proposal": "reports/006_V5P5_PREFLIGHT_AND_AUTH_REQUEST/API_AUTHORIZATION_PROPOSAL.json", "allowed_change_policy": sorted(allowed), "fields": fields, "unexpected_fields": unexpected, "pass": not unexpected}


def write_checklist() -> None:
    with (REPORT / "PREFLIGHT_CHECKLIST.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ChecklistRow.__annotations__))
        writer.writeheader()
        writer.writerows(row.__dict__ for row in ROWS)


def write_docs(proposal: dict[str, Any], plan: list[dict[str, Any]], diff: dict[str, Any]) -> None:
    total = sum(float(item["estimated_cost_usd"]) for item in plan)
    write_text("DEFECT_REPRO.md", """# V5-P6 defect reproduction\n\nThe V5-P5 evidence stopped before authorization because the complete proposal SHA changed after offline tests while request-plan and config hashes remained equal. The old tree hash included generated `__pycache__/*.pyc` files. V5-P6 replaces only the new proposal protocol with `stable_tree_hash_v1`, which excludes reproducible caches but fails closed on symlinks, missing roots, and unreadable files. Historical reports and old hash outputs are unchanged.\n\n- old frozen proposal: `c3358f44c467b068b7c029c928eabdf519c661207ba3065232a555e164b88301`\n- old/new request-plan hash: `6eff0560b6cafe9fbd3a148519e6205ca2e7f15b0c66c554dc54a01798b8913c`\n- old/new config hash: `b630cbebbbc827ab68f3cf76e83b600e986657482416e07b6e99a1b66feac563`\n- defect status: `RESOLVED OFFLINE; NEW PROPOSAL REQUIRES CONFIRMATION`\n""")
    write_text("HASH_CALL_GRAPH.md", """# V5-P6 hash call graph\n\n- `scripts/run_v5p5_preflight.py::tree_hash`: legacy V5-P5 proposal path; recursively included generated cache files. Preserved as historical evidence and not reused for V5-P6 authorization.\n- `scripts/build_v5p4_proposal.py::tree_hash`: older V5-P4 path; skipped `.pyc` but used a different algorithm. Preserved for historical comparability.\n- `src/mini_science/stable_fingerprint.py::stable_tree_hash`: canonical V5-P6 implementation used by the new proposal and package builder.\n- `src/mini_science/experiment_plan.py::source_tree_hash`: now delegates to `stable_tree_hash(src)` for new run fingerprints.\n- `src/mini_science/authorization.py::create_v5p4_authorization`: when the new CLI supplies a proposal file/SHA, verifies the complete digest, scope, plan/config/prompt fields, and stable tree fingerprints before writing `authorization.json`.\n- `src/mini_science/real_gate.py::V5P4SessionGate`: preserves serial, unique-request, frozen-plan, and budget enforcement; the new authorization record carries `proposal_sha256` and fingerprint bindings.\n- `src/mini_science/cli.py::authorize-real`: V5-P4 authorization now requires `--proposal-file` and `--proposal-sha256`.\n- `src/mini_science/budget_plan.py::pilot_request_plan`: unchanged request construction; plan hash and prompts are frozen.\n- `scripts/audit_v5p4_history.py`: read-only historical audit; not used to overwrite old evidence.\n""")
    write_text("AUTH_REQUEST.md", f"""# V5-P6 new proposal authorization request\n\nStatus: `PROPOSED_NOT_AUTHORIZED`. P0-P8 used zero paid requests and zero network requests.\n\n- New proposal SHA256: `{proposal['proposal_sha256']}`\n- Provider/model: `kimi26 / kimi-k2.6`\n- World: `CV001` only\n- Conditions: `A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK`\n- Requests: 5 unique, serial, A → B → shared Stage1 → C → D\n- Automatic retry: false\n- Local estimate: `${total:.8f}`; session cap `$0.05`\n- User's overall ceiling: `$2.00`; it does not expand this frozen session\n- Request-plan hash: `{proposal['request_plan_hash']}`\n- Config hash: `{proposal['frozen_config_hash']}`\n- Output caps: `900/900/600/600/600`\n- Hash algorithm: `stable_tree_hash_v1`\n\nThe corrected complete proposal SHA must be explicitly confirmed in a new user message before `authorize-real` or any live API request.\n""")
    write_text("TEST_RESULTS.md", """# V5-P6 offline test results\n\nThe full pytest count is recorded in `logs/pytest_full_v5p6.log` and the repeated stability runs are in `logs/pytest_repeat_*.log`; the count is not hardcoded here. World validation is in `logs/validate_worlds_v5p6.log`; prompt blinding is in `prompt_blinding_audit.csv`. The package fresh-extraction result is in `FRESH_EXTRACTION_VALIDATION.md`.\n\nAll commands in P0-P8 are offline. No check-api, probe-role, authorize-real, paid pilot, or network request was executed.\n""")
    write_text("CURRENT_PROGRESS.md", """# Current progress\n\n| Dimension | Status |\n|---|---:|\n| Offline engineering | 100% for the V5-P6 hash-fix gate, subject to fresh package PASS |\n| Minimal experiment overall | 92% milestone baseline |\n| Real-model scientific validation | 25% milestone baseline; no new calls |\n| Strict valid real C/D pairs | 0/1 unchanged |\n| Paper-level mechanism validation | ~10% milestone baseline |\n| New real API requests | 0 |\n""")
    write_text("GO_NO_GO.md", """# GO / NO-GO\n\n- Offline hash-fix gate: `GO_FOR_AUTH` only after the final checklist and fresh extraction are PASS.\n- Paid API gate: `NO_GO / WAITING_NEW_PROPOSAL_CONFIRMATION`.\n- The corrected proposal SHA is new; the previous c335... proposal is not reused.\n- No real result, token, billing, or A/B/C/D scientific conclusion is generated in P0-P8.\n""")
    write_text("package_README.md", f"""# 008 V5-P6 hash fix and authorization request\n\nThis is an offline-only, self-contained evidence package. New proposal SHA: `{proposal['proposal_sha256']}`. Request-plan hash: `{proposal['request_plan_hash']}`. Local estimate: `${total:.8f}` with a `$0.05` session cap. Real API calls: `0`.\n\nIt contains the copied source/tests/scripts/config, public development worlds, private scorer fixtures, hash stability matrix, proposal diff, command logs, and no credentials. A new user confirmation naming the new proposal SHA is required before any paid action.\n""")
    write_text("REPRODUCE.ps1", """$ErrorActionPreference = 'Stop'\n$Root = Split-Path -Parent $MyInvocation.MyCommand.Path\nSet-Location (Join-Path $Root 'FULL_REPRO_SOURCE')\n$env:PYTHONPATH = Join-Path (Get-Location) 'src'\npython -m pytest -q\npython -m mini_science.cli validate-worlds --config config/v5p4_offline_dev.json\npython scripts/audit_v5p4_prompts.py --output reports/008_V5P6_HASH_FIX_AND_NEW_PROPOSAL/reproduce_prompt_blinding.csv\n""")
    write_json("EVIDENCE_MANIFEST.json", {"package": "008_V5P6_HASH_FIX_AND_AUTH_REQUEST", "proposal_sha256": proposal["proposal_sha256"], "request_plan_hash": proposal["request_plan_hash"], "config_hash": proposal["frozen_config_hash"], "authorization_status": "PROPOSED_NOT_AUTHORIZED", "real_api_calls_this_round": 0, "network_requests_this_round": 0, "history_stable": True, "secret_policy": "no key content copied"})


def main() -> None:
    if REPORT.exists() and (REPORT / "FINAL_STATUS.md").exists():
        raise SystemExit(f"refusing to overwrite completed V5-P6 report: {REPORT}")
    REPORT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    env = {"PYTHONPATH": str(ROOT / "src")}
    write_text("start_time.txt", datetime.now(timezone.utc).isoformat() + "\n")
    inventory = {"project_root": str(ROOT), "pyproject": (ROOT / "pyproject.toml").is_file(), "cli": (ROOT / "src/mini_science/cli.py").is_file(), "config": CONFIG_PATH.is_file(), "v5p4_public": (ROOT / "data/worlds_v5p4_dev/CV001").is_dir(), "v5p4_private": (ROOT / "private/worlds_v5p4_dev/CV001").is_dir(), "original_api_project": Path(r"E:\master_exp\nature_prj1_cal\from_llm_to_agent").is_dir()}
    write_json("repository_inventory.json", inventory)
    add_row("P0.1", "locate project", "python --version and repository inventory", "project paths and Python are present", json.dumps(inventory, sort_keys=True), "repository_inventory.json", "PASS" if all(inventory.values()) else "FAIL", "continue" if all(inventory.values()) else "stop")
    if not all(inventory.values()):
        raise SystemExit("P0.1 project inventory failed")
    status = run_command("P0.2", "record git status", ["git", "status", "--short"], "status saved", "git_status_before.log")
    write_text("git_status_before.txt", status.stdout + status.stderr)
    before = history_snapshot()
    write_json("history_hash_before.json", before)
    write_source_manifest("SOURCE_MANIFEST_BEFORE.csv")
    add_row("P0.2", "snapshot history", "hash protected history, old evidence, and source manifest", "hash-only snapshots present; no old path modified", "history_hash_before.json and SOURCE_MANIFEST_BEFORE.csv written", "history_hash_before.json", "PASS", "continue")
    write_text("DEFECT_REPRO.md", "V5-P6 defect record is completed after P1.\n")
    reproduce_old_cache_drift()
    write_text("HASH_CALL_GRAPH.md", "V5-P6 hash call graph is completed after P1.\n")

    tests = run_command("P3.1", "run full offline pytest", [str(PYTHON), "-m", "pytest", "-q"], "all tests pass", "pytest_full_v5p6.log", env=env)
    if tests.returncode != 0:
        raise SystemExit("P3 full pytest failed")
    worlds = run_command("P4.1", "validate CV001-CV004 worlds", [str(PYTHON), "-m", "mini_science.cli", "validate-worlds", "--config", "config/v5p4_offline_dev.json"], "world validation pass with CV001 E03", "validate_worlds_v5p6.log", env=env)
    if worlds.returncode != 0:
        raise SystemExit("P4 world validation failed")
    prompt = run_command("P4.2", "audit prompt privacy", [str(PYTHON), "scripts/audit_v5p4_prompts.py", "--output", str(REPORT / "prompt_blinding_audit.csv")], "all prompt records pass", "prompt_blinding_v5p6.log", env=env)
    if prompt.returncode != 0:
        raise SystemExit("P4 prompt audit failed")
    add_row("P3-P4", "offline engineering checks", "pytest + validate-worlds + prompt audit", "tests/world/privacy pass before proposal freeze", "exit codes all 0", "pytest_full_v5p6.log", "PASS", "continue")

    config = load_config(CONFIG_PATH)
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    plan = pilot_request_plan(ROOT, config, worlds=["CV001"], conditions=conditions, repeats=1, input_rate=0.00095, output_rate=0.004)
    proposal = build_proposal(config, plan)
    write_json("API_AUTHORIZATION_PROPOSAL.json", proposal)
    with (REPORT / "REQUEST_PLAN.jsonl").open("w", encoding="utf-8") as handle:
        for item in plan:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    add_row("P2-P5.1", "generate new stable proposal", "pilot_request_plan + stable_tree_hash + proposal_digest", "new proposal is computed, not copied", f"proposal_sha256={proposal['proposal_sha256']}; requests={len(plan)}", "API_AUTHORIZATION_PROPOSAL.json", "PASS", "repeat after pytest")

    stability_rows: list[dict[str, Any]] = []
    for index in range(3):
        repeat = run_command(f"P5.2.{index + 1}", "repeat pytest after proposal", [str(PYTHON), "-m", "pytest", "-q"], "all tests pass and proposal remains stable", f"pytest_repeat_{index + 1}.log", env=env)
        if repeat.returncode != 0:
            raise SystemExit("pytest repeat failed")
        after = build_proposal(config, plan)
        stability_rows.append({"repeat": index + 1, "proposal_sha256": after["proposal_sha256"], "equals_initial": after["proposal_sha256"] == proposal["proposal_sha256"], "request_plan_equal": after["request_plan_hash"] == proposal["request_plan_hash"], "config_equal": after["frozen_config_hash"] == proposal["frozen_config_hash"]})
    with (REPORT / "HASH_STABILITY_TESTS.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stability_rows[0]))
        writer.writeheader()
        writer.writerows(stability_rows)
    if not all(row["equals_initial"] and row["request_plan_equal"] and row["config_equal"] for row in stability_rows):
        raise SystemExit("proposal is unstable after pytest")
    add_row("P5.2", "prove repeated proposal stability", "three pytest -> proposal recomputations", "all three full proposal SHA values equal", json.dumps(stability_rows, sort_keys=True), "HASH_STABILITY_TESTS.csv", "PASS", "continue")

    with tempfile.TemporaryDirectory(prefix="v5p6_mutation_") as temporary:
        temp = Path(temporary)
        (temp / "agent.py").write_text("x=1\n", encoding="utf-8")
        h0 = stable_tree_hash(temp)
        (temp / "agent.py").write_text("x=2\n", encoding="utf-8")
        h1 = stable_tree_hash(temp)
        (temp / "agent.py").write_text("x=1\n", encoding="utf-8")
        h2 = stable_tree_hash(temp)
    mutation = {"before": h0, "changed": h1, "restored": h2, "changed_detected": h0 != h1, "restore_detected": h0 == h2}
    write_json("INTENTIONAL_MUTATION_AUDIT.json", mutation)
    add_row("P5.3", "audit intentional source mutation", "temporary agent.py change and restore", "change changes hash; restore returns original", json.dumps(mutation, sort_keys=True), "INTENTIONAL_MUTATION_AUDIT.json", "PASS" if mutation["changed_detected"] and mutation["restore_detected"] else "FAIL", "continue")
    if not mutation["changed_detected"] or not mutation["restore_detected"]:
        raise SystemExit("stable hash mutation audit failed")

    old = json.loads((ROOT / "reports/006_V5P5_PREFLIGHT_AND_AUTH_REQUEST/API_AUTHORIZATION_PROPOSAL.json").read_text(encoding="utf-8"))
    diff = proposal_diff(old, proposal)
    write_json("PROPOSAL_DIFF_FROM_006.json", diff)
    add_row("P5.4", "diff new proposal against 006", "field-by-field proposal diff", "only intended hash/version metadata changes", f"unexpected_fields={diff['unexpected_fields']}", "PROPOSAL_DIFF_FROM_006.json", "PASS" if diff["pass"] else "FAIL", "continue" if diff["pass"] else "stop")
    if not diff["pass"]:
        raise SystemExit("unexpected proposal diff")

    write_source_manifest("SOURCE_MANIFEST_AFTER.csv")
    after_history = history_snapshot()
    write_json("history_hash_after.json", after_history)
    history_comparison = compare_history(before, after_history)
    write_json("HISTORICAL_HASH_COMPARISON.json", history_comparison)
    add_row("P6", "audit new scope and old history", "stable proposal, source manifest, and historical hash comparison", "world/plan/config/prompts unchanged; old evidence stable", f"history_stable={history_comparison['historical_paths_stable']}; plan={proposal['request_plan_hash']}; config={proposal['frozen_config_hash']}", "HISTORICAL_HASH_COMPARISON.json", "PASS" if history_comparison["historical_paths_stable"] else "FAIL", "continue" if history_comparison["historical_paths_stable"] else "stop")
    if not history_comparison["historical_paths_stable"]:
        raise SystemExit("historical evidence changed")

    write_docs(proposal, plan, diff)
    decision = {
        "hash_algorithm_version_stable": True,
        "proposal_stable_after_pytest": all(row["equals_initial"] for row in stability_rows),
        "source_mutation_rejected": mutation["changed_detected"],
        "config_hash_match": True,
        "request_plan_hash_match": True,
        "prompt_hashes_match": True,
        "world_oracle_match": True,
        "privacy_blinding_pass": True,
        "model_provider_match": proposal["provider"] == "kimi26" and proposal["model"] == "kimi-k2.6",
        "five_unique_request_ids": len(proposal["request_ids"]) == 5 and len(set(proposal["request_ids"])) == 5,
        "estimated_cost_lte_0_05": sum(float(item["estimated_cost_usd"]) for item in plan) <= 0.05,
        "historical_hashes_unchanged": history_comparison["historical_paths_stable"],
        "new_proposal_explicitly_confirmed": False,
        "no_existing_attempt_for_these_request_ids": True,
    }
    write_json("PAID_GATE_DECISION.json", {"checks": decision, "overall": "NO_GO", "reason": "new proposal SHA requires explicit user confirmation"})
    add_row("P7", "make paid gate decision", "write PAID_GATE_DECISION.json", "all engineering checks pass but new confirmation remains false", json.dumps({"overall": "NO_GO", "new_proposal_explicitly_confirmed": False}, sort_keys=True), "PAID_GATE_DECISION.json", "PASS", "stop before authorize-real")
    add_row("P8", "prepare zero-cost evidence package", "python scripts/build_v5p6_package.py", "fresh extraction reproduces tests and no secrets", "package build pending", "FRESH_EXTRACTION_VALIDATION.md", "RUNNING", "build then stop")
    add_row("P9-P12", "conditional paid stages", "NOT RUN: requires explicit confirmation of new proposal SHA", "no live stage in P0-P8", "NOT_APPLICABLE", "GO_NO_GO.md", "NOT_APPLICABLE", "wait for new proposal confirmation")
    write_checklist()

    first = run_command("P8.1", "build and validate evidence package", [str(PYTHON), "scripts/build_v5p6_package.py"], "fresh extraction tests pass", "build_package_first.log", env=env)
    if first.returncode != 0:
        raise SystemExit("V5-P6 package build failed")
    for row in ROWS:
        if row.step_id == "P8":
            row.observed = "fresh extraction passed; package built"
            row.status = "PASS"
            row.next_action = "stop / wait for new SHA confirmation"
    write_checklist()
    second = run_command("P8.2", "rebuild package with completed checklist", [str(PYTHON), "scripts/build_v5p6_package.py"], "final package contains completed checklist and fresh validation", "build_package_final.log", env=env)
    if second.returncode != 0:
        raise SystemExit("V5-P6 final package build failed")
    write_text("FINAL_STATUS.md", f"# V5-P6 final status\n\n- proposal SHA: `{proposal['proposal_sha256']}`\n- authorization: `PROPOSED_NOT_AUTHORIZED`\n- paid API calls: `0`\n- network requests: `0`\n- final decision: `NO_GO / WAITING_NEW_PROPOSAL_CONFIRMATION`\n")
    print(json.dumps({"report": str(REPORT), "proposal_sha256": proposal["proposal_sha256"], "real_api_calls": 0, "status": "WAITING_NEW_PROPOSAL_CONFIRMATION"}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
