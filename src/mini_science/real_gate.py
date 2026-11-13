from __future__ import annotations

"""Persistent, fail-closed authorization and spend gate for real providers."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from .authorization import config_digest, load_authorization


class GateDenied(PermissionError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GateReservation:
    request_id: str
    estimated_cost_usd: float
    attempt_number: int


class _FileMutex:
    """Cross-process create-exclusive lock for the small JSON gate state."""

    def __init__(self, path: Path, timeout_seconds: float = 5.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.handle: int | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self.handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.handle, f"pid={os.getpid()}\n".encode("ascii"))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 60:
                        self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise GateDenied(f"persistent gate lock busy: {self.path}")
                time.sleep(0.01)

    def __exit__(self, *_args):
        if self.handle is not None:
            os.close(self.handle)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class PersistentRealGate:
    """A JSON ledger shared by check/probe/pilot processes."""

    def __init__(
        self,
        project_root: str | Path,
        config: Any,
        *,
        state_path: str | Path | None = None,
        run_max_calls: int | None = None,
        run_max_cost_usd: float | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.config = config
        self.state_path = Path(state_path) if state_path else self.project_root / "runs" / "v3_real_gate_state.json"
        self.lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        self.run_max_calls = run_max_calls
        self.run_max_cost_usd = run_max_cost_usd
        self._run_reserved_calls = 0
        self._run_reserved_cost_usd = 0.0

    def _authorization(self) -> dict[str, Any] | None:
        return load_authorization(self.project_root)

    def _default_state(self) -> dict[str, Any]:
        authorization = self._authorization()
        return {
            "schema_version": 2,
            "created_at": utc_now(),
            "authorization_status": "AUTHORIZED" if authorization else self.config.authorization_status,
            "authorization_id": authorization.get("authorization_id") if authorization else None,
            "config_hash": config_digest(self.config),
            "authorized_provider": authorization.get("provider") if authorization else self.config.authorized_provider,
            "authorized_model": authorization.get("model") if authorization else self.config.authorized_model,
            "max_unique_calls": authorization.get("max_unique_provider_attempts", 0) if authorization else self.config.max_unique_calls,
            "max_estimated_cost_usd": authorization.get("max_estimated_cost_usd") if authorization else self.config.max_estimated_cost_usd,
            "calls_used": 0,
            "estimated_cost_used_usd": 0.0,
            "attempts": [],
        }

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateDenied(f"invalid persistent gate state: {self.state_path}") from exc
        for key in ("calls_used", "estimated_cost_used_usd", "attempts", "authorization_status"):
            if key not in state:
                raise GateDenied(f"invalid persistent gate state: missing {key}")
        authorization = self._authorization()
        if authorization:
            if state.get("authorization_id") != authorization.get("authorization_id"):
                raise GateDenied("persistent gate state belongs to a different authorization; refusing reset")
            if state.get("config_hash") != config_digest(self.config):
                raise GateDenied("configuration changed after authorization; create a new authorization")
            if state.get("max_unique_calls") != authorization.get("max_unique_provider_attempts") or float(state.get("max_estimated_cost_usd") or 0.0) != float(authorization.get("max_estimated_cost_usd") or 0.0):
                raise GateDenied("persistent gate caps do not match authorization manifest")
        return state

    def load(self) -> dict[str, Any]:
        with _FileMutex(self.lock_path):
            return self._load_unlocked()

    def _save_unlocked(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.state_path)

    def save(self, state: dict[str, Any]) -> None:
        with _FileMutex(self.lock_path):
            self._save_unlocked(state)

    def _effective_limits(self, state: dict[str, Any]) -> tuple[int, float | None]:
        max_calls = int(state.get("max_unique_calls", 0))
        max_cost = state.get("max_estimated_cost_usd")
        return max_calls, max_cost

    def _check_run_limits(self, planned_calls: int, planned_cost_usd: float) -> None:
        if self.run_max_calls is not None and self._run_reserved_calls + planned_calls > max(0, int(self.run_max_calls)):
            raise GateDenied("planned provider attempts exceed this stage run cap")
        if self.run_max_cost_usd is not None and self._run_reserved_cost_usd + float(planned_cost_usd) > max(0.0, float(self.run_max_cost_usd)) + 1e-12:
            raise GateDenied("planned provider estimate exceeds this stage run cost cap")

    def _assert_authorized_unlocked(
        self,
        state: dict[str, Any],
        *,
        provider: str,
        model: str,
        allow_paid_api: bool,
        stage: str,
        worlds: list[str] | None = None,
        conditions: list[str] | None = None,
    ) -> dict[str, Any]:
        if not allow_paid_api:
            raise GateDenied("real provider requires --allow-paid-api")
        authorization = self._authorization()
        if authorization is None or authorization.get("authorization_status") != "AUTHORIZED":
            raise GateDenied("no explicit user authorization manifest")
        if authorization.get("provider") != provider or authorization.get("model") != model:
            raise GateDenied("provider/model outside explicit authorization")
        if stage not in set(authorization.get("scope", [])):
            raise GateDenied(f"stage outside authorization scope: {stage}")
        if authorization.get("current_stage") not in {stage, "ALL"}:
            raise GateDenied(f"stage is not the currently approved stage: {stage}")
        allowed_worlds = set(authorization.get("worlds", []))
        allowed_conditions = set(authorization.get("conditions", []))
        if worlds and not set(worlds).issubset(allowed_worlds):
            raise GateDenied("world outside explicit authorization scope")
        if conditions and not set(conditions).issubset(allowed_conditions):
            raise GateDenied("condition outside explicit authorization scope")
        if state.get("authorization_status") != "AUTHORIZED":
            raise GateDenied("persistent gate state is not AUTHORIZED")
        return state

    def assert_authorized(self, *, provider: str, model: str, allow_paid_api: bool, stage: str, worlds: list[str] | None = None, conditions: list[str] | None = None) -> dict[str, Any]:
        with _FileMutex(self.lock_path):
            state = self._load_unlocked()
            return self._assert_authorized_unlocked(state, provider=provider, model=model, allow_paid_api=allow_paid_api, stage=stage, worlds=worlds, conditions=conditions)

    def preflight(
        self,
        *,
        provider: str,
        model: str,
        allow_paid_api: bool,
        stage: str,
        planned_calls: int | None = None,
        planned_cost_usd: float | None = None,
        request_plan: list[dict[str, Any]] | None = None,
        worlds: list[str] | None = None,
        conditions: list[str] | None = None,
    ) -> dict[str, Any]:
        if request_plan is not None:
            request_ids = [str(item.get("request_id", "")) for item in request_plan]
            if any(not item for item in request_ids) or len(set(request_ids)) != len(request_ids):
                raise GateDenied("preflight request plan contains missing or duplicate request_id")
            planned_calls = len(request_plan)
            planned_cost_usd = sum(float(item.get("estimated_cost_usd", 0.0)) for item in request_plan)
        if planned_calls is None or planned_cost_usd is None:
            raise ValueError("preflight requires planned_calls/planned_cost_usd or request_plan")
        if planned_calls <= 0 or planned_cost_usd < 0:
            raise ValueError("preflight plan must have positive calls and nonnegative cost")
        with _FileMutex(self.lock_path):
            state = self._load_unlocked()
            self._assert_authorized_unlocked(state, provider=provider, model=model, allow_paid_api=allow_paid_api, stage=stage, worlds=worlds, conditions=conditions)
            self._check_run_limits(int(planned_calls), float(planned_cost_usd))
            max_calls, max_cost = self._effective_limits(state)
            if max_calls <= 0 or max_cost is None or max_cost <= 0:
                raise GateDenied("authorization has no positive call and cost cap")
            if int(state["calls_used"]) + int(planned_calls) > max_calls:
                raise GateDenied("planned provider attempts exceed persistent call cap")
            if float(state["estimated_cost_used_usd"]) + float(planned_cost_usd) > float(max_cost) + 1e-12:
                raise GateDenied("planned provider estimate exceeds persistent cost cap")
            authorized_calls = int(state.get("max_unique_calls", 0))
            authorized_cost = state.get("max_estimated_cost_usd")
            return {
                "planned_calls": planned_calls,
                "planned_cost_usd": planned_cost_usd,
                "calls_remaining": max_calls - int(state["calls_used"]) - planned_calls,
                "estimated_cost_remaining": float(max_cost) - float(state["estimated_cost_used_usd"]) - float(planned_cost_usd),
                "global_calls_remaining": authorized_calls - int(state["calls_used"]) - planned_calls,
                "global_estimated_cost_remaining": None if authorized_cost is None else float(authorized_cost) - float(state["estimated_cost_used_usd"]) - float(planned_cost_usd),
                "max_calls_for_run": self.run_max_calls if self.run_max_calls is not None else max_calls,
                "max_cost_for_run": self.run_max_cost_usd if self.run_max_cost_usd is not None else max_cost,
                "request_plan": request_plan or [],
            }

    def reserve(self, *, request_id: str, provider: str, model: str, stage: str, estimated_cost_usd: float, world_id: str | None = None, condition: str | None = None) -> GateReservation:
        with _FileMutex(self.lock_path):
            state = self._load_unlocked()
            self._assert_authorized_unlocked(state, provider=provider, model=model, allow_paid_api=True, stage=stage, worlds=[world_id] if world_id else None, conditions=[condition] if condition and condition != "PROBE" else None)
            self._check_run_limits(1, float(estimated_cost_usd))
            max_calls, max_cost = self._effective_limits(state)
            if any(str(item.get("request_id")) == request_id for item in state["attempts"]):
                raise GateDenied(f"request_id already attempted: {request_id}")
            if int(state["calls_used"]) + 1 > max_calls:
                raise GateDenied("provider attempt cap exceeded before request")
            if max_cost is None or float(state["estimated_cost_used_usd"]) + float(estimated_cost_usd) > float(max_cost) + 1e-12:
                raise GateDenied("provider cost cap exceeded before request")
            attempt_number = len(state["attempts"]) + 1
            state["calls_used"] = int(state["calls_used"]) + 1
            state["estimated_cost_used_usd"] = float(state["estimated_cost_used_usd"]) + float(estimated_cost_usd)
            state["attempts"].append({"request_id": request_id, "attempt_number": attempt_number, "provider": provider, "model": model, "stage": stage, "world_id": world_id, "condition": condition, "estimated_cost_usd": estimated_cost_usd, "status": "STARTED", "started_at": utc_now(), "actual_cost_usd": None, "billing_verified": False})
            self._save_unlocked(state)
            self._run_reserved_calls += 1
            self._run_reserved_cost_usd += float(estimated_cost_usd)
            return GateReservation(request_id, float(estimated_cost_usd), attempt_number)

    def finish(self, reservation: GateReservation, *, status: str, actual_cost_usd: float | None = None, billing_verified: bool = False, returned_model: str | None = None, error: str | None = None) -> None:
        if status not in {"COMPLETED", "FAILED"}:
            raise ValueError("gate finish status must be COMPLETED or FAILED")
        with _FileMutex(self.lock_path):
            state = self._load_unlocked()
            for item in state["attempts"]:
                if item.get("request_id") == reservation.request_id:
                    item.update({"status": status, "finished_at": utc_now(), "actual_cost_usd": actual_cost_usd, "billing_verified": billing_verified, "returned_model": returned_model, "error": error})
                    self._save_unlocked(state)
                    return
            raise GateDenied(f"reservation not found: {reservation.request_id}")

    def summary(self) -> dict[str, Any]:
        state = self.load()
        authorized_max_calls = int(state.get("max_unique_calls", 0))
        authorized_max_cost = state.get("max_estimated_cost_usd")
        max_calls, max_cost = self._effective_limits(state)
        statuses = [str(item.get("status", "UNKNOWN")) for item in state["attempts"]]
        if "FAILED" in statuses:
            real_status = "FAILED"
        elif "STARTED" in statuses:
            real_status = "STARTED"
        elif "COMPLETED" in statuses:
            real_status = "COMPLETED"
        else:
            real_status = "AUTHORIZED"
        return {
            "calls_used": int(state["calls_used"]),
            "max_unique_calls": authorized_max_calls,
            "global_calls_remaining": authorized_max_calls - int(state["calls_used"]),
            "run_max_unique_calls": self.run_max_calls if self.run_max_calls is not None else max_calls,
            "run_calls_remaining": (self.run_max_calls - self._run_reserved_calls) if self.run_max_calls is not None else max_calls - int(state["calls_used"]),
            "estimated_cost_used_usd": float(state["estimated_cost_used_usd"]),
            "max_estimated_cost_usd": authorized_max_cost,
            "global_budget_remaining": None if authorized_max_cost is None else float(authorized_max_cost) - float(state["estimated_cost_used_usd"]),
            "run_max_estimated_cost_usd": self.run_max_cost_usd if self.run_max_cost_usd is not None else max_cost,
            "run_budget_remaining": (float(self.run_max_cost_usd) - self._run_reserved_cost_usd) if self.run_max_cost_usd is not None else (None if max_cost is None else float(max_cost) - float(state["estimated_cost_used_usd"])),
            "attempts": len(state["attempts"]),
            "completed_attempts": statuses.count("COMPLETED"),
            "failed_attempts": statuses.count("FAILED"),
            "started_attempts": statuses.count("STARTED"),
            "real_api_status": real_status,
            "authorization_id": state.get("authorization_id"),
        }


class V4SessionGate:
    """Independent V4 session ledger; it never reads or mutates V3 gate state."""

    def __init__(self, project_root: str | Path, session_dir: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.session_dir = Path(session_dir).resolve()
        self.authorization_path = self.session_dir / "authorization.json"
        self.state_path = self.session_dir / "gate_state.json"
        self.attempts_path = self.session_dir / "attempts.jsonl"
        self.lock_path = self.session_dir / "gate_state.json.lock"

    def _authorization(self) -> dict[str, Any]:
        if not self.authorization_path.exists():
            raise GateDenied("V4 session authorization is absent")
        try:
            value = json.loads(self.authorization_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateDenied("invalid V4 session authorization") from exc
        if value.get("authorization_status") != "AUTHORIZED":
            raise GateDenied("V4 session is not AUTHORIZED")
        return value

    def _default_state(self, authorization: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "authorization_id": authorization.get("authorization_id"),
            "calls_used": 0,
            "estimated_cost_used_usd": 0.0,
            "attempts": [],
        }

    def _load_unlocked(self) -> dict[str, Any]:
        authorization = self._authorization()
        if not self.state_path.exists():
            return self._default_state(authorization)
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateDenied("invalid V4 session gate state") from exc
        if state.get("authorization_id") != authorization.get("authorization_id"):
            raise GateDenied("V4 state belongs to a different authorization")
        return state

    def _save_unlocked(self, state: dict[str, Any]) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.state_path)

    def _append_attempt(self, item: dict[str, Any]) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        with self.attempts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    def assert_authorized(self, *, provider: str, model: str, worlds: list[str], conditions: list[str]) -> dict[str, Any]:
        authorization = self._authorization()
        if provider != authorization.get("provider") or model != authorization.get("model"):
            raise GateDenied("V4 provider/model mismatch")
        if not set(worlds).issubset(set(authorization.get("worlds", []))) or not set(conditions).issubset(set(authorization.get("conditions", []))):
            raise GateDenied("V4 scope mismatch")
        return authorization

    def preflight(self, *, provider: str, model: str, request_plan: list[dict[str, Any]], worlds: list[str], conditions: list[str]) -> dict[str, Any]:
        if not request_plan or len({str(item.get("request_id", "")) for item in request_plan}) != len(request_plan) or any(not item.get("request_id") for item in request_plan):
            raise GateDenied("V4 request plan contains missing or duplicate request_id")
        with _FileMutex(self.lock_path):
            authorization = self._authorization()
            if provider != authorization.get("provider") or model != authorization.get("model"):
                raise GateDenied("V4 provider/model mismatch")
            if not set(worlds).issubset(set(authorization.get("worlds", []))) or not set(conditions).issubset(set(authorization.get("conditions", []))):
                raise GateDenied("V4 scope mismatch")
            state = self._load_unlocked()
            attempted = {str(item.get("request_id")) for item in state.get("attempts", [])}
            pending = [item for item in request_plan if str(item["request_id"]) not in attempted]
            planned_cost = sum(float(item.get("estimated_cost_usd", 0.0)) for item in pending)
            max_calls = int(authorization.get("max_unique_provider_attempts", 0))
            max_cost = float(authorization.get("max_estimated_cost_usd", 0.0))
            if int(state.get("calls_used", 0)) + len(pending) > max_calls:
                raise GateDenied("V4 plan exceeds session call cap")
            if float(state.get("estimated_cost_used_usd", 0.0)) + planned_cost > max_cost + 1e-12:
                raise GateDenied("V4 plan exceeds session cost cap")
            return {"planned_calls": len(pending), "planned_cost_usd": planned_cost, "skipped_request_ids": sorted(attempted.intersection({str(item["request_id"]) for item in request_plan})), "request_plan": pending, "calls_remaining": max_calls - int(state.get("calls_used", 0)) - len(pending), "cost_remaining": max_cost - float(state.get("estimated_cost_used_usd", 0.0)) - planned_cost}

    def reserve(self, *, request_id: str, provider: str, model: str, stage: str, estimated_cost_usd: float, world_id: str, condition: str) -> GateReservation:
        with _FileMutex(self.lock_path):
            authorization = self._authorization()
            if provider != authorization.get("provider") or model != authorization.get("model"):
                raise GateDenied("V4 provider/model mismatch")
            if stage not in set(authorization.get("scope", [])):
                raise GateDenied("V4 stage outside authorization scope")
            if world_id not in set(authorization.get("worlds", [])) or condition not in set(authorization.get("conditions", [])):
                raise GateDenied("V4 world or condition outside authorization scope")
            state = self._load_unlocked()
            if any(str(item.get("request_id")) == request_id for item in state.get("attempts", [])):
                raise GateDenied(f"V4 request_id already attempted: {request_id}")
            if int(state.get("calls_used", 0)) + 1 > int(authorization.get("max_unique_provider_attempts", 0)):
                raise GateDenied("V4 call cap exceeded")
            if float(state.get("estimated_cost_used_usd", 0.0)) + float(estimated_cost_usd) > float(authorization.get("max_estimated_cost_usd", 0.0)) + 1e-12:
                raise GateDenied("V4 cost cap exceeded")
            attempt_number = int(state.get("calls_used", 0)) + 1
            item = {"request_id": request_id, "attempt_number": attempt_number, "provider": provider, "model": model, "stage": stage, "world_id": world_id, "condition": condition, "estimated_cost_usd": float(estimated_cost_usd), "status": "STARTED", "started_at": utc_now(), "actual_cost_usd": None, "billing_verified": False}
            state.setdefault("attempts", []).append(item)
            state["calls_used"] = attempt_number
            state["estimated_cost_used_usd"] = float(state.get("estimated_cost_used_usd", 0.0)) + float(estimated_cost_usd)
            self._save_unlocked(state)
            self._append_attempt(item)
            return GateReservation(request_id, float(estimated_cost_usd), attempt_number)

    def finish(self, reservation: GateReservation, *, status: str, actual_cost_usd: float | None = None, billing_verified: bool = False, returned_model: str | None = None, error: str | None = None) -> None:
        if status not in {"COMPLETED", "FAILED"}:
            raise ValueError("V4 gate status must be COMPLETED or FAILED")
        with _FileMutex(self.lock_path):
            state = self._load_unlocked()
            for item in state.get("attempts", []):
                if item.get("request_id") == reservation.request_id:
                    item.update({"status": status, "finished_at": utc_now(), "actual_cost_usd": actual_cost_usd, "billing_verified": billing_verified, "returned_model": returned_model, "error": error})
                    self._save_unlocked(state)
                    self._append_attempt(item)
                    return
            raise GateDenied("V4 reservation not found")

    def summary(self) -> dict[str, Any]:
        with _FileMutex(self.lock_path):
            authorization = self._authorization()
            state = self._load_unlocked()
            statuses = [str(item.get("status")) for item in state.get("attempts", [])]
            return {"authorization_id": authorization.get("authorization_id"), "authorization_status": authorization.get("authorization_status"), "calls_used": int(state.get("calls_used", 0)), "max_unique_calls": int(authorization.get("max_unique_provider_attempts", 0)), "calls_remaining": int(authorization.get("max_unique_provider_attempts", 0)) - int(state.get("calls_used", 0)), "estimated_cost_used_usd": float(state.get("estimated_cost_used_usd", 0.0)), "max_estimated_cost_usd": float(authorization.get("max_estimated_cost_usd", 0.0)), "cost_remaining": float(authorization.get("max_estimated_cost_usd", 0.0)) - float(state.get("estimated_cost_used_usd", 0.0)), "completed_attempts": statuses.count("COMPLETED"), "failed_attempts": statuses.count("FAILED"), "started_attempts": statuses.count("STARTED"), "real_api_status": "FAILED" if "FAILED" in statuses else ("STARTED" if "STARTED" in statuses else ("COMPLETED" if "COMPLETED" in statuses else "AUTHORIZED"))}


class V5P4SessionGate:
    """Independent V5-P4 session gate with frozen-plan and replay checks.

    It intentionally uses different files from both the legacy V3 gate and
    the V4 session implementation.  The gate is fail-closed and reserves a
    request before transport, so a failed or uncertain attempt consumes one
    unique request and cannot be silently retried.
    """

    def __init__(self, project_root: str | Path, session_dir: str | Path, *, session_protocol: str = "v5p4") -> None:
        self.project_root = Path(project_root).resolve()
        self.session_dir = Path(session_dir).resolve()
        self.session_protocol = str(session_protocol)
        allowed_root = (self.project_root / "runs" / "real_api_sessions").resolve()
        if self.session_dir.parent != allowed_root or not re.fullmatch(rf"{re.escape(self.session_protocol)}_[A-Za-z0-9_-]{{8,127}}", self.session_dir.name):
            raise GateDenied(f"{self.session_protocol} session directory must be a unique child of runs/real_api_sessions")
        self.authorization_path = self.session_dir / "authorization.json"
        self.state_path = self.session_dir / "gate_state.json"
        self.planned_requests_path = self.session_dir / "planned_requests.jsonl"
        self.attempt_ledger_path = self.session_dir / "attempt_ledger.jsonl"
        self.lock_path = self.session_dir / "gate_state.json.lock"

    def _authorization(self) -> dict[str, Any]:
        if not self.authorization_path.exists():
            raise GateDenied("V5-P4 session authorization is absent")
        try:
            value = json.loads(self.authorization_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateDenied("invalid V5-P4 session authorization") from exc
        if value.get("session_protocol") != self.session_protocol or value.get("authorization_status") != "AUTHORIZED":
            raise GateDenied(f"{self.session_protocol} session is not AUTHORIZED")
        return value

    def _planned(self, authorization: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if not self.planned_requests_path.exists():
            raise GateDenied("V5-P4 frozen request plan is absent")
        rows: dict[str, dict[str, Any]] = {}
        try:
            lines = self.planned_requests_path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                if line.strip():
                    item = json.loads(line)
                    request_id = str(item.get("request_id", ""))
                    if not request_id or request_id in rows:
                        raise GateDenied("V5-P4 frozen request plan is invalid")
                    rows[request_id] = item
        except (OSError, json.JSONDecodeError) as exc:
            raise GateDenied("invalid V5-P4 frozen request plan") from exc
        expected_ids = [str(item) for item in authorization.get("request_ids", [])]
        if len(rows) != len(expected_ids) or set(rows) != set(expected_ids):
            raise GateDenied("V5-P4 frozen request IDs do not match authorization")
        return rows

    def _default_state(self, authorization: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "session_protocol": self.session_protocol,
            "authorization_id": authorization.get("authorization_id"),
            "calls_used": 0,
            "estimated_cost_used_usd": 0.0,
            "attempts": [],
        }

    def _load_unlocked(self) -> dict[str, Any]:
        authorization = self._authorization()
        self._planned(authorization)
        if not self.state_path.exists():
            return self._default_state(authorization)
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateDenied("invalid V5-P4 gate state") from exc
        if state.get("authorization_id") != authorization.get("authorization_id") or state.get("session_protocol") != self.session_protocol:
            raise GateDenied(f"{self.session_protocol} gate state belongs to a different authorization")
        if not isinstance(state.get("attempts"), list):
            raise GateDenied("invalid V5-P4 gate attempts")
        return state

    def _save_unlocked(self, state: dict[str, Any]) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.state_path)

    def _append_ledger(self, item: dict[str, Any]) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        with self.attempt_ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    def assert_authorized(self, *, provider: str, model: str, worlds: list[str], conditions: list[str]) -> dict[str, Any]:
        authorization = self._authorization()
        if provider != authorization.get("provider") or model != authorization.get("model"):
            raise GateDenied("V5-P4 provider/model mismatch")
        if not set(worlds).issubset(set(authorization.get("worlds", []))) or not set(conditions).issubset(set(authorization.get("conditions", []))):
            raise GateDenied("V5-P4 scope mismatch")
        return authorization

    def preflight(self, *, provider: str, model: str, request_plan: list[dict[str, Any]], worlds: list[str], conditions: list[str]) -> dict[str, Any]:
        if not request_plan or len({str(item.get("request_id", "")) for item in request_plan}) != len(request_plan) or any(not item.get("request_id") for item in request_plan):
            raise GateDenied(f"{self.session_protocol} request plan must contain unique request IDs")
        with _FileMutex(self.lock_path):
            authorization = self.assert_authorized(provider=provider, model=model, worlds=worlds, conditions=conditions)
            frozen = self._planned(authorization)
            requested = {str(item["request_id"]): item for item in request_plan}
            if set(requested) != set(frozen):
                raise GateDenied("request plan is not the frozen V5-P4 plan")
            for request_id, item in requested.items():
                expected = frozen[request_id]
                for key in ("prompt_hash", "stage", "world_id", "condition", "max_output_tokens"):
                    if str(item.get(key)) != str(expected.get(key)):
                        raise GateDenied(f"V5-P4 frozen request mismatch: {request_id}:{key}")
                if abs(float(item.get("estimated_cost_usd", 0.0)) - float(expected.get("estimated_cost_usd", 0.0))) > 1e-12:
                    raise GateDenied(f"V5-P4 frozen request mismatch: {request_id}:estimated_cost_usd")
            state = self._load_unlocked()
            attempted = {str(item.get("request_id")) for item in state.get("attempts", [])}
            if attempted.intersection(requested):
                raise GateDenied("V5-P4 replay refused: a frozen request was already attempted")
            planned_cost = sum(float(item.get("estimated_cost_usd", 0.0)) for item in request_plan)
            max_calls = int(authorization.get("max_unique_provider_attempts", 0))
            max_cost = float(authorization.get("max_estimated_cost_usd", 0.0))
            if len(request_plan) > max_calls or float(state.get("estimated_cost_used_usd", 0.0)) + planned_cost > max_cost + 1e-12:
                raise GateDenied("V5-P4 frozen plan exceeds session cap")
            planned_calls = len(request_plan)
            return {"planned_calls": planned_calls, "planned_cost_usd": planned_cost, "calls_remaining": max_calls - int(state.get("calls_used", 0)) - planned_calls, "cost_remaining": max_cost - float(state.get("estimated_cost_used_usd", 0.0)) - planned_cost, "request_plan": request_plan}

    def reserve(self, *, request_id: str, provider: str, model: str, stage: str, estimated_cost_usd: float, world_id: str, condition: str, max_output_tokens: int | None = None) -> GateReservation:
        with _FileMutex(self.lock_path):
            authorization = self.assert_authorized(provider=provider, model=model, worlds=[world_id], conditions=[condition])
            frozen = self._planned(authorization)
            if request_id not in frozen:
                raise GateDenied("request ID is not in the frozen V5-P4 plan")
            expected = frozen[request_id]
            if str(expected.get("stage")) != str(stage) or str(expected.get("world_id")) != str(world_id) or str(expected.get("condition")) != str(condition):
                raise GateDenied("V5-P4 request metadata mismatch")
            if max_output_tokens is not None and int(expected.get("max_output_tokens", 0)) != int(max_output_tokens):
                raise GateDenied("V5-P4 max_output_tokens differs from frozen budget")
            expected_cost = float(expected.get("estimated_cost_usd", 0.0))
            if float(estimated_cost_usd) > expected_cost + 1e-12:
                raise GateDenied("V5-P4 actual conservative estimate exceeds frozen budget")
            state = self._load_unlocked()
            if any(str(item.get("request_id")) == request_id for item in state.get("attempts", [])):
                raise GateDenied(f"V5-P4 request_id already attempted: {request_id}")
            if any(str(item.get("status")) == "UNKNOWN_BILLING_OUTCOME" for item in state.get("attempts", [])):
                raise GateDenied("V5-P4 session is stopped after UNKNOWN_BILLING_OUTCOME")
            if any(str(item.get("status")) == "STARTED" for item in state.get("attempts", [])):
                raise GateDenied("V5-P4 session enforces serial execution")
            max_calls = int(authorization.get("max_unique_provider_attempts", 0))
            max_cost = float(authorization.get("max_estimated_cost_usd", 0.0))
            if int(state.get("calls_used", 0)) + 1 > max_calls:
                raise GateDenied("V5-P4 call cap exceeded")
            if float(state.get("estimated_cost_used_usd", 0.0)) + expected_cost > max_cost + 1e-12:
                raise GateDenied("V5-P4 cost cap exceeded")
            attempt_number = int(state.get("calls_used", 0)) + 1
            item = {"request_id": request_id, "attempt_number": attempt_number, "provider": provider, "model": model, "stage": stage, "world_id": world_id, "condition": condition, "estimated_cost_usd": expected_cost, "actual_request_estimate_usd": float(estimated_cost_usd), "max_output_tokens": max_output_tokens, "status": "STARTED", "started_at": utc_now(), "actual_cost_usd": None, "billing_verified": False}
            state.setdefault("attempts", []).append(item)
            state["calls_used"] = attempt_number
            state["estimated_cost_used_usd"] = float(state.get("estimated_cost_used_usd", 0.0)) + expected_cost
            self._save_unlocked(state)
            self._append_ledger(item)
            return GateReservation(request_id, expected_cost, attempt_number)

    def finish(self, reservation: GateReservation, *, status: str, actual_cost_usd: float | None = None, billing_verified: bool = False, returned_model: str | None = None, error: str | None = None) -> None:
        if status not in {"COMPLETED", "FAILED", "UNKNOWN_BILLING_OUTCOME"}:
            raise ValueError("V5-P4 gate status must be COMPLETED, FAILED, or UNKNOWN_BILLING_OUTCOME")
        with _FileMutex(self.lock_path):
            state = self._load_unlocked()
            for item in state.get("attempts", []):
                if item.get("request_id") == reservation.request_id:
                    item.update({"status": status, "finished_at": utc_now(), "actual_cost_usd": actual_cost_usd, "billing_verified": billing_verified, "returned_model": returned_model, "error": error})
                    self._save_unlocked(state)
                    self._append_ledger(item)
                    return
            raise GateDenied("V5-P4 reservation not found")

    def summary(self) -> dict[str, Any]:
        with _FileMutex(self.lock_path):
            authorization = self._authorization()
            state = self._load_unlocked()
            statuses = [str(item.get("status")) for item in state.get("attempts", [])]
            if "UNKNOWN_BILLING_OUTCOME" in statuses:
                real_status = "UNKNOWN_BILLING_OUTCOME"
            elif "FAILED" in statuses:
                real_status = "FAILED"
            elif "STARTED" in statuses:
                real_status = "STARTED"
            elif "COMPLETED" in statuses:
                real_status = "COMPLETED"
            else:
                real_status = "AUTHORIZED"
            return {"authorization_id": authorization.get("authorization_id"), "authorization_status": authorization.get("authorization_status"), "calls_used": int(state.get("calls_used", 0)), "max_unique_calls": int(authorization.get("max_unique_provider_attempts", 0)), "calls_remaining": int(authorization.get("max_unique_provider_attempts", 0)) - int(state.get("calls_used", 0)), "estimated_cost_used_usd": float(state.get("estimated_cost_used_usd", 0.0)), "max_estimated_cost_usd": float(authorization.get("max_estimated_cost_usd", 0.0)), "cost_remaining": float(authorization.get("max_estimated_cost_usd", 0.0)) - float(state.get("estimated_cost_used_usd", 0.0)), "completed_attempts": statuses.count("COMPLETED"), "failed_attempts": statuses.count("FAILED"), "unknown_billing_attempts": statuses.count("UNKNOWN_BILLING_OUTCOME"), "started_attempts": statuses.count("STARTED"), "real_api_status": real_status}


class V5P8SessionGate(V5P4SessionGate):
    """The same fail-closed frozen-plan gate with an independent V5P8 namespace."""

    def __init__(self, project_root: str | Path, session_dir: str | Path) -> None:
        super().__init__(project_root, session_dir, session_protocol="v5p8")


class V5P11SessionGate(V5P4SessionGate):
    """Independent fail-closed session namespace for the V5-P11 protocol."""

    def __init__(self, project_root: str | Path, session_dir: str | Path) -> None:
        super().__init__(project_root, session_dir, session_protocol="v5p11")
