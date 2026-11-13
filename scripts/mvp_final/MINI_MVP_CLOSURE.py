#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only acceptance audit of Mini Science Society V5P13 evidence.

Only Python standard library. No network, no API key access, and no project writes.
It writes new audit outputs into a previously nonexistent output directory.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

REQ = {
    "rows": "14_FINAL_ANALYSIS/analysis/results_raw.csv",
    "ledger": "14_FINAL_ANALYSIS/combined_analysis_source/call_ledger.jsonl",
    "routes": "14_FINAL_ANALYSIS/analysis/stage1_router_proofs.csv",
    "pairs": "14_FINAL_ANALYSIS/analysis/paired_deltas_action.csv",
    "summary": "14_FINAL_ANALYSIS/analysis/overall_summary.json",
    "history": "03_HISTORY_IMMUTABILITY_CHECK.json",
    "remediation": "19_LEGACY_V3_OVERWRITE_REMEDIATION.json",
    "progress": "16_PROJECT_PROGRESS.json",
    "embedded_zip": "18_RESTRICTED_EVIDENCE.zip",
    "embedded_sha": "18_RESTRICTED_EVIDENCE_SHA256.json",
    "sensitivity": "08_LAW_INFORMATION_SENSITIVITY_AUDIT.csv",
    "baseline": "14_FINAL_ANALYSIS/analysis/baseline_comparison.csv",
}


class Evidence:
    def __init__(self, p):
        self.source = Path(p)
        self.z = zipfile.ZipFile(self.source) if self.source.is_file() else None
        if not self.z and not self.source.is_dir():
            raise FileNotFoundError(f"evidence not found: {self.source}")
        self.paths = self.z.namelist() if self.z else [x.relative_to(self.source).as_posix() for x in self.source.rglob('*') if x.is_file()]

    def get(self, suffix):
        matched = [p for p in self.paths if p == suffix or p.endswith('/' + suffix)]
        # Some inner archives may have overlapping file names; require unique match.
        if len(matched) != 1:
            raise ValueError(f"expected exactly one {suffix}; got {len(matched)}: {matched[:4]}")
        return self.z.read(matched[0]) if self.z else (self.source / matched[0]).read_bytes()

    def close(self):
        if self.z: self.z.close()


def read_csv(e, key):
    return list(csv.DictReader(io.StringIO(e.get(REQ[key]).decode('utf-8-sig'))))


def read_json(e, key):
    return json.loads(e.get(REQ[key]))


def yes(x):
    return str(x).lower() in ('true', '1', 'yes')


def safe_float(x):
    try:
        n = float(x)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def write_json(p, obj):
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--evidence', required=True, help='path to original 018 ZIP or extracted 018 directory')
    ap.add_argument('--out', required=True, help='new directory to create; must not already exist')
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        raise RuntimeError('Output exists: refusing to overwrite existing evidence/report: ' + str(out))
    # Source and output cannot overlap, and only write to a new folder.
    ev = Evidence(args.evidence)
    try:
        rows = read_csv(ev, 'rows')
        ledgers = [json.loads(line) for line in ev.get(REQ['ledger']).decode('utf-8-sig').splitlines() if line.strip()]
        routes = read_csv(ev, 'routes')
        input_pairs = read_csv(ev, 'pairs')
        summary = read_json(ev, 'summary')
        history = read_json(ev, 'history')
        remediation = read_json(ev, 'remediation')
        sensitivity = read_csv(ev, 'sensitivity')
        baselines = read_csv(ev, 'baseline')
        embedded = ev.get(REQ['embedded_zip'])
        stated_zip = read_json(ev, 'embedded_sha')
    finally:
        ev.close()
    if not rows or not ledgers:
        raise RuntimeError('Empty evidence tables')
    request_ids = [r.get('request_id') for r in ledgers]
    unique_req_ok = all(request_ids) and len(request_ids) == len(set(request_ids))
    complete_calls = [r for r in ledgers if r.get('request_status') == 'completed']
    failed_calls = [r for r in ledgers if r.get('request_status') != 'completed']
    model_ok = all(r.get('model_requested') == 'kimi-k2.6' and r.get('returned_model') == 'kimi-k2.6' for r in complete_calls)
    finished_rows = [r for r in rows if r.get('run_status') == 'COMPLETED' and yes(r.get('executed_scientific_output'))]
    strict_rows = [r for r in finished_rows if yes(r.get('fully_scientifically_valid'))]
    action_valid = [r for r in finished_rows if yes(r.get('action_valid'))]
    raw_acc = [safe_float(r.get('raw_agent_numeric_accuracy')) for r in finished_rows]
    if any(v is None for v in raw_acc):
        raise RuntimeError('At least one completed row lacks valid raw numerical accuracy')
    group = defaultdict(dict)
    for r in rows:
        key=(r['world_id'],r['replicate'])
        if r['condition'] in group[key]:
            raise RuntimeError('duplicate condition rows: ' + str(key) + ':' + r['condition'])
        group[key][r['condition']]=r
    route = {(r['world_id'],r['replicate']): r for r in routes}
    input_cd = {(r['world_id'], r['replicate']): r for r in input_pairs if r['contrast'] == 'C-D'}
    pair_records=[]
    for (world,rep), conditions in sorted(group.items()):
        c = conditions.get('C_SEQ2_TRANSFER')
        d = conditions.get('D_SEQ2_BLOCK')
        if not c or not d:
            pair_records.append(dict(world_id=world, replicate=rep, status='MISSING_CONDITION', action_delta='', reason='C or D row missing'))
            continue
        eligible = all(x.get('run_status') == 'COMPLETED' and yes(x.get('action_valid')) for x in [c,d])
        proof=route.get((world,rep),{})
        if not eligible:
            pair_records.append(dict(world_id=world, replicate=rep, status='UNDEFINED', action_delta='', reason='C or D unexecuted or invalid'))
            continue
        same_stage = bool(c.get('stage1_artifact_sha256')) and c['stage1_artifact_sha256'] == d['stage1_artifact_sha256']
        actual_route = (c.get('forwarded_artifact_sha256') == c.get('stage1_artifact_sha256')
            and d.get('route_intervention') == 'blocked'
            and d.get('forwarded_artifact_sha256') != d.get('stage1_artifact_sha256')
            and proof.get('status') == 'EXECUTED' and yes(proof.get('same_stage1_artifact'))
            and proof.get('d_route_intervention') == 'blocked')
        c_score=safe_float(c.get('top1_action_score'))
        d_score=safe_float(d.get('top1_action_score'))
        if c_score is None or d_score is None: raise RuntimeError('Completed CD pair lacks action score')
        original = input_cd.get((world,rep),{})
        report_delta=safe_float(original.get('delta'))
        check_delta=(original.get('status')=='ELIGIBLE' and report_delta is not None and abs(c_score-d_score-report_delta)<1e-7)
        pair_records.append(dict(world_id=world,replicate=rep,status='ELIGIBLE' if (same_stage and actual_route and check_delta) else 'ROUTE_OR_DELTA_MISMATCH',c_action=c.get('experiment_id_selected'),d_action=d.get('experiment_id_selected'),c_action_score=c_score,d_action_score=d_score,action_delta=c_score-d_score,strict_pair_valid=yes(c.get('fully_scientifically_valid')) and yes(d.get('fully_scientifically_valid')),same_stage1_artifact=same_stage,actual_program_block=actual_route,reported_delta_matches=check_delta,reason=''))
    completed_pairs = [p for p in pair_records if p['status']=='ELIGIBLE']
    invalid_pair_proofs = [p for p in pair_records if p['status']=='ROUTE_OR_DELTA_MISMATCH']
    all_pairs_same = all(p.get('c_action') == p.get('d_action') for p in completed_pairs)
    embedded_integrity=hashlib.sha256(embedded).hexdigest() == stated_zip['sha256'] and len(embedded)==stated_zip['size']
    nonconfirmatory = not strict_rows
    history_issue = history.get('status')=='FAIL' or bool(history.get('changed_historical_paths'))
    # Check totals against the independently supplied frozen summary.
    totals_match = len(rows)==summary['result_rows'] and len(ledgers)==summary['cumulative_unique_attempts'] and len(complete_calls)==summary['cumulative_completed_responses'] and len(failed_calls)==summary['cumulative_failed_or_unresolved'] and len(finished_rows)==summary['completed_scientific_rows']
    cd_source_count = sum(1 for r in input_pairs if r.get('contrast')=='C-D' and r.get('status')=='ELIGIBLE')
    mechanical_pass = (unique_req_ok and model_ok and embedded_integrity and totals_match and len(completed_pairs)==cd_source_count and len(completed_pairs)>=1 and not invalid_pair_proofs and len(action_valid)==len(finished_rows))
    metrics={
        'source':str(args.evidence),
        'audit_protocol':'READ_ONLY_MVP_ACTION_AND_PIPELINE_VALIDATION_V1',
        'real_calls':{'unique_attempts':len(ledgers),'completed':len(complete_calls),'failed_or_unresolved':len(failed_calls),'unique_request_ids':bool(unique_req_ok),'completed_model_identity_ok':model_ok},
        'science_rows':{'all_condition_slots':len(rows),'completed':len(finished_rows),'action_valid':len(action_valid),'strict_raw_valid':len(strict_rows),'mean_action_score':sum(safe_float(r['top1_action_score']) for r in finished_rows)/len(finished_rows),'mean_raw_agent_numeric_accuracy':sum(raw_acc)/len(raw_acc)},
        'paired_cd':{'eligible_pairs':len(completed_pairs),'eligible_worlds':sorted({p['world_id'] for p in completed_pairs}),'nonzero_deltas':sum(abs(p['action_delta'])>1e-8 for p in completed_pairs),'all_pairs_same_selected_action':all_pairs_same,'mean_action_delta':sum(p['action_delta'] for p in completed_pairs)/len(completed_pairs) if completed_pairs else None,'route_or_delta_mismatch_count':len(invalid_pair_proofs),'all_planned_pair_rows':len(pair_records)},
        'stage1':summary.get('stage1_summary'),
        'baselines_rows':len(baselines),
        'law_sensitivity_worlds':len(sensitivity),
        'cost_accounting':summary.get('cost_accounting'),
        'history':{'history_integrity_check':history.get('status'),'changed_historical_paths':history.get('changed_historical_paths'),'restoration_status':remediation.get('status'),'exact_prelock_restoration_unverified':history_issue},
        'checks':{'embedded_restricted_evidence_sha256_ok':embedded_integrity,'ledger_report_totals_match':totals_match,'request_ids_unique':bool(unique_req_ok),'finished_models_match':model_ok,'all_finished_actions_legal':len(action_valid)==len(finished_rows),'cd_routes_and_reported_deltas_match':not invalid_pair_proofs},
        'verdict':{
            'mvp_engineering_and_action_pipeline':'CONDITIONALLY_PASS_WITH_RECORDED_HISTORY_EXCEPTION' if mechanical_pass else 'FAIL_CHECK_INPUTS',
            'mvp_real_action_comparison':'COMPLETED_DESCRIPTIVE',
            'transfer_benefit_in_observed_pairs':'NOT_OBSERVED' if completed_pairs and not any(abs(p['action_delta'])>1e-8 for p in completed_pairs) else 'NEEDS_INTERPRETATION',
            'strict_raw_science':'FAIL_NO_FULLY_VALID_ROWS' if nonconfirmatory else 'SOME_VALID_ROWS',
            'paper_level_hypothesis':'NOT_ESTABLISHED',
            'does_not_require_more_api_calls':True,
        },
    }
    out.mkdir(parents=True)
    write_json(out/'MVP_ACCEPTANCE.json', metrics)
    cols=['world_id','replicate','status','c_action','d_action','c_action_score','d_action_score','action_delta','strict_pair_valid','same_stage1_artifact','actual_program_block','reported_delta_matches','reason']
    with open(out/'MVP_CD_AUDIT.csv','w',encoding='utf-8-sig',newline='') as f:
        dw=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');dw.writeheader();dw.writerows(pair_records)
    rep=f"""# Mini Science Society — 一次性最小系统验证（独立复核）

## 结论

- 工程与真实动作对照：**{'有条件通过' if mechanical_pass else '未通过（存在待修复的审计错误）'}**。
- 已有真实请求：{len(ledgers)}次尝试，{len(complete_calls)}次成功，{len(failed_calls)}次失败/未决。
- 完成科学结果：{len(finished_rows)}条；合法动作：{len(action_valid)}条；原始数值严格有效：{len(strict_rows)}条。
- 完整且路由核验通过的C/D：{len(completed_pairs)}组，涉及{len({p['world_id'] for p in completed_pairs})}个科学世界；平均C−D动作分差：{metrics['paired_cd']['mean_action_delta']}。
- 5组C/D结果{'均选择相同动作，未观察到规律传递的选题收益' if all_pairs_same else '存在不同的动作选择'}。
- **科学假设未被证实**；本次只可声称系统和动作层面的探索性验证，不能声称严格科学数值推理成功。
- 本工具仅访问证据并生成审计文件，**不会发送真实API请求**。

## 必须披露的限定

1. 计算器辅助结果属于确定性公式复算，不能当作Agent原始数学能力。
2. 数值错误导致原始严格科学有效数为{len(strict_rows)}，严格C−D不可估计；动作层C−D为描述性量。
3. 发生{len(failed_calls)}次未完成的真实调用；不可将缺失实验填成0差值。
4. 历史保护：{history.get('status')}，{len(history.get('changed_historical_paths', []))}份旧文件的原始SHA无法确认恢复。应附加审计例外，禁止伪造恢复。
5. Provider账单：{'已核实' if summary.get('cost_accounting',{}).get('provider_billing_verified') else '未核实'}；成功响应本地usage估算 ${summary.get('cost_accounting',{}).get('completed_response_usage_local_estimate_usd')}，不是供应商最终扣费。
6. 少量世界、重复依赖与实际传递利用不足，禁止作统计显著或普适结论。

## 验收明细

```json
{json.dumps(metrics['checks'],ensure_ascii=False,indent=2)}
```

## 输出

- `MVP_ACCEPTANCE.json`：所有核对和验收状态。
- `MVP_CD_AUDIT.csv`：各世界/重复的C/D动作、分差与路由验证。
- `MVP_FINAL_REPORT.md`：本报告。

**最终标准**：只要真实证据链与C/D路由可信、科学结果包括负结果得到完整报告，最小系统工程验证即告收官；严谨科学假设验证另列未完成，不能用工程通过替代。
"""
    (out/'MVP_FINAL_REPORT.md').write_text(rep,encoding='utf-8')
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file()}
    write_json(out/'MVP_SHA256.json',manifest)
    print(json.dumps({'verdict':metrics['verdict'],'checks':metrics['checks'],'out':str(out)},ensure_ascii=False,indent=2))
    return 0 if mechanical_pass else 2

if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('AUDIT_FATAL:', type(exc).__name__, str(exc), file=sys.stderr)
        sys.exit(2)
