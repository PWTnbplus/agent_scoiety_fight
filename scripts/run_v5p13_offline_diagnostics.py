from __future__ import annotations

"""Read-only V5-P13 sensitivity and transport diagnostics.

This script uses public files for the public value-of-information calculation
and private truth only for a separately labelled retrospective oracle column.
It never constructs a provider prompt from private data and never makes HTTP
requests.
"""

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import ssl
import statistics
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "018_V5P13_SCIENCE_DIAG_AND_FINAL"
CONFIG_PATH = ROOT / "config" / "v5p11_main.json"
BASE_ANALYSIS = ROOT / "reports" / "017_V5P12_REMAINDER_LIVE" / "analysis"
BASE_RUNS = [path for path in (ROOT / "runs").glob("real_v5p12_*")]


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def numbers(text: str, pattern: str) -> list[float]:
    return [float(value) for value in re.findall(pattern, text)]


def public_values(text: str, prefix: str) -> tuple[float, list[tuple[float, float]]]:
    k = float(re.search(rf"{prefix}.*?candidate-rate k=([0-9.]+)", text, re.I | re.S).group(1))
    if prefix == "Target ":
        matches = re.findall(r"target_state=([0-9.]+), target_time=([0-9.]+) s, target_x0=([0-9.]+)", text)
    else:
        matches = re.findall(r"source_state=([0-9.]+), source_time=([0-9.]+) s, source_x0=([0-9.]+)", text)
    return k, [(float(state), float(time), float(x0)) for state, time, x0 in matches]


def predict(model: str, x0: float, t: float, k: float) -> float:
    import math
    if model == "EXP_DECAY":
        return x0 * math.exp(-k * t)
    if model == "HYPERBOLIC_DECAY":
        return x0 / (1.0 + k * x0 * t)
    if model == "STRETCHED_EXP":
        return x0 * math.exp(-(k * t) ** 2)
    if model == "BI_EXP":
        return x0 * (0.75 * math.exp(-1.8 * k * t) + 0.25 * math.exp(-0.25 * k * t))
    raise ValueError(model)


def ranks(scores: dict[str, float]) -> dict[str, int]:
    ordered = sorted(scores, key=lambda key: (-scores[key], key))
    return {key: index + 1 for index, key in enumerate(ordered)}


def sensitivity() -> list[dict[str, Any]]:
    from mini_science.config import load_config
    from mini_science.analysis import write_oracle_audit

    config = load_config(CONFIG_PATH)
    oracle_path = REPORT / "PRIVATE_ORACLE_RETROSPECTIVE.csv"
    write_oracle_audit(ROOT, config, oracle_path)
    oracle = read_csv(oracle_path)
    results = read_csv(BASE_ANALYSIS / "results_raw.csv")
    rows: list[dict[str, Any]] = []
    for world_id in config.allowed_worlds:
        world_dir = ROOT / "data" / config.worlds_subdir / world_id
        target_text = (world_dir / "target_notes.md").read_text(encoding="utf-8")
        source_text = (world_dir / "source_related.md").read_text(encoding="utf-8")
        target_k, target_obs = public_values(target_text, "Target ")
        source_k, source_obs = public_values(source_text, "Source ")
        source_errors = {
            model: statistics.mean([(predict(model, x0, t, source_k) - state) ** 2 for state, t, x0 in source_obs])
            for model in config.candidate_models
        }
        source_model = min(source_errors, key=lambda model: (source_errors[model], model))
        menu = json.loads((world_dir / "candidate_experiments.json").read_text(encoding="utf-8"))["experiments"]
        without_scores = {
            str(item["experiment_id"]): max(predict(model, float(item["x0"]), float(item["measure_t"]), target_k) for model in config.candidate_models)
            - min(predict(model, float(item["x0"]), float(item["measure_t"]), target_k) for model in config.candidate_models)
            for item in menu
        }
        with_scores = {
            str(item["experiment_id"]): max(abs(predict(source_model, float(item["x0"]), float(item["measure_t"]), target_k) - predict(model, float(item["x0"]), float(item["measure_t"]), target_k)) for model in config.candidate_models if model != source_model)
            for item in menu
        }
        without_id = max(without_scores, key=lambda key: (without_scores[key], key))
        with_id = max(with_scores, key=lambda key: (with_scores[key], key))
        oracle_rows = [row for row in oracle if row["world_id"] == world_id]
        oracle_best = max(oracle_rows, key=lambda row: float(row["ig_nats"]))
        c_rows = [row for row in results if row["world_id"] == world_id and row["condition"] == "C_SEQ2_TRANSFER" and row["run_status"] == "COMPLETED"]
        cd_rows = []
        diagnoses: list[str] = []
        for c in c_rows:
            d = next((row for row in results if row["world_id"] == world_id and row["replicate"] == c["replicate"] and row["condition"] == "D_SEQ2_BLOCK"), None)
            if d and d["run_status"] == "COMPLETED":
                cd_rows.append((c, d))
                if c.get("stage1_artifact_sha256") != d.get("stage1_artifact_sha256") or d.get("route_intervention") != "blocked":
                    diagnoses.append("ROUTE_BUG")
                if c.get("stage1_law_identification_correct") != "True":
                    diagnoses.append("LAW_IDENTIFICATION_FAILURE")
                elif c.get("experiment_id_selected") == d.get("experiment_id_selected"):
                    diagnoses.append("NO_STAGE2_UPTAKE")
        if c_rows and any(row.get("stage1_law_identification_correct") != "True" for row in c_rows):
            diagnoses.append("LAW_IDENTIFICATION_FAILURE")
        if without_id == with_id or ranks(without_scores).get("E08") == ranks(with_scores).get("E08"):
            diagnoses.append("ACTION_OBJECTIVE_INSENSITIVE")
        if not diagnoses:
            diagnoses.append("UNRESOLVED")
        rows.append({
            "world_id": world_id,
            "public_source_best_model": source_model,
            "public_source_fit_mse": source_errors[source_model],
            "public_only_best_action": without_id,
            "public_law_conditioned_best_action": with_id,
            "public_action_changed": without_id != with_id,
            "public_only_e08_rank": ranks(without_scores)["E08"],
            "public_law_conditioned_e08_rank": ranks(with_scores)["E08"],
            "public_only_best_score": without_scores[without_id],
            "public_law_conditioned_best_score": with_scores[with_id],
            "public_score_difference_at_selected_actions": with_scores[with_id] - without_scores[without_id],
            "private_oracle_best_action": oracle_best["experiment_id"],
            "private_oracle_best_ig_nats": oracle_best["ig_nats"],
            "full_cd_pairs_in_current_data": len(cd_rows),
            "diagnosis": ";".join(dict.fromkeys(diagnoses)),
            "public_analysis_note": "source fit and target candidate spread use public files only; no private truth was used for these columns",
            "private_retrospective_note": "oracle columns are scoring-side retrospective diagnostics and were not sent to any provider",
        })
    return rows


def network_audit() -> dict[str, Any]:
    host = "token.ctflow.cn"
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            tls_info = {"tcp_443": True, "tls_version": tls.version(), "cipher": tls.cipher()[0]}
    proxy_names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    message_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for run in BASE_RUNS:
        events = run / "events.jsonl"
        calls = run / "call_ledger.jsonl"
        if events.exists():
            for line in events.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                event = json.loads(line)
                if event.get("event_type") == "STAGE2_REQUEST" and event.get("condition") == "B_SINGLE_RELATED" and event.get("world_id") == "IV002":
                    messages = event.get("request", [])
                    payload = json.dumps(messages, ensure_ascii=False, sort_keys=True)
                    message_rows.append({"run_id": run.name, "request_id": event.get("request_id"), "world_id": event.get("world_id"), "condition": event.get("condition"), "message_count": len(messages), "char_count": len(payload), "utf8_bytes": len(payload.encode("utf-8")), "token_approx": max(1, len(payload.split()), (len(payload) + 1) // 2), "prompt_hash": event.get("request_hash"), "system_message_sha256": sha(messages[0]) if messages else None, "user_message_sha256": sha(messages[-1]) if messages else None, "max_output_tokens": event.get("max_output_tokens")})
        if calls.exists():
            for line in calls.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                row = json.loads(line)
                if str(row.get("failure_kind", "")) or str(row.get("request_status", "")).startswith("failed"):
                    failures.append({"run_id": run.name, "request_id": row.get("request_id"), "failure_kind": row.get("failure_kind"), "reason_type": row.get("reason_type"), "detail_code": row.get("detail_code"), "latency_ms": row.get("latency_ms"), "error_text_present_in_source_ledger": bool(row.get("error"))})
    return {
        "host": host,
        "addresses": addresses,
        **tls_info,
        "credentials_sent": False,
        "http_probe": False,
        "proxy_environment_present": {name: bool(os.getenv(name)) for name in proxy_names},
        "transport_failures": failures,
        "iv002_b_message_shape_audit": message_rows,
        "interpretation": "DNS/TCP/TLS reachability succeeded without credentials; RemoteDisconnected remains an unresolved provider-side or post-connect transport outcome, not evidence of prompt causality.",
    }


def main() -> int:
    write_csv(REPORT / "08_LAW_INFORMATION_SENSITIVITY_AUDIT.csv", sensitivity())
    (REPORT / "09_NETWORK_SAFETY_AUDIT.json").write_text(json.dumps(network_audit(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"sensitivity": str(REPORT / "08_LAW_INFORMATION_SENSITIVITY_AUDIT.csv"), "network": str(REPORT / "09_NETWORK_SAFETY_AUDIT.json")}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
