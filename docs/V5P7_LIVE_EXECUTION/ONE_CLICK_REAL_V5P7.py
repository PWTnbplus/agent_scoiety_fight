#!/usr/bin/env python3
"""One run: surgical science-failure fix -> offline tests -> hash -> authorise -> paid pilot -> evidence.

This script DOES NOT ask for approval again. It is intended for the existing
user-authorised CV001 experiment, with a HARD 5-request/US$0.05 session limit.
There is no internet call until AFTER patches, tests and authorization succeed.

Call this script ONLY with --execute. Without --execute it prints its plan and
exits without any API request. Never store credential material in this script.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

CONDITIONS = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
MODEL = "kimi-k2.6"
PROVIDER = "kimi26"
WORLD = "CV001"
MAX_CALLS = 5
CAP_USD = 0.05
ORIGINAL_APPROVAL_CAP_USD = 2.00
CONFIRMATION = "V5P4_REAL_API_AUTHORIZED"

REPLACES = [
('''        if not bool(cache.get("valid")):
            return cache, response, f"stage1_schema_failure:{cache.get('reason', 'invalid_stage1')}"
''', '''        if not bool(cache.get("valid")):
            # V5-P4: an invalid scientific output is part of the experiment,
            # not a network, budget or identity failure. Retain neutral Stage1
            # and collect the paired C/D experimental outcomes.
            if str(config.score_version).startswith("v5p4"):
                _emit(events_path, "STAGE1_SCIENTIFIC_INVALID", run_id=run_id,
                      world_id=world_id, replicate=replicate, pair_id=pair_id,
                      reason=cache.get("reason", "invalid_stage1"), status="recorded")
                return cache, response, None
            return cache, response, f"stage1_schema_failure:{cache.get('reason', 'invalid_stage1')}"
'''),
('''        if not truth_checks["mapping_schema_valid"]:
            return cache, response, "stage1_mapping_check_failed"
''', '''        if not truth_checks["mapping_schema_valid"]:
            if str(config.score_version).startswith("v5p4"):
                _emit(events_path, "STAGE1_SCIENTIFIC_INVALID", run_id=run_id,
                      world_id=world_id, replicate=replicate, pair_id=pair_id,
                      reason="stage1_mapping_check_failed", status="recorded")
            else:
                return cache, response, "stage1_mapping_check_failed"
'''),
('''                if is_real_provider:
                    stop_reason = _real_result_failure_reason(row, require_stage1_mapping=condition in SEQ2_CONDITIONS)
''', '''                if is_real_provider:
                    scientific_issue = _real_result_failure_reason(row, require_stage1_mapping=condition in SEQ2_CONDITIONS)
                    if str(config.score_version).startswith("v5p4"):
                        # Keep scientific failures, continue with next experiment
                        # arm. Network, budget, identity and credential failures
                        # still abort via the technical exception paths.
                        if scientific_issue:
                            _emit(events_path, "SCIENTIFIC_OUTPUT_INVALID", run_id=run_id,
                                  world_id=world_id, replicate=replicate, pair_id=pair_id,
                                  condition=condition, reason=scientific_issue,
                                  status="recorded_continue")
                    else:
                        stop_reason = scientific_issue
'''),
]
TEST_OLD = '''def test_invalid_stage1_mapping_stops_before_downstream_calls(tmp_path):
    cache, reason, adapter, gate = _run_stage1_failure(tmp_path, _stage1_payload(variable_mapping={"source_concentration": "target_state", "source_minutes": "target_time"}))
    assert cache["valid"] is False
    assert reason.startswith("stage1_schema_failure:")
    assert adapter.calls == 1
    assert gate.summary()["calls_used"] == 1
'''
TEST_NEW = '''def test_invalid_stage1_mapping_is_scientific_failure_not_safety_abort(tmp_path):
    cache, reason, adapter, gate = _run_stage1_failure(tmp_path, _stage1_payload(variable_mapping={"source_concentration": "target_state", "source_minutes": "target_time"}))
    assert cache["valid"] is False
    assert reason is None
    assert adapter.calls == 1
    assert gate.summary()["calls_used"] == 1
'''


def run(cmd: list[str], root: Path, env: dict[str, str], output: Path | None = None) -> str:
    """Show exactly which command is executing, but never print a key."""
    pretty = " ".join('"***redacted***"' if "key" in str(x).lower() and str(x).endswith(".txt") else str(x) for x in cmd)
    print("RUN:", pretty, flush=True)
    p = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    result = (p.stdout or "") + (p.stderr or "")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"COMMAND: {pretty}\nEXIT: {p.returncode}\n" + result, encoding="utf-8")
    print((p.stdout or "")[-3500:], flush=True)
    if p.returncode != 0:
        print((p.stderr or "")[-3500:], flush=True)
        raise RuntimeError(f"Command failed (no automatic retry): {cmd[:5]}, exit={p.returncode}")
    return p.stdout or ""


def patch_once(root: Path, bundle: Path) -> None:
    runner = root / "src/mini_science/runner.py"
    tests = root / "tests/test_v5p4_paid_failfast.py"
    if not runner.is_file() or not tests.is_file():
        raise RuntimeError("Current directory is not the existing Mini Science Society repository")
    old = runner.read_text(encoding="utf-8")
    new = old
    for before, after in REPLACES:
        if new.count(before) == 1:
            new = new.replace(before, after)
        elif after in new:
            continue  # idempotent patch, never duplicate
        else:
            raise RuntimeError("Current local runner.py differs from uploaded V5-P6 snapshot. Inspect before changing it.")
    t = tests.read_text(encoding="utf-8")
    if TEST_OLD in t:
        t = t.replace(TEST_OLD, TEST_NEW)
    elif TEST_NEW not in t:
        raise RuntimeError("test_v5p4_paid_failfast.py unexpectedly differs; refusing broad rewrite")
    fixture_src = bundle / "tests/test_v5p7_collect_all_arms.py"
    fixture_dest = root / "tests/test_v5p7_collect_all_arms.py"
    if fixture_dest.exists() and fixture_dest.read_bytes() != fixture_src.read_bytes():
        raise RuntimeError("Existing V5-P7 test differs; refusing overwrite")
    if new != old:
        runner.write_text(new, encoding="utf-8")
    tests.write_text(t, encoding="utf-8")
    shutil.copyfile(fixture_src, fixture_dest)
    print("PATCH_APPLIED: scientific outputs do not stop other experimental arms; security/budget checks remain active", flush=True)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_new_proposal(root: Path, out_dir: Path):
    # Local src imports only. Never contact the model for a proposal.
    sys.path.insert(0, str(root / "src"))
    from mini_science.authorization import proposed_v5p4_authorization
    from mini_science.budget_plan import pilot_request_plan
    from mini_science.config import load_config
    from mini_science.proposal_fingerprint import proposal_digest
    from mini_science.stable_fingerprint import stable_tree_hash
    cfg = load_config(root / "config/v5p4_offline_dev.json")
    assert cfg.score_version.startswith("v5p4")
    plan = pilot_request_plan(root, cfg, worlds=[WORLD], conditions=CONDITIONS, repeats=1, input_rate=0.00095, output_rate=0.004)
    proposal = proposed_v5p4_authorization(root, cfg, provider=PROVIDER, model=MODEL, worlds=[WORLD], conditions=CONDITIONS, request_plan=plan, max_unique_provider_attempts=MAX_CALLS, max_estimated_cost_usd=CAP_USD)
    proposal.update({
        "proposal_version": "V5-P7-EXECUTION",
        "session_protocol": "v5p6_stable_hash",
        "hash_algorithm_version": "stable_tree_hash_v1",
        "source_tree_hash": stable_tree_hash(root / "src"),
        "tests_tree_hash": stable_tree_hash(root / "tests"),
        "scripts_tree_hash": stable_tree_hash(root / "scripts"),
        "public_world_tree_hash": stable_tree_hash(root / "data/worlds_v5p4_dev"),
        "private_fixture_tree_hash": stable_tree_hash(root / "private/worlds_v5p4_dev"),
        "docs_tree_hash": stable_tree_hash(root / "docs"),
        "generated_at": "offline_generation",
        "overall_prior_user_cap_usd": ORIGINAL_APPROVAL_CAP_USD,
    })
    if len(plan) != 5 or len({x['request_id'] for x in plan}) != 5:
        raise RuntimeError("Must freeze exactly five distinct requests")
    if sum(float(x['estimated_cost_usd']) for x in plan) > CAP_USD:
        raise RuntimeError("Plan exceeds more restrictive 0.05 USD session cap")
    proposal['proposal_sha256'] = proposal_digest(proposal)
    path = out_dir / "FROZEN_PROPOSAL.json"
    path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding="utf-8")
    print('NEW_PROPOSAL_SHA256:', proposal['proposal_sha256'])
    print('FROZEN_UNIQUE_CALLS:', len(plan), 'ESTIMATED_COST_USD:', sum(float(x['estimated_cost_usd']) for x in plan))
    return path, proposal


def main():
    parser = argparse.ArgumentParser(description="Execute the user-authorised bounded CV001 experiment in the local Windows project")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--execute", action="store_true", help="Run real paid API, within 5 calls / 0.05 USD estimate")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    bundle = Path(__file__).resolve().parent
    required = ["src/mini_science/runner.py", "config/v5p4_offline_dev.json", "data/worlds_v5p4_dev/CV001", "private/worlds_v5p4_dev/CV001"]
    if any(not (root/x).exists() for x in required):
        raise RuntimeError(f"Existing project missing required files: {root}")
    if not args.execute:
        print("DRY_RUN_ONLY: pass --execute to patch, test, authorize and run 5 real calls")
        return
    now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    output = root / "reports" / ("009_V5P7_LIVE_" + now)
    output.mkdir(parents=True, exist_ok=False)
    log = output / 'execution_steps.jsonl'
    def record(status, **fields):
        with log.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'status': status, **fields}, ensure_ascii=False, sort_keys=True) + '\n')
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root/'src') + os.pathsep + env.get('PYTHONPATH','')
    python = sys.executable
    try:
        record('STARTED', user_authorization='explicit_prior_cap_2usd_plus_current_start_instruction', per_session_cap_usd=CAP_USD, unique_requests=5)
        # Existing key is read in memory only by the adapter; never copied here.
        key = Path(env['KIMI26_KEY_FILE']) if env.get('KIMI26_KEY_FILE') else Path(r'E:\master_exp\nature_prj1_cal\from_llm_to_agent\api_key\kimi\kimi-k2.6.txt')
        if not key.is_file():
            raise RuntimeError('Existing KIMI26_KEY_FILE could not be found. Set the environment variable to the existing file path. No request made.')
        patch_once(root, bundle)
        record('PATCH_OK')
        run([python, '-m', 'pytest', '-q'], root, env, output/'pytest.log')
        run([python, '-m', 'mini_science.cli', 'validate-worlds', '--config', 'config/v5p4_offline_dev.json'], root, env, output/'validate_worlds.log')
        record('OFFLINE_TESTS_PASSED')
        path, proposal = create_new_proposal(root, output)
        record('PROPOSAL_FROZEN', sha256=proposal['proposal_sha256'], request_plan_hash=proposal['request_plan_hash'])
        auth_cmd = [python,'-m','mini_science.cli','authorize-real', '--config','config/v5p4_offline_dev.json',
            '--approved-by','user_explicit','--provider','kimi26','--model','kimi-k2.6',
            '--scope','pilot','--worlds','CV001', '--conditions', ','.join(CONDITIONS),
            '--max-calls','5','--max-estimated-cost-usd','0.05',
            '--confirmation',CONFIRMATION,
            '--authorization-note','User approved up to USD 2 and explicitly directed start now; run is limited to frozen CV001 5-call USD 0.05 session; no retry',
            '--proposal-file',str(path),'--proposal-sha256',proposal['proposal_sha256']]
        stdout=run(auth_cmd,root,env,output/'authorize.log')
        auth=json.loads(stdout.strip().splitlines()[-1]); session=Path(auth['session_dir'])
        record('AUTHORIZED', session=str(session), sha256=proposal['proposal_sha256'])
        run_dir = root / 'runs' / ('real_v5p7_cv001_' + now)
        # One actual invocation executes A, B, shared Stage1, C, D sequentially.
        pilot_cmd=[python,'-m','mini_science.cli','pilot',
            '--config','config/v5p4_offline_dev.json', '--provider','kimi26', '--allow-paid-api',
            '--worlds','CV001','--conditions',','.join(CONDITIONS),'--repeats','1',
            '--max-calls','5','--max-estimated-cost-usd','0.05',
            '--kimi26-max-cost-usd','0.05','--kimi26-max-output-tokens','900',
            '--kimi26-key-file',str(key), '--session-dir',str(session), '--run-dir',str(run_dir)]
        record('PAID_CALL_BEGIN', run_dir=str(run_dir))
        pilot_error=None
        try:
            run(pilot_cmd,root,env,output/'pilot.log')
        except Exception as err:
            pilot_error=str(err)
            record('PAID_CALL_ERROR',error=pilot_error)
        ledger=session/'attempt_ledger.jsonl'
        state=session/'gate_state.json'
        attempts=[]
        if ledger.exists():
            attempts=[json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines() if line.strip()]
        unique={str(x['request_id']) for x in attempts if x.get('request_id')}
        results=[]
        results_csv=run_dir/'results.csv'
        if results_csv.exists():
            with results_csv.open(encoding='utf-8',newline='') as f:
                results=list(csv.DictReader(f))
        bycondition={r.get('condition'):r for r in results}
        raw_ledger = run_dir / 'call_ledger.jsonl'
        provider_rows = []
        if raw_ledger.exists():
            provider_rows = [json.loads(line) for line in raw_ledger.read_text(encoding='utf-8').splitlines() if line.strip()]
        successful = [item for item in provider_rows if item.get('request_status') == 'completed']
        token_input = sum(int(item.get('actual_input_tokens') or 0) for item in successful)
        token_output = sum(int(item.get('actual_output_tokens') or 0) for item in successful)
        local_cost = sum(float(item.get('local_response_estimate_usd') or 0.0) for item in successful)
        bill_verified = bool(successful) and all(item.get('billing_source') == 'PROVIDER_BILL' for item in successful)
        billed_cost = sum(float(item.get('provider_billed_cost_usd') or 0.0) for item in successful) if bill_verified else None
        def checked_delta(c1, c2, key, validity_key):
            left, right = bycondition.get(c1), bycondition.get(c2)
            if not left or not right:
                return None
            if str(left.get(validity_key, '')).lower() not in ('true', '1'):
                return None
            if str(right.get(validity_key, '')).lower() not in ('true', '1'):
                return None
            try:
                return float(left[key]) - float(right[key])
            except (ValueError, TypeError, KeyError):
                return None
        contrasts = {
            'B_minus_A_strict': checked_delta('B_SINGLE_RELATED','A_TARGET_ONLY','top1_score','fully_scientifically_valid'),
            'C_minus_D_strict': checked_delta('C_SEQ2_TRANSFER','D_SEQ2_BLOCK','top1_score','fully_scientifically_valid'),
            'B_minus_A_action_only': checked_delta('B_SINGLE_RELATED','A_TARGET_ONLY','top1_action_score','action_valid'),
            'C_minus_D_action_only': checked_delta('C_SEQ2_TRANSFER','D_SEQ2_BLOCK','top1_action_score','action_valid'),
        }
        summary={
            'run_dir':str(run_dir),'session_dir':str(session), 'frozen_proposal_sha':proposal['proposal_sha256'],
            'provider':PROVIDER,'model':MODEL,'world':WORLD,
            'unique_provider_attempt_ids':len(unique),
            'completed_final_conditions':list(bycondition),
            'condition_validity':{c: {k:bycondition.get(c,{}).get(k) for k in ['valid','fully_scientifically_valid','action_valid','top1_score','top1_action_score','model_numeric_valid','invalid_reason','run_status','selected_action']} for c in CONDITIONS},
            'pilot_error':pilot_error,
            'billing_is_provider_verified':bill_verified,
            'provider_billed_cost_usd': billed_cost,
            'local_usage_based_cost_usd':local_cost,
            'actual_input_tokens':token_input,
            'actual_output_tokens':token_output,
            'contrasts':contrasts,
            'estimated_spend_upper_bound':sum(float(x['estimated_cost_usd']) for x in proposal['request_plan']),
            'historical_user_cap_usd':ORIGINAL_APPROVAL_CAP_USD,
            'session_cap_usd':CAP_USD,
        }
        if state.exists():
            summary['session_state']=json.loads(state.read_text(encoding='utf-8'))
        (output/'REAL_EXECUTION_RESULT.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        record('FINALIZED',unique_requests=len(unique), conditions=len(bycondition), run_dir=str(run_dir))
        # Evidence files only: source and private secrets are excluded.
        with zipfile.ZipFile(output/'REAL_EXPERIMENT_EVIDENCE.zip','w', zipfile.ZIP_DEFLATED) as z:
            for file in sorted(output.iterdir()):
                if file.is_file() and file.suffix.lower() in {'.json','.jsonl','.log'}:
                    z.write(file, 'report/'+file.name)
            for relative in ['manifest.json','results.csv','report.md','paired_deltas.csv','events.jsonl','call_ledger.jsonl','attempt_results.jsonl']:
                f=run_dir/relative
                if f.is_file(): z.write(f, 'run/'+relative)
            for relative in ['authorization.json','gate_state.json','attempt_ledger.jsonl','planned_requests.jsonl']:
                f=session/relative
                if f.is_file(): z.write(f, 'session/'+relative)
        print('\n>>> ACTUAL TEST FINISHED (or stopped on recorded technical failure).')
        print('RESULT JSON:',output/'REAL_EXECUTION_RESULT.json')
        print('EVIDENCE ZIP:',output/'REAL_EXPERIMENT_EVIDENCE.zip')
        if pilot_error: raise RuntimeError('Technical failure during actual pilot; preserved evidence. Do not auto-retry.')
        if len(unique)!=5 or any(c not in bycondition for c in CONDITIONS):
            raise RuntimeError('Experiment incomplete: fewer than 5 attempts / 4 conditions; evidence preserved. Do not auto-retry.')
        print('COMPLETED_ALL_FIVE_REQUESTS: true')
    except Exception as e:
        record('STOPPED_WITH_EVIDENCE',error=f'{type(e).__name__}: {str(e)}')
        print('STOPPED:',str(e),flush=True)
        print('EVIDENCE_LOCATION:',output,flush=True)
        raise

if __name__=='__main__':
    main()
