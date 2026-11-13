from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import random
from typing import Any

from .adapters.base import LLMResponse, ProviderAdapter
from .adapters.existing_project import ExistingProjectAdapter
from .adapters.kimi26 import Kimi26Adapter
from .adapters.mock import MockAdapter
from .analysis import read_results, write_report, write_results
from .budget import BudgetExceeded, BudgetTracker
from .config import ExperimentConfig
from .public_loader import load_world
from .schema import sha256_json
from .scoring import evaluate_final
from .societies import collab3, compete3, seq2, single


def _response_meta(response: LLMResponse | None) -> dict[str, Any]:
    if response is None:
        return {}
    return {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
        "cost_usd": response.cost_usd,
        "metadata": response.metadata,
    }


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class CallRecorder:
    def __init__(self, adapter: ProviderAdapter, tracker: BudgetTracker, events_path: Path, *, run_id: str, world_id: str, condition: str, replicate: int) -> None:
        self.adapter = adapter
        self.tracker = tracker
        self.events_path = events_path
        self.run_id = run_id
        self.world_id = world_id
        self.condition = condition
        self.replicate = replicate

    def _event(self, value: dict[str, Any]) -> None:
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")

    def __call__(self, agent_name: str, messages: list[dict[str, str]], max_output_tokens: int) -> LLMResponse:
        self.tracker.before_call()
        request_hash = sha256_json(messages)
        started = datetime.now(timezone.utc).isoformat()
        try:
            response = self.adapter.complete(messages, max_output_tokens)
            self.tracker.record(response)
            self._event({
                "run_id": self.run_id,
                "world_id": self.world_id,
                "condition": self.condition,
                "replicate": self.replicate,
                "agent_name": agent_name,
                "request_hash": request_hash,
                "response_hash": sha256_json(response.text),
                "request": messages,
                "response": response.text,
                "model_snapshot": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": response.latency_ms,
                "cost": response.cost_usd,
                "parse_status": "unparsed",
                "transfer_applied": None,
                "error_or_status": "completed",
                "started_at": started,
            })
            return response
        except Exception as exc:
            self._event({
                "run_id": self.run_id,
                "world_id": self.world_id,
                "condition": self.condition,
                "replicate": self.replicate,
                "agent_name": agent_name,
                "request_hash": request_hash,
                "response_hash": None,
                "request": messages,
                "response": None,
                "model_snapshot": getattr(self.adapter, "model_name", "unknown"),
                "input_tokens": None,
                "output_tokens": None,
                "latency_ms": None,
                "cost": None,
                "parse_status": "not_run",
                "transfer_applied": None,
                "error_or_status": f"{type(exc).__name__}:{str(exc)[:500]}",
                "started_at": started,
            })
            raise


def make_adapter(provider: str, allow_paid_api: bool, *, config: ExperimentConfig | None = None, key_file: str | Path | None = None, base_url: str | None = None, timeout: float | None = None, max_cost_usd: float | None = None, max_output_tokens: int = 1200) -> ProviderAdapter:
    if provider == "mock":
        return MockAdapter()
    if provider == "existing":
        return ExistingProjectAdapter(allow_paid_api=allow_paid_api)
    if provider == "kimi26":
        source_project = config.api_source_project if config and config.api_source_project else None
        return Kimi26Adapter(allow_paid_api=allow_paid_api, key_file=key_file, source_project=source_project, base_url=base_url, timeout=timeout, max_cost_usd=max_cost_usd, max_output_tokens=max_output_tokens)
    raise ValueError(f"unknown provider: {provider}")


def _condition_view(project_root: Path, world_id: str, condition: str):
    return load_world(project_root, world_id, source_variant="irrelevant" if condition == "A_TARGET_ONLY" else "related")


def _artifact_dir(run_dir: Path, world_id: str, condition: str) -> Path:
    path = run_dir / "agent_artifacts" / world_id / condition
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_response(path: Path, response: LLMResponse | None, extra: dict[str, Any] | None = None) -> None:
    value = {"raw_text": response.text if response else None, "response": _response_meta(response)}
    if extra:
        value.update(extra)
    _json_write(path, value)


def _numeric(response: LLMResponse | None, field: str) -> int:
    return int(getattr(response, field, 0) or 0) if response else 0


def _cost(response: LLMResponse | None) -> float:
    return float(response.cost_usd or 0.0) if response else 0.0


def _record_result(rows: list[dict[str, Any]], row: dict[str, Any], run_id: str) -> None:
    row["run_id"] = run_id
    rows.append(row)


def _key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (str(row.get("world_id")), str(row.get("condition")), str(row.get("replicate")), str(row.get("model_snapshot")))


def _load_cached_stage1(run_dir: Path, world_id: str, owner_condition: str) -> dict[str, Any] | None:
    path = run_dir / "agent_artifacts" / world_id / owner_condition / "stage1.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    meta = payload.get("response") or {}
    raw_text = payload.get("raw_text") or ""
    response = None
    if raw_text:
        response = LLMResponse(
            text=raw_text,
            model=str(meta.get("model", "unknown")),
            input_tokens=meta.get("input_tokens"),
            output_tokens=meta.get("output_tokens"),
            latency_ms=int(meta.get("latency_ms", 0) or 0),
            cost_usd=meta.get("cost_usd"),
            metadata=meta.get("metadata") or {},
        )
    return {
        "raw_text": raw_text,
        "parsed_artifact": payload.get("parsed_artifact") or {},
        "valid": bool(payload.get("valid", False)),
        "reason": str(payload.get("reason", "cached")),
        "response": response,
        "owner_condition": owner_condition,
    }


def run_pilot(
    project_root: str | Path,
    config: ExperimentConfig,
    *,
    provider: str,
    worlds: list[str],
    conditions: list[str],
    repeats: int,
    allow_paid_api: bool = False,
    run_dir: str | Path | None = None,
    retry_failed: bool = False,
    kimi26_key_file: str | Path | None = None,
    kimi26_base_url: str | None = None,
    kimi26_timeout: float | None = None,
    kimi26_max_cost_usd: float | None = None,
    kimi26_max_output_tokens: int = 1200,
) -> Path:
    project_root = Path(project_root).resolve()
    if provider in {"existing", "kimi26"} and not allow_paid_api:
        raise PermissionError(f"{provider} provider requires --allow-paid-api; no network request was attempted")
    adapter = make_adapter(provider, allow_paid_api, config=config, key_file=kimi26_key_file, base_url=kimi26_base_url, timeout=kimi26_timeout, max_cost_usd=kimi26_max_cost_usd, max_output_tokens=kimi26_max_output_tokens)
    if run_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir_path = project_root / "runs" / f"{provider}_{stamp}"
    else:
        run_dir_path = Path(run_dir).resolve()
    run_dir_path.mkdir(parents=True, exist_ok=True)
    events_path = run_dir_path / "events.jsonl"
    if not events_path.exists():
        events_path.touch()
    manifest_path = run_dir_path / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        run_id = manifest["run_id"]
    else:
        run_id = run_dir_path.name
        manifest = {
            "run_id": run_id,
            "experiment_id": config.experiment_id,
            "provider": provider,
            "model_snapshot": adapter.model_name,
            "worlds": worlds,
            "conditions": conditions,
            "repeats": repeats,
            "config": config.to_dict(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scientific_status": "ENGINEERING_PILOT_ONLY" if provider == "mock" else "REAL_PROVIDER_PILOT_NON_CONFIRMATORY",
        }
        _json_write(manifest_path, manifest)
        _json_write(run_dir_path / "config_frozen.json", config.to_dict())
    rows: list[dict[str, Any]] = [dict(row) for row in read_results(run_dir_path)]
    if retry_failed:
        # Successful rows are immutable; only explicitly requested retries can
        # replace a failed/invalid key.
        existing_keys = {_key(row) for row in rows if str(row.get("run_status")) == "COMPLETED" and str(row.get("valid")).lower() == "true"}
    else:
        # A resumed run must not silently spend again on a failed row. The
        # caller must opt into retry-failed, and the old failure remains in the
        # ledger until a new run is explicitly recorded.
        existing_keys = {_key(row) for row in rows}
    ordered_worlds = list(worlds)
    random.Random(config.seed).shuffle(ordered_worlds)
    ordered_conditions = [condition for condition in config.conditions if condition in conditions]

    for world_id in ordered_worlds:
        stage1_cache: dict[str, Any] | None = None
        if any(condition in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"} for condition in ordered_conditions):
            owner_condition = "C_SEQ2_TRANSFER" if "C_SEQ2_TRANSFER" in ordered_conditions else "D_SEQ2_BLOCK"
            stage1_needed = any(
                (world_id, condition, str(replicate), adapter.model_name) not in existing_keys
                for replicate in range(repeats)
                for condition in ("C_SEQ2_TRANSFER", "D_SEQ2_BLOCK")
                if condition in ordered_conditions
            )
            if stage1_needed:
                stage1_cache = _load_cached_stage1(run_dir_path, world_id, owner_condition)
            if stage1_needed and stage1_cache is None:
                view = load_world(project_root, world_id, "related")
                stage1_tracker = BudgetTracker(config.max_total_tokens_per_condition, config.max_agent_model_calls)
                stage1_call = CallRecorder(adapter, stage1_tracker, events_path, run_id=run_id, world_id=world_id, condition=owner_condition, replicate=0)
                try:
                    response, validation = seq2.extract_stage1(view, stage1_call)
                    artifact = validation.data or {}
                    stage1_cache = {
                        "raw_text": response.text,
                        "parsed_artifact": artifact,
                        "valid": validation.valid,
                        "reason": validation.reason,
                        "response": response,
                        "owner_condition": owner_condition,
                    }
                    _save_response(_artifact_dir(run_dir_path, world_id, owner_condition) / "stage1.json", response, {
                        "parsed_artifact": artifact,
                        "valid": validation.valid,
                        "reason": validation.reason,
                        "stage1_artifact_sha256": sha256_json(artifact),
                    })
                except Exception as exc:
                    stage1_cache = {"raw_text": "", "parsed_artifact": {}, "valid": False, "reason": f"{type(exc).__name__}:{str(exc)[:500]}", "response": None, "owner_condition": owner_condition}
                    _save_response(_artifact_dir(run_dir_path, world_id, owner_condition) / "stage1.json", None, {"parsed_artifact": {}, "valid": False, "reason": stage1_cache["reason"]})

        for replicate in range(repeats):
            # The cached stage-1 artifact is produced once per world and reused
            # for all replicates only in this low-cost paired implementation.
            for condition in ordered_conditions:
                model_snapshot = adapter.model_name
                candidate_key = (world_id, condition, str(replicate), model_snapshot)
                if candidate_key in existing_keys:
                    continue
                view = _condition_view(project_root, world_id, condition)
                try:
                    if condition in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}:
                        if stage1_cache is None or not stage1_cache.get("parsed_artifact"):
                            raise RuntimeError("stage1 artifact unavailable")
                        tracker = BudgetTracker(config.max_total_tokens_per_condition, config.max_agent_model_calls)
                        recorder = CallRecorder(adapter, tracker, events_path, run_id=run_id, world_id=world_id, condition=condition, replicate=replicate)
                        transfer = condition == "C_SEQ2_TRANSFER"
                        final_response, route = seq2.run_stage2(view, condition, stage1_cache["parsed_artifact"], transfer, recorder)
                        stage1_response = stage1_cache.get("response")
                        actual_response = final_response
                        input_tokens = _numeric(final_response, "input_tokens") + (_numeric(stage1_response, "input_tokens") if transfer else 0)
                        output_tokens = _numeric(final_response, "output_tokens") + (_numeric(stage1_response, "output_tokens") if transfer else 0)
                        actual_calls = 1 + (1 if transfer else 0)
                        stage1_cost = _cost(stage1_response)
                        actual_cost = _cost(final_response) + (stage1_cost if transfer else 0.0)
                        attributed_cost = _cost(final_response) + stage1_cost
                        stage1_info = {"parsed_artifact": stage1_cache["parsed_artifact"]}
                        _save_response(_artifact_dir(run_dir_path, world_id, condition) / "stage2.json", final_response, {"route": route, "stage1_artifact_sha256": route["stage1_artifact_sha256"], "forwarded_artifact_sha256": route["forwarded_artifact_sha256"]})
                        row = evaluate_final(project_root, world_id, view, final_response.text, condition=condition, provider=provider, model_snapshot=model_snapshot, replicate=replicate, input_tokens=input_tokens, output_tokens=output_tokens, api_calls=actual_calls, latency_ms=_numeric(final_response, "latency_ms") + (_numeric(stage1_response, "latency_ms") if transfer else 0), billed_cost=actual_cost, attributed_full_workflow_cost=attributed_cost, stage1=stage1_info, transfer_applied=transfer, stage1_artifact_sha256=route["stage1_artifact_sha256"], forwarded_artifact_sha256=route["forwarded_artifact_sha256"])
                    else:
                        tracker = BudgetTracker(config.max_total_tokens_per_condition, config.max_agent_model_calls)
                        recorder = CallRecorder(adapter, tracker, events_path, run_id=run_id, world_id=world_id, condition=condition, replicate=replicate)
                        if condition in {"A_TARGET_ONLY", "B_SINGLE_RELATED"}:
                            output = single.run(view, condition, recorder)
                        elif condition == "S_COLLAB3":
                            output = collab3.run(view, recorder)
                        elif condition == "S_COMPETE3":
                            output = compete3.run(view, recorder)
                        else:
                            raise ValueError(f"unsupported condition: {condition}")
                        final_response = output["final_response"]
                        assert isinstance(final_response, LLMResponse)
                        _save_response(_artifact_dir(run_dir_path, world_id, condition) / "final.json", final_response, {"condition": condition})
                        for name, value in output.items():
                            if name.endswith("_response") and isinstance(value, LLMResponse):
                                _save_response(_artifact_dir(run_dir_path, world_id, condition) / f"{name}.json", value, {"agent_name": name})
                        row = evaluate_final(project_root, world_id, view, final_response.text, condition=condition, provider=provider, model_snapshot=model_snapshot, replicate=replicate, input_tokens=tracker.total_input_tokens, output_tokens=tracker.total_output_tokens, api_calls=tracker.calls, latency_ms=tracker.latency_ms, billed_cost=tracker.cost_usd, attributed_full_workflow_cost=tracker.cost_usd, stage1=None)
                    row["experiment_id"] = config.experiment_id
                    _record_result(rows, row, run_id)
                except Exception as exc:
                    row = evaluate_final(project_root, world_id, view, "", condition=condition, provider=provider, model_snapshot=model_snapshot, replicate=replicate, input_tokens=0, output_tokens=0, api_calls=0, latency_ms=0, billed_cost=None, attributed_full_workflow_cost=None, run_status="FAILED", invalid_reason=f"{type(exc).__name__}:{str(exc)[:500]}", stage1={"parsed_artifact": (stage1_cache or {}).get("parsed_artifact", {})} if condition in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"} else None, transfer_applied=(condition == "C_SEQ2_TRANSFER") if condition in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"} else None)
                    row["experiment_id"] = config.experiment_id
                    _record_result(rows, row, run_id)
    write_results(run_dir_path, rows)
    write_report(run_dir_path)
    return run_dir_path
