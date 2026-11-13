from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .analysis import write_report
from .config import load_config, project_root_from_config
from .runner import make_adapter, run_pilot
from .worldgen import WORLD_SPECS, generate_worlds, validate_worlds


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
    smoke.add_argument("--provider", choices=["mock", "existing", "kimi26"], default="mock")
    smoke.add_argument("--world", default="W001")
    smoke.add_argument("--allow-paid-api", action="store_true")
    smoke.add_argument("--run-dir")
    smoke.add_argument("--kimi26-key-file")
    smoke.add_argument("--kimi26-base-url")
    smoke.add_argument("--kimi26-timeout", type=float)
    smoke.add_argument("--kimi26-max-cost-usd", type=float)
    smoke.add_argument("--kimi26-max-output-tokens", type=int, default=1200)

    pilot = sub.add_parser("pilot")
    pilot.add_argument("--config", default="config/pilot.json")
    pilot.add_argument("--provider", choices=["mock", "existing", "kimi26"], default="mock")
    pilot.add_argument("--worlds", default="all")
    pilot.add_argument("--conditions", default="all")
    pilot.add_argument("--repeats", type=int, default=None)
    pilot.add_argument("--allow-paid-api", action="store_true")
    pilot.add_argument("--run-dir")
    pilot.add_argument("--retry-failed", action="store_true")
    pilot.add_argument("--kimi26-key-file")
    pilot.add_argument("--kimi26-base-url")
    pilot.add_argument("--kimi26-timeout", type=float)
    pilot.add_argument("--kimi26-max-cost-usd", type=float)
    pilot.add_argument("--kimi26-max-output-tokens", type=int, default=1200)

    report = sub.add_parser("report")
    report.add_argument("--run-dir", required=True)

    check = sub.add_parser("check-api")
    check.add_argument("--provider", choices=["existing", "kimi26"], default="existing")
    check.add_argument("--allow-paid-api", action="store_true")
    check.add_argument("--max-calls", type=int, default=1)
    check.add_argument("--kimi26-key-file")
    check.add_argument("--kimi26-base-url")
    check.add_argument("--kimi26-timeout", type=float)
    check.add_argument("--kimi26-max-cost-usd", type=float)
    check.add_argument("--kimi26-max-output-tokens", type=int, default=8)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            path = write_report(args.run_dir)
            print(path)
            return 0
        if args.command == "check-api":
            if not args.allow_paid_api:
                raise PermissionError("check-api is blocked without --allow-paid-api; no network request was attempted")
            if args.max_calls < 1:
                raise ValueError("--max-calls must be at least 1")
            adapter = make_adapter(args.provider, True, key_file=args.kimi26_key_file, base_url=args.kimi26_base_url, timeout=args.kimi26_timeout, max_cost_usd=args.kimi26_max_cost_usd, max_output_tokens=args.kimi26_max_output_tokens)
            response = adapter.complete([{"role": "user", "content": "Reply with exactly {\"status\":\"ok\"}."}], args.kimi26_max_output_tokens)
            print(json.dumps({"status": "ok", "model": response.model, "input_tokens": response.input_tokens, "output_tokens": response.output_tokens, "cost_usd": response.cost_usd}, ensure_ascii=False))
            return 0

        config = load_config(args.config)
        root = project_root_from_config(args.config)
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
        allowed_worlds = [spec[0] for spec in WORLD_SPECS[: config.num_worlds]]
        if args.command == "smoke":
            worlds = _parse_csv(args.world, allowed_worlds, "world")
            conditions = list(config.conditions)
            run_dir = run_pilot(root, config, provider=args.provider, worlds=worlds, conditions=conditions, repeats=1, allow_paid_api=args.allow_paid_api, run_dir=args.run_dir, kimi26_key_file=args.kimi26_key_file, kimi26_base_url=args.kimi26_base_url, kimi26_timeout=args.kimi26_timeout, kimi26_max_cost_usd=args.kimi26_max_cost_usd, kimi26_max_output_tokens=args.kimi26_max_output_tokens)
            print(run_dir)
            return 0
        if args.command == "pilot":
            worlds = _parse_csv(args.worlds, allowed_worlds, "world")
            conditions = _parse_csv(args.conditions, list(config.conditions), "condition")
            repeats = args.repeats if args.repeats is not None else config.repeats
            run_dir = run_pilot(root, config, provider=args.provider, worlds=worlds, conditions=conditions, repeats=repeats, allow_paid_api=args.allow_paid_api, run_dir=args.run_dir, retry_failed=args.retry_failed, kimi26_key_file=args.kimi26_key_file, kimi26_base_url=args.kimi26_base_url, kimi26_timeout=args.kimi26_timeout, kimi26_max_cost_usd=args.kimi26_max_cost_usd, kimi26_max_output_tokens=args.kimi26_max_output_tokens)
            print(run_dir)
            return 0
        parser.error(f"unhandled command: {args.command}")
    except (OSError, ValueError, PermissionError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
