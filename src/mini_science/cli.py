from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .analysis import write_cheap_baselines, write_oracle_audit, write_report
from .authorization import CONFIRMATION_PHRASE, V4_CONFIRMATION_PHRASE, V5P4_CONFIRMATION_PHRASE, V5P8_CONFIRMATION_PHRASE, V5P11_CONFIRMATION_PHRASE, advance_stage, create_authorization, create_v4_authorization, create_v5p4_authorization, create_v5p8_authorization, create_v5p11_authorization
from .budget_plan import check_api_request_plan, pilot_request_plan
from .config import load_config, project_root_from_config
from .experiment_plan import build_plan, write_plan
from .protocol_checks import check_api_response
from .real_gate import PersistentRealGate
from .real_reports import write_g1_report
from .runner import _append_jsonl, _json_write, _response_meta, make_adapter, probe_role, run_pilot
from .world_registry import resolve_worlds
from .worldgen import generate_worlds, validate_worlds


def _parse_csv(value: str, allowed: list[str], label: str) -> list[str]:
    if value.strip().lower() == "all":
        return list(allowed)
    selected = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(selected) - set(allowed))
    if unknown:
        raise ValueError(f"unknown {label}: {', '.join(unknown)}")
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mini Science Society synthetic experiment")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("init", "generate", "validate-worlds"):
        command = sub.add_parser(name)
        command.add_argument("--config", default="config/pilot.json")

    smoke = sub.add_parser("smoke")
    smoke.add_argument("--config", default="config/pilot.json")
    smoke.add_argument("--provider", choices=["mock", "behavioral-mock", "existing", "kimi26"], default="mock")
    smoke.add_argument("--world", default="W001")
    smoke.add_argument("--allow-paid-api", action="store_true")
    smoke.add_argument("--run-dir")
    smoke.add_argument("--kimi26-key-file")
    smoke.add_argument("--kimi26-base-url")
    smoke.add_argument("--kimi26-timeout", type=float)
    smoke.add_argument("--kimi26-max-cost-usd", type=float)
    smoke.add_argument("--kimi26-max-output-tokens", type=int, default=1200)
    smoke.add_argument("--behavioral-scenario", choices=["constant", "transfer_sensitive", "transfer_ignored", "bad_stage1", "bad_final", "citation_leak"], default="constant")

    pilot = sub.add_parser("pilot")
    pilot.add_argument("--config", default="config/pilot.json")
    pilot.add_argument("--provider", choices=["mock", "behavioral-mock", "existing", "kimi26"], default="mock")
    pilot.add_argument("--worlds", default="all")
    pilot.add_argument("--conditions", default="all")
    pilot.add_argument("--repeats", type=int, default=None)
    pilot.add_argument("--replicate-indices", help="absolute repeat indices to execute, e.g. 1; defaults to all repeats")
    pilot.add_argument("--request-namespace", help="unique request/pair namespace for a new independent experiment")
    pilot.add_argument("--allow-paid-api", action="store_true")
    pilot.add_argument("--run-dir")
    pilot.add_argument("--retry-failed", action="store_true")
    pilot.add_argument("--max-calls", type=int, default=None, help="V3 real-provider global attempt cap override")
    pilot.add_argument("--max-estimated-cost-usd", type=float, default=None, help="V3 real-provider global estimate cap override")
    pilot.add_argument("--v4-session-dir", help="independent V4 authorized session directory; required for V4 real pilot")
    pilot.add_argument("--session-dir", help="independent V5-P4 authorized session directory; required for V5-P4 real pilot")
    pilot.add_argument("--kimi26-key-file")
    pilot.add_argument("--kimi26-base-url")
    pilot.add_argument("--kimi26-timeout", type=float)
    pilot.add_argument("--kimi26-max-cost-usd", type=float)
    pilot.add_argument("--kimi26-max-output-tokens", type=int, default=1200)
    pilot.add_argument("--behavioral-scenario", choices=["constant", "transfer_sensitive", "transfer_ignored", "bad_stage1", "bad_final", "citation_leak"], default="constant")

    report = sub.add_parser("report")
    report.add_argument("--run-dir", required=True)

    oracle = sub.add_parser("audit-oracle")
    oracle.add_argument("--config", default="config/pilot_v2.json")
    oracle.add_argument("--output", default="reports/v2_oracle_audit.csv")

    plan = sub.add_parser("plan")
    plan.add_argument("--config", default="config/pilot_v2.json")
    plan.add_argument("--run-id", default="v2_plan")
    plan.add_argument("--worlds", default="all")
    plan.add_argument("--conditions", default="all")
    plan.add_argument("--repeats", type=int, default=None)

    check = sub.add_parser("check-api")
    check.add_argument("--config", default="config/real_gate_v3.json")
    check.add_argument("--provider", choices=["existing", "kimi26"], default="existing")
    check.add_argument("--allow-paid-api", action="store_true")
    check.add_argument("--max-calls", type=int, default=1)
    check.add_argument("--kimi26-key-file")
    check.add_argument("--kimi26-base-url")
    check.add_argument("--kimi26-timeout", type=float)
    check.add_argument("--kimi26-max-cost-usd", type=float)
    check.add_argument("--kimi26-max-output-tokens", type=int, default=32)

    authorize = sub.add_parser("authorize-real")
    authorize.add_argument("--config", default="config/real_gate_v3.json")
    authorize.add_argument("--approved-by", required=True)
    authorize.add_argument("--provider", default="kimi26")
    authorize.add_argument("--model", default="kimi-k2.6")
    authorize.add_argument("--scope", default="check-api,probe-role,pilot")
    authorize.add_argument("--worlds", default="W001")
    authorize.add_argument("--conditions", default="A_TARGET_ONLY,B_SINGLE_RELATED,C_SEQ2_TRANSFER,D_SEQ2_BLOCK")
    authorize.add_argument("--max-calls", type=int, required=True)
    authorize.add_argument("--max-estimated-cost-usd", type=float, required=True)
    authorize.add_argument("--repeats", type=int, help="V5-P8 repeat count; defaults to the bound proposal or config")
    authorize.add_argument("--replicate-indices", help="absolute repeat indices to authorize, e.g. 2,3; defaults to all repeats")
    authorize.add_argument("--request-namespace", help="unique request/pair namespace bound into a new V5-P8 proposal")
    authorize.add_argument("--confirmation", required=True, help=f"V3: {CONFIRMATION_PHRASE}; V4: {V4_CONFIRMATION_PHRASE}; V5-P4: {V5P4_CONFIRMATION_PHRASE}; V5-P8: {V5P8_CONFIRMATION_PHRASE}; V5-P11: {V5P11_CONFIRMATION_PHRASE}")
    authorize.add_argument("--authorization-note", required=True)
    authorize.add_argument("--proposal-file", help="V5-P4/V5-P5 complete proposal JSON to bind to the new session")
    authorize.add_argument("--proposal-sha256", help="SHA256 of the complete proposal JSON excluding its stored proposal_sha256 field")

    advance = sub.add_parser("advance-real-stage")
    advance.add_argument("--config", default="config/real_gate_v3.json")
    advance.add_argument("--stage", choices=["check-api", "probe-role", "pilot"], required=True)
    advance.add_argument("--confirmation", required=True, help=f"must equal {CONFIRMATION_PHRASE}")

    probe = sub.add_parser("probe-role")
    probe.add_argument("--config", default="config/pilot_v2.json")
    probe.add_argument("--provider", choices=["mock", "behavioral-mock", "existing", "kimi26"], default="kimi26")
    probe.add_argument("--world", default="W001")
    probe.add_argument("--role", choices=["single_question_designer", "pattern_extractor", "question_designer"], required=True)
    probe.add_argument("--allow-paid-api", action="store_true")
    probe.add_argument("--max-calls", type=int, default=1)
    probe.add_argument("--kimi26-key-file")
    probe.add_argument("--kimi26-base-url")
    probe.add_argument("--kimi26-timeout", type=float)
    probe.add_argument("--kimi26-max-cost-usd", type=float)
    probe.add_argument("--kimi26-max-output-tokens", type=int, default=800)
    probe.add_argument("--behavioral-scenario", choices=["constant", "transfer_sensitive", "transfer_ignored", "bad_stage1", "bad_final", "citation_leak"], default="constant")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            path = write_report(args.run_dir)
            print(path)
            return 0
        if args.command == "audit-oracle":
            config = load_config(args.config)
            root = project_root_from_config(args.config)
            path = write_oracle_audit(root, config, root / args.output)
            write_cheap_baselines(root, config, root / "reports" / "v3" / "cheap_baselines.csv")
            print(path)
            return 0
        if args.command == "check-api":
            if not args.allow_paid_api:
                raise PermissionError("check-api is blocked without --allow-paid-api; no network request was attempted")
            if args.max_calls != 1:
                raise ValueError("check-api requires --max-calls 1")
            config = load_config(args.config)
            root = project_root_from_config(args.config)
            adapter = make_adapter(args.provider, True, config=config, key_file=args.kimi26_key_file, base_url=args.kimi26_base_url, timeout=args.kimi26_timeout, max_cost_usd=args.kimi26_max_cost_usd, max_output_tokens=args.kimi26_max_output_tokens)
            budget_plan = check_api_request_plan(max_output_tokens=args.kimi26_max_output_tokens, input_rate=float(getattr(adapter, "input_cost_per_1k", 0.00095)), output_rate=float(getattr(adapter, "output_cost_per_1k", 0.004)))
            gate = PersistentRealGate(root, config, run_max_calls=1, run_max_cost_usd=args.kimi26_max_cost_usd)
            estimated_cost = budget_plan[0]["estimated_cost_usd"]
            gate.preflight(provider=args.provider, model=adapter.model_name, allow_paid_api=True, stage="check-api", request_plan=budget_plan)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            run_dir = root / "runs" / f"real_kimi26_g1_{stamp}"
            run_dir.mkdir(parents=True, exist_ok=False)
            events_path = run_dir / "events.jsonl"
            ledger_path = run_dir / "call_ledger.jsonl"
            request_messages = [{"role": "user", "content": 'Reply with exactly {"status":"ok"}.'}]
            _json_write(run_dir / "request.json", {"provider": args.provider, "requested_model": adapter.model_name, "max_output_tokens": args.kimi26_max_output_tokens, "request_hash": budget_plan[0]["prompt_hash"], "messages": request_messages, "budget_plan": budget_plan})
            _append_jsonl(events_path, {"event_type": "REQUEST_STARTED", "stage": "check-api", "request_id": budget_plan[0]["request_id"], "request_hash": budget_plan[0]["prompt_hash"], "max_output_tokens": args.kimi26_max_output_tokens})
            reservation = gate.reserve(request_id=budget_plan[0]["request_id"], provider=args.provider, model=adapter.model_name, stage="check-api", estimated_cost_usd=estimated_cost)
            try:
                response = adapter.complete(request_messages, args.kimi26_max_output_tokens)
                gate.finish(reservation, status="COMPLETED", actual_cost_usd=response.cost_usd, billing_verified=bool((response.metadata or {}).get("provider_billing_verified")), returned_model=(response.metadata or {}).get("returned_model"))
                _append_jsonl(ledger_path, {"request_id": budget_plan[0]["request_id"], "attempt_number": 1, "provider": args.provider, "model_requested": adapter.model_name, "returned_model": (response.metadata or {}).get("returned_model"), "request_hash": budget_plan[0]["prompt_hash"], "response_hash": __import__("hashlib").sha256(response.text.encode("utf-8")).hexdigest(), "input_tokens": response.input_tokens, "output_tokens": response.output_tokens, "usage_source": "provider_usage" if (response.metadata or {}).get("usage_verified") else ("ESTIMATED" if response.input_tokens is not None and response.output_tokens is not None else "MISSING"), "billing_source": "PROVIDER_BILL" if (response.metadata or {}).get("provider_billing_verified") else "UNVERIFIED", "finish_reason": (response.metadata or {}).get("finish_reason"), "estimated_cost_usd": estimated_cost, "provider_billed_cost_usd": response.cost_usd if (response.metadata or {}).get("provider_billing_verified") else None, "status": "COMPLETED"})
            except Exception as exc:
                gate.finish(reservation, status="FAILED", error=str(exc)[:500])
                _append_jsonl(ledger_path, {"request_id": budget_plan[0]["request_id"], "attempt_number": 1, "provider": args.provider, "model_requested": adapter.model_name, "request_hash": budget_plan[0]["prompt_hash"], "usage_source": "MISSING", "billing_source": "UNVERIFIED", "estimated_cost_usd": estimated_cost, "status": "FAILED", "error": f"{type(exc).__name__}:{str(exc)[:500]}"})
                _append_jsonl(events_path, {"event_type": "RESPONSE_FAILED", "stage": "check-api", "request_id": budget_plan[0]["request_id"], "error": f"{type(exc).__name__}:{str(exc)[:500]}"})
                _json_write(run_dir / "manifest.json", {"run_id": run_dir.name, "provider": args.provider, "requested_model": adapter.model_name, "real_api_status": "FAILED", "gate_summary": gate.summary(), "budget_plan": budget_plan})
                raise
            result = check_api_response(response, requested_model=adapter.model_name, request_attempts=1)
            result.update({"provider": args.provider, "cost_usd": response.cost_usd, "input_tokens": response.input_tokens, "output_tokens": response.output_tokens, "root": str(root), "gate_summary": gate.summary(), "budget_plan": budget_plan})
            _append_jsonl(events_path, {"event_type": "RESPONSE_RECEIVED", "stage": "check-api", "request_id": budget_plan[0]["request_id"], "response_hash": result["response_hash"], "returned_model": result["returned_model"], "usage_source": result["usage_source"], "finish_reason": (response.metadata or {}).get("finish_reason"), "gate_result": result["gate_result"]})
            _json_write(run_dir / "response.json", {"raw_text": response.text, "response": _response_meta(response), "contract_check": result})
            _json_write(run_dir / "manifest.json", {"run_id": run_dir.name, "provider": args.provider, "requested_model": adapter.model_name, "real_api_status": "COMPLETED" if result["gate_result"] == "PASS" else "FAILED", "gate_summary": gate.summary(), "budget_plan": budget_plan, "contract_check": result})
            write_g1_report(root, run_dir=run_dir, result=result, budget_plan=budget_plan, gate_summary=gate.summary())
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["gate_result"] == "PASS" else 2

        if args.command == "authorize-real":
            config = load_config(args.config)
            root = project_root_from_config(args.config)
            worlds = resolve_worlds(root, config, args.worlds)
            conditions = _parse_csv(args.conditions, list(config.allowed_conditions or config.conditions), "condition")
            scope = [item.strip() for item in args.scope.split(",") if item.strip()]
            if str(config.score_version).startswith("v4"):
                if scope != ["pilot"]:
                    raise ValueError("V4 authorization scope must be exactly pilot")
                proposal_path = root / "reports" / "v4_preflight" / "V4_PROPOSED_AUTHORIZATION.json"
                proposal = json.loads(proposal_path.read_text(encoding="utf-8")) if proposal_path.exists() else {}
                path = create_v4_authorization(root, config, approved_by=args.approved_by, provider=args.provider, model=args.model, worlds=worlds, conditions=conditions, max_unique_provider_attempts=args.max_calls, max_estimated_cost_usd=args.max_estimated_cost_usd, confirmation=args.confirmation, authorization_note=args.authorization_note, protocol_hash=str(proposal.get("protocol_hash", "")))
                print(json.dumps({"authorization_manifest": str(path), "session_dir": str(path.parent), "provider": args.provider, "model": args.model, "scope": scope, "worlds": worlds, "conditions": conditions, "max_unique_provider_attempts": args.max_calls, "max_estimated_cost_usd": args.max_estimated_cost_usd, "confirmation_phrase_accepted": True}, ensure_ascii=False, sort_keys=True))
                return 0
            if str(config.score_version).startswith("v5p4"):
                if scope != ["pilot"]:
                    raise ValueError("V5-P4 authorization scope must be exactly pilot")
                if worlds != ["CV001"] or conditions != ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]:
                    raise ValueError("V5-P4 authorization scope must be CV001 A/B/C/D")
                if not args.proposal_file or not args.proposal_sha256:
                    raise PermissionError("V5-P4 authorization requires --proposal-file and --proposal-sha256")
                adapter = make_adapter(args.provider, True, config=config, max_output_tokens=900)
                plan = pilot_request_plan(root, config, worlds=worlds, conditions=conditions, repeats=1, input_rate=float(getattr(adapter, "input_cost_per_1k", 0.00095)), output_rate=float(getattr(adapter, "output_cost_per_1k", 0.004)))
                path = create_v5p4_authorization(root, config, approved_by=args.approved_by, provider=args.provider, model=args.model, worlds=worlds, conditions=conditions, max_unique_provider_attempts=args.max_calls, max_estimated_cost_usd=args.max_estimated_cost_usd, confirmation=args.confirmation, authorization_note=args.authorization_note, request_plan=plan, proposal_path=args.proposal_file, proposal_sha256=args.proposal_sha256, require_proposal_binding=True)
                print(json.dumps({"authorization_manifest": str(path), "session_dir": str(path.parent), "provider": args.provider, "model": args.model, "scope": scope, "worlds": worlds, "conditions": conditions, "max_unique_provider_attempts": args.max_calls, "max_estimated_cost_usd": args.max_estimated_cost_usd, "confirmation_phrase_accepted": True}, ensure_ascii=False, sort_keys=True))
                return 0
            if str(config.score_version).startswith("v5p8"):
                if scope != ["pilot"]:
                    raise ValueError("V5-P8 authorization scope must be exactly pilot")
                expected_worlds = ["CV001", "CV002", "CV003", "CV004"]
                expected_conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
                if not worlds or any(world not in expected_worlds for world in worlds):
                    raise ValueError("V5-P8 authorization worlds must be a non-empty subset of CV001-CV004")
                if not conditions or conditions != [condition for condition in expected_conditions if condition in conditions]:
                    raise ValueError("V5-P8 authorization conditions must be an ordered subset of A/B/C/D")
                if not args.proposal_file or not args.proposal_sha256:
                    raise PermissionError("V5-P8 authorization requires --proposal-file and --proposal-sha256")
                proposal_hint = json.loads(Path(args.proposal_file).read_text(encoding="utf-8"))
                proposal_repeats = int(args.repeats if args.repeats is not None else proposal_hint.get("repeats", config.repeats))
                proposal_namespace = args.request_namespace if args.request_namespace is not None else proposal_hint.get("request_namespace")
                replicate_indices = None if args.replicate_indices is None else [int(value.strip()) for value in args.replicate_indices.split(",") if value.strip()]
                adapter = make_adapter(args.provider, True, config=config, max_output_tokens=900)
                plan = pilot_request_plan(root, config, worlds=worlds, conditions=conditions, repeats=proposal_repeats, replicate_indices=replicate_indices, request_namespace=proposal_namespace, input_rate=float(getattr(adapter, "input_cost_per_1k", 0.00095)), output_rate=float(getattr(adapter, "output_cost_per_1k", 0.004)))
                path = create_v5p8_authorization(root, config, approved_by=args.approved_by, provider=args.provider, model=args.model, worlds=worlds, conditions=conditions, repeats=proposal_repeats, request_namespace=proposal_namespace, max_unique_provider_attempts=args.max_calls, max_estimated_cost_usd=args.max_estimated_cost_usd, confirmation=args.confirmation, authorization_note=args.authorization_note, request_plan=plan, proposal_path=args.proposal_file, proposal_sha256=args.proposal_sha256, require_proposal_binding=True)
                print(json.dumps({"authorization_manifest": str(path), "session_dir": str(path.parent), "provider": args.provider, "model": args.model, "scope": scope, "worlds": worlds, "conditions": conditions, "max_unique_provider_attempts": args.max_calls, "max_estimated_cost_usd": args.max_estimated_cost_usd, "confirmation_phrase_accepted": True}, ensure_ascii=False, sort_keys=True))
                return 0
            if str(config.score_version).startswith("v5p11"):
                if scope != ["pilot"]:
                    raise ValueError("V5-P11 authorization scope must be exactly pilot")
                expected_conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
                if not args.proposal_file or not args.proposal_sha256:
                    raise PermissionError("V5-P11 authorization requires --proposal-file and --proposal-sha256")
                proposal_hint = json.loads(Path(args.proposal_file).read_text(encoding="utf-8"))
                is_remainder = proposal_hint.get("protocol_variant") == "v5p12_remainder"
                is_v5p13 = proposal_hint.get("protocol_variant") == "v5p13_iv002_followup"
                is_v5p15 = proposal_hint.get("protocol_variant") == "v5p15_research"
                expected_worlds = list(proposal_hint.get("worlds", [])) if is_v5p15 else (["IV002"] if is_v5p13 else (["IV002", "IV003", "IV004"] if is_remainder else ["IV001", "IV002", "IV003", "IV004"]))
                expected_conditions = list(proposal_hint.get("conditions", [])) if is_v5p15 else expected_conditions
                if worlds != expected_worlds or conditions != expected_conditions:
                    raise ValueError("V5-P11 authorization scope does not match the bound proposal")
                proposal_repeats = int(args.repeats if args.repeats is not None else proposal_hint.get("repeats", config.repeats))
                proposal_namespace = args.request_namespace if args.request_namespace is not None else proposal_hint.get("request_namespace")
                replicate_indices = None if args.replicate_indices is None else [int(value.strip()) for value in args.replicate_indices.split(",") if value.strip()]
                adapter = make_adapter(args.provider, True, config=config, max_output_tokens=900)
                plan = pilot_request_plan(root, config, worlds=worlds, conditions=conditions, repeats=proposal_repeats, replicate_indices=replicate_indices, request_namespace=proposal_namespace, input_rate=float(getattr(adapter, "input_cost_per_1k", 0.00095)), output_rate=float(getattr(adapter, "output_cost_per_1k", 0.004)))
                path = create_v5p11_authorization(root, config, approved_by=args.approved_by, provider=args.provider, model=args.model, worlds=worlds, conditions=conditions, repeats=proposal_repeats, request_namespace=proposal_namespace, max_unique_provider_attempts=args.max_calls, max_estimated_cost_usd=args.max_estimated_cost_usd, confirmation=args.confirmation, authorization_note=args.authorization_note, request_plan=plan, proposal_path=args.proposal_file, proposal_sha256=args.proposal_sha256, require_proposal_binding=True)
                print(json.dumps({"authorization_manifest": str(path), "session_dir": str(path.parent), "provider": args.provider, "model": args.model, "scope": scope, "worlds": worlds, "conditions": conditions, "max_unique_provider_attempts": args.max_calls, "max_estimated_cost_usd": args.max_estimated_cost_usd, "confirmation_phrase_accepted": True}, ensure_ascii=False, sort_keys=True))
                return 0
            path = create_authorization(root, config, approved_by=args.approved_by, provider=args.provider, model=args.model, scope=scope, worlds=worlds, conditions=conditions, max_unique_provider_attempts=args.max_calls, max_estimated_cost_usd=args.max_estimated_cost_usd, confirmation=args.confirmation, authorization_note=args.authorization_note)
            print(json.dumps({"authorization_manifest": str(path), "provider": args.provider, "model": args.model, "scope": scope, "worlds": worlds, "conditions": conditions, "max_unique_provider_attempts": args.max_calls, "max_estimated_cost_usd": args.max_estimated_cost_usd, "confirmation_phrase_accepted": True}, ensure_ascii=False, sort_keys=True))
            return 0

        if args.command == "advance-real-stage":
            root = project_root_from_config(args.config)
            path = advance_stage(root, target_stage=args.stage, confirmation=args.confirmation)
            print(json.dumps({"authorization_manifest": str(path), "current_stage": args.stage, "confirmation_phrase_accepted": True}, ensure_ascii=False, sort_keys=True))
            return 0

        config = load_config(args.config)
        root = project_root_from_config(args.config)
        if args.command == "probe-role":
            probe_worlds = resolve_worlds(root, config, args.world)
            if len(probe_worlds) != 1:
                raise ValueError("probe-role requires exactly one world")
            path = probe_role(root, config, provider=args.provider, world_id=args.world, role=args.role, allow_paid_api=args.allow_paid_api, max_calls=args.max_calls, kimi26_key_file=args.kimi26_key_file, kimi26_base_url=args.kimi26_base_url, kimi26_timeout=args.kimi26_timeout, kimi26_max_cost_usd=args.kimi26_max_cost_usd, kimi26_max_output_tokens=args.kimi26_max_output_tokens, behavioral_scenario=args.behavioral_scenario)
            print(path)
            return 0
        if args.command == "plan":
            worlds = resolve_worlds(root, config, args.worlds)
            conditions = _parse_csv(args.conditions, list(config.conditions), "condition")
            rows = build_plan(root, config, run_id=args.run_id, worlds=worlds, conditions=conditions, repeats=args.repeats)
            plan_path = root / "runs" / args.run_id / "run_plan.jsonl"
            write_plan(plan_path, rows)
            print(plan_path)
            return 0
        if args.command == "init":
            for relative in ("data/worlds", "private/worlds", "runs", "reports", "docs", "src/mini_science", "tests"):
                (root / relative).mkdir(parents=True, exist_ok=True)
            print(root)
            return 0
        if args.command == "generate":
            result = generate_worlds(root, config)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate-worlds":
            result = validate_worlds(root, config)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "smoke":
            worlds = resolve_worlds(root, config, args.world)
            conditions = list(config.conditions)
            run_dir = run_pilot(root, config, provider=args.provider, worlds=worlds, conditions=conditions, repeats=1, allow_paid_api=args.allow_paid_api, run_dir=args.run_dir, kimi26_key_file=args.kimi26_key_file, kimi26_base_url=args.kimi26_base_url, kimi26_timeout=args.kimi26_timeout, kimi26_max_cost_usd=args.kimi26_max_cost_usd, kimi26_max_output_tokens=args.kimi26_max_output_tokens, behavioral_scenario=args.behavioral_scenario)
            print(run_dir)
            return 0
        if args.command == "pilot":
            worlds = resolve_worlds(root, config, args.worlds)
            conditions = _parse_csv(args.conditions, list(config.conditions), "condition")
            repeats = args.repeats if args.repeats is not None else config.repeats
            replicate_indices = None if args.replicate_indices is None else [int(value.strip()) for value in args.replicate_indices.split(",") if value.strip()]
            run_dir = run_pilot(root, config, provider=args.provider, worlds=worlds, conditions=conditions, repeats=repeats, replicate_indices=replicate_indices, request_namespace=args.request_namespace, allow_paid_api=args.allow_paid_api, run_dir=args.run_dir, retry_failed=args.retry_failed, kimi26_key_file=args.kimi26_key_file, kimi26_base_url=args.kimi26_base_url, kimi26_timeout=args.kimi26_timeout, kimi26_max_cost_usd=args.kimi26_max_cost_usd, kimi26_max_output_tokens=args.kimi26_max_output_tokens, behavioral_scenario=args.behavioral_scenario, global_max_calls=args.max_calls, global_max_cost_usd=args.max_estimated_cost_usd, v4_session_dir=args.v4_session_dir, session_dir=args.session_dir)
            print(run_dir)
            if args.provider in {"existing", "kimi26"}:
                manifest_path = Path(run_dir) / "manifest.json"
                if manifest_path.exists():
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    status = str(manifest.get("call_policy", {}).get("real_api_status", ""))
                    if status in {"FAILED", "UNKNOWN_BILLING_OUTCOME"}:
                        return 2
            return 0
        parser.error(f"unhandled command: {args.command}")
    except (OSError, ValueError, PermissionError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
