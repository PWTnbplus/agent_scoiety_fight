from __future__ import annotations

"""Offline, operator-confirmed authorization records for real API stages."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
from typing import Any

from .proposal_fingerprint import verify_proposal_digest
from .schema import sha256_json
from .stable_fingerprint import stable_tree_hash


AUTHORIZATION_FILE = Path("runs") / "real_authorization_manifest.json"
V4_SESSION_ROOT = Path("runs") / "real_api_sessions"
V5P4_SESSION_ROOT = Path("runs") / "real_api_sessions"
CONFIRMATION_PHRASE = "V3_REAL_API_AUTHORIZED"
V4_CONFIRMATION_PHRASE = "V4_REAL_API_AUTHORIZED"
V5P4_CONFIRMATION_PHRASE = "V5P4_REAL_API_AUTHORIZED"
V5P8_CONFIRMATION_PHRASE = "V5P8_REAL_API_AUTHORIZED"
V5P11_CONFIRMATION_PHRASE = "V5P11_REAL_API_AUTHORIZED"
STAGE_ORDER = ("check-api", "probe-role", "pilot")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def config_digest(config: Any) -> str:
    return sha256_json(config.to_dict())


def authorization_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / AUTHORIZATION_FILE


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_authorization(project_root: str | Path) -> dict[str, Any] | None:
    path = authorization_path(project_root)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PermissionError(f"invalid real authorization manifest: {path}") from exc
    if not isinstance(value, dict):
        raise PermissionError("real authorization manifest must be an object")
    return value


def create_authorization(
    project_root: str | Path,
    config: Any,
    *,
    approved_by: str,
    provider: str,
    model: str,
    scope: list[str],
    worlds: list[str],
    conditions: list[str],
    max_unique_provider_attempts: int,
    max_estimated_cost_usd: float,
    confirmation: str,
    authorization_note: str,
) -> Path:
    destination = authorization_path(project_root)
    if destination.exists():
        raise PermissionError(f"authorization manifest already exists; refusing to overwrite: {destination}")
    if approved_by != "user_explicit":
        raise PermissionError("approved_by must be user_explicit")
    if confirmation != CONFIRMATION_PHRASE:
        raise PermissionError("explicit authorization confirmation phrase did not match")
    if provider != "kimi26" or model != "kimi-k2.6":
        raise PermissionError("V3 first pilot is frozen to provider kimi26 and model kimi-k2.6")
    if not scope or not set(scope).issubset(set(STAGE_ORDER)):
        raise ValueError("scope must contain only check-api, probe-role, and pilot")
    if not worlds or not set(worlds).issubset(set(config.allowed_worlds or worlds)):
        raise ValueError("authorization worlds exceed configured scope")
    if not conditions or not set(conditions).issubset(set(config.allowed_conditions or conditions)):
        raise ValueError("authorization conditions exceed configured scope")
    if max_unique_provider_attempts <= 0 or max_estimated_cost_usd <= 0:
        raise ValueError("authorization call and cost caps must be positive")
    if config.authorized_provider and provider != config.authorized_provider:
        raise ValueError("provider does not match config authorization scope")
    if config.authorized_model and model != config.authorized_model:
        raise ValueError("model does not match config authorization scope")
    initial_stage = "check-api" if "check-api" in scope else scope[0]
    record = {
        "schema_version": 1,
        "authorization_id": f"auth-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "authorization_status": "AUTHORIZED",
        "approved_by": approved_by,
        "confirmed_at": utc_now(),
        "confirmation_method": "explicit_confirmation_phrase",
        "provider": provider,
        "model": model,
        "scope": list(scope),
        "current_stage": initial_stage,
        "worlds": list(worlds),
        "conditions": list(conditions),
        "max_unique_provider_attempts": int(max_unique_provider_attempts),
        "max_estimated_cost_usd": float(max_estimated_cost_usd),
        "parallelism": 1,
        "auto_retry": False,
        "authorization_note": authorization_note,
        "config_hash": config_digest(config),
        "history": [{"event": "AUTHORIZED", "at": utc_now(), "stage": initial_stage}],
    }
    _atomic_write(destination, record)
    return destination


def advance_stage(project_root: str | Path, *, target_stage: str, confirmation: str) -> Path:
    if target_stage not in STAGE_ORDER:
        raise ValueError(f"unknown real API stage: {target_stage}")
    if confirmation != CONFIRMATION_PHRASE:
        raise PermissionError("explicit stage-advance confirmation phrase did not match")
    path = authorization_path(project_root)
    record = load_authorization(project_root)
    if record is None or record.get("authorization_status") != "AUTHORIZED":
        raise PermissionError("no active user authorization manifest")
    if target_stage not in set(record.get("scope", [])):
        raise PermissionError(f"stage outside authorization scope: {target_stage}")
    current = str(record.get("current_stage", ""))
    if STAGE_ORDER.index(target_stage) < STAGE_ORDER.index(current):
        raise PermissionError("stage cannot move backwards")
    record["current_stage"] = target_stage
    record.setdefault("history", []).append({"event": "STAGE_ADVANCED", "at": utc_now(), "from": current, "stage": target_stage})
    _atomic_write(path, record)
    return path


def v4_session_dir(project_root: str | Path, session_id: str) -> Path:
    if not session_id or any(char in session_id for char in "\\/:\x00"):
        raise ValueError("invalid V4 session id")
    return Path(project_root).resolve() / V4_SESSION_ROOT / session_id


def v5p4_session_dir(project_root: str | Path, session_id: str) -> Path:
    """Resolve a V5-P4 session without allowing path traversal or aliases."""
    if not session_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}", session_id):
        raise ValueError("invalid V5-P4 session id")
    return Path(project_root).resolve() / V5P4_SESSION_ROOT / session_id


def v5p8_session_dir(project_root: str | Path, session_id: str) -> Path:
    """Resolve a V5-P8 session without allowing path traversal or aliases."""
    if not session_id or not re.fullmatch(r"v5p8_[A-Za-z0-9][A-Za-z0-9_-]{7,127}", session_id):
        raise ValueError("invalid V5-P8 session id")
    return Path(project_root).resolve() / V5P4_SESSION_ROOT / session_id


def v5p11_session_dir(project_root: str | Path, session_id: str) -> Path:
    """Resolve an independent V5-P11 session without path traversal."""
    if not session_id or not re.fullmatch(r"v5p11_[A-Za-z0-9][A-Za-z0-9_-]{7,127}", session_id):
        raise ValueError("invalid V5-P11 session id")
    return Path(project_root).resolve() / V5P4_SESSION_ROOT / session_id


def proposed_v4_authorization(project_root: str | Path, config: Any, *, provider: str = "kimi26", model: str = "kimi-k2.6", worlds: list[str] | None = None, conditions: list[str] | None = None, max_unique_provider_attempts: int = 5, max_estimated_cost_usd: float = 0.05, protocol_hash: str = "") -> dict[str, Any]:
    worlds = list(worlds or ["W001"])
    conditions = list(conditions or ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"])
    if provider != "kimi26" or model != "kimi-k2.6":
        raise ValueError("V4 proposal is frozen to kimi26/kimi-k2.6")
    if worlds != ["W001"] or set(conditions) != {"A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}:
        raise ValueError("V4 proposal scope must be W001 A/B/C/D")
    if max_unique_provider_attempts != 5 or max_estimated_cost_usd <= 0 or max_estimated_cost_usd > 0.05:
        raise ValueError("V4 proposal must be exactly five requests and no more than USD 0.05")
    return {
        "schema_version": 1,
        "authorization_id": "PROPOSED_V4_SESSION_ID",
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "approved_by": None,
        "provider": provider,
        "model": model,
        "scope": ["pilot"],
        "worlds": worlds,
        "conditions": conditions,
        "max_unique_provider_attempts": max_unique_provider_attempts,
        "max_estimated_cost_usd": float(max_estimated_cost_usd),
        "parallelism": 1,
        "auto_retry": False,
        "config_hash": config_digest(config),
        "protocol_hash": protocol_hash,
        "old_v3_authorization_untouched": True,
    }


def create_v4_authorization(project_root: str | Path, config: Any, *, approved_by: str, confirmation: str, authorization_note: str, **kwargs: Any) -> Path:
    if approved_by != "user_explicit" or confirmation != V4_CONFIRMATION_PHRASE:
        raise PermissionError("V4 authorization requires a new explicit user confirmation")
    record = proposed_v4_authorization(project_root, config, **kwargs)
    auth_id = f"auth-v4-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    destination = v4_session_dir(project_root, auth_id)
    if destination.exists():
        raise PermissionError(f"V4 session already exists: {destination}")
    record.update({"authorization_id": auth_id, "authorization_status": "AUTHORIZED", "approved_by": approved_by, "confirmed_at": utc_now(), "authorization_note": authorization_note, "current_stage": "pilot", "history": [{"event": "AUTHORIZED", "at": utc_now(), "stage": "pilot"}]})
    _atomic_write(destination / "authorization.json", record)
    return destination / "authorization.json"


def proposed_v5p4_authorization(
    project_root: str | Path,
    config: Any,
    *,
    request_plan: list[dict[str, Any]],
    provider: str = "kimi26",
    model: str = "kimi-k2.6",
    worlds: list[str] | None = None,
    conditions: list[str] | None = None,
    max_unique_provider_attempts: int = 5,
    max_estimated_cost_usd: float = 0.05,
) -> dict[str, Any]:
    """Create a new, non-authorizing V5-P4 proposal from a frozen plan."""
    worlds = list(worlds or ["CV001"])
    conditions = list(conditions or ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"])
    if provider != "kimi26" or model != "kimi-k2.6":
        raise ValueError("V5-P4 proposal is frozen to kimi26/kimi-k2.6")
    if worlds != ["CV001"] or conditions != ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]:
        raise ValueError("V5-P4 proposal scope must be CV001 A/B/C/D")
    if max_unique_provider_attempts != 5 or max_estimated_cost_usd <= 0 or max_estimated_cost_usd > 0.05:
        raise ValueError("V5-P4 proposal must be exactly five requests and no more than USD 0.05")
    request_ids = [str(item.get("request_id", "")) for item in request_plan]
    if len(request_plan) != 5 or any(not item for item in request_ids) or len(set(request_ids)) != 5:
        raise ValueError("V5-P4 proposal requires five unique frozen request IDs")
    if any(str(item.get("world_id")) != "CV001" for item in request_plan):
        raise ValueError("V5-P4 request plan contains a world outside CV001")
    if float(sum(float(item.get("estimated_cost_usd", 0.0)) for item in request_plan)) > max_estimated_cost_usd + 1e-12:
        raise ValueError("V5-P4 request plan exceeds the proposal cost cap")
    plan_hash = sha256_json(request_plan)
    session_seed = f"v5p4-proposed-{plan_hash[:20]}"
    return {
        "schema_version": 2,
        "session_protocol": "v5p4",
        "authorization_id": session_seed,
        "session_id": session_seed,
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "approved_by": None,
        "provider": provider,
        "model": model,
        "scope": ["pilot"],
        "worlds": worlds,
        "conditions": conditions,
        "max_unique_provider_attempts": max_unique_provider_attempts,
        "max_estimated_cost_usd": float(max_estimated_cost_usd),
        "parallelism": 1,
        "auto_retry": False,
        "config_hash": config_digest(config),
        "frozen_config_hash": config_digest(config),
        "prompt_hashes": {str(item["request_id"]): str(item.get("prompt_hash", "")) for item in request_plan},
        "request_plan_hash": plan_hash,
        "request_ids": request_ids,
        "request_plan": request_plan,
        "max_output_tokens_by_stage": {"stage2_single": 900, "stage1": 600, "stage2_seq2": 600},
        "real_api_calls_this_round": 0,
        "old_authorizations_untouched": True,
        "authorization_note": "Offline proposal only; explicit new user authorization is required before any HTTP request.",
    }


def create_v5p4_authorization(
    project_root: str | Path,
    config: Any,
    *,
    approved_by: str,
    confirmation: str,
    authorization_note: str,
    request_plan: list[dict[str, Any]],
    proposal_path: str | Path | None = None,
    proposal_sha256: str | None = None,
    require_proposal_binding: bool = False,
    **kwargs: Any,
) -> Path:
    """Create an authorized V5-P4 session only after a new explicit approval."""
    if approved_by != "user_explicit" or confirmation != V5P4_CONFIRMATION_PHRASE:
        raise PermissionError("V5-P4 authorization requires a new explicit user confirmation")
    record = proposed_v5p4_authorization(project_root, config, request_plan=request_plan, **kwargs)
    if require_proposal_binding and (proposal_path is None or proposal_sha256 is None):
        raise PermissionError("V5-P4 authorization requires a complete proposal file and SHA256 binding")
    if proposal_path is not None or proposal_sha256 is not None:
        if proposal_path is None or proposal_sha256 is None:
            raise PermissionError("proposal file and proposal SHA256 must be supplied together")
        proposal_file = Path(proposal_path).resolve()
        try:
            proposal = json.loads(proposal_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PermissionError("proposal file cannot be read as JSON") from exc
        if not isinstance(proposal, dict):
            raise PermissionError("proposal file must contain an object")
        verified_sha = verify_proposal_digest(proposal, proposal_sha256)
        expected_fields = {
            "provider": record["provider"],
            "model": record["model"],
            "worlds": record["worlds"],
            "conditions": record["conditions"],
            "max_unique_provider_attempts": record["max_unique_provider_attempts"],
            "max_estimated_cost_usd": record["max_estimated_cost_usd"],
            "parallelism": record["parallelism"],
            "auto_retry": record["auto_retry"],
            "frozen_config_hash": record["frozen_config_hash"],
            "request_plan_hash": record["request_plan_hash"],
            "request_ids": record["request_ids"],
            "prompt_hashes": record["prompt_hashes"],
        }
        for key, expected in expected_fields.items():
            if proposal.get(key) != expected:
                raise PermissionError(f"proposal binding mismatch: {key}")
        tree_bindings = {
            "source_tree_hash": Path(project_root).resolve() / "src",
            "tests_tree_hash": Path(project_root).resolve() / "tests",
            "scripts_tree_hash": Path(project_root).resolve() / "scripts",
            "public_world_tree_hash": Path(project_root).resolve() / "data" / "worlds_v5p4_dev",
            "private_fixture_tree_hash": Path(project_root).resolve() / "private" / "worlds_v5p4_dev",
            "docs_tree_hash": Path(project_root).resolve() / "docs",
        }
        for field, tree in tree_bindings.items():
            if proposal.get(field) != stable_tree_hash(tree):
                raise PermissionError(f"proposal binding mismatch: {field}")
        record["proposal_sha256"] = verified_sha
        record["proposal_fingerprints"] = {field: proposal[field] for field in tree_bindings}
        record["proposal_file"] = str(proposal_file)
    token = secrets.token_urlsafe(12).replace("-", "_")
    auth_id = f"auth-v5p4-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{token}"
    session_id = f"v5p4_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{token}"
    destination = v5p4_session_dir(project_root, session_id)
    if destination.exists():
        raise PermissionError(f"V5-P4 session already exists: {destination}")
    record.update({
        "authorization_id": auth_id,
        "session_id": session_id,
        "authorization_status": "AUTHORIZED",
        "approved_by": approved_by,
        "confirmed_at": utc_now(),
        "confirmation_method": "explicit_new_session_confirmation",
        "authorization_note": authorization_note,
        "history": [{"event": "AUTHORIZED", "at": utc_now(), "stage": "pilot"}],
    })
    _atomic_write(destination / "authorization.json", record)
    (destination / "planned_requests.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in request_plan), encoding="utf-8")
    (destination / "attempt_ledger.jsonl").write_text("", encoding="utf-8")
    return destination / "authorization.json"


def proposed_v5p8_authorization(
    project_root: str | Path,
    config: Any,
    *,
    request_plan: list[dict[str, Any]],
    provider: str = "kimi26",
    model: str = "kimi-k2.6",
    worlds: list[str] | None = None,
    conditions: list[str] | None = None,
    max_unique_provider_attempts: int = 40,
    max_estimated_cost_usd: float = 0.40,
    repeats: int | None = None,
    request_namespace: str | None = None,
) -> dict[str, Any]:
    """Create a non-authorizing, plan-bound V5P8 proposal.

    The frozen request plan may be the complete V5P8 design or a legal,
    explicitly bound subset.  This is what lets a narrowly authorized pilot
    use the same fail-closed machinery without granting the four-world plan.
    """
    worlds = list(worlds or ["CV001", "CV002", "CV003", "CV004"])
    conditions = list(conditions or ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"])
    allowed_worlds = ["CV001", "CV002", "CV003", "CV004"]
    allowed_conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    if provider != "kimi26" or model != "kimi-k2.6":
        raise ValueError("V5-P8 proposal is frozen to kimi26/kimi-k2.6")
    if not str(config.score_version).startswith("v5p8"):
        raise ValueError("V5-P8 proposal requires a v5p8 configuration")
    if not worlds or len(set(worlds)) != len(worlds) or any(world not in allowed_worlds for world in worlds):
        raise ValueError("V5-P8 proposal worlds must be a unique subset of CV001-CV004")
    if not conditions or conditions != [condition for condition in allowed_conditions if condition in conditions]:
        raise ValueError("V5-P8 proposal conditions must be an ordered subset of A/B/C/D")
    proposal_repeats = int(getattr(config, "repeats", 2) if repeats is None else repeats)
    if proposal_repeats < 1:
        raise ValueError("V5-P8 proposal repeats must be positive")
    if request_namespace is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,100}", str(request_namespace)):
        raise ValueError("V5-P8 request namespace is invalid")
    request_ids = [str(item.get("request_id", "")) for item in request_plan]
    if not request_plan or any(not item for item in request_ids) or len(set(request_ids)) != len(request_plan):
        raise ValueError("V5-P8 proposal requires unique frozen request IDs")
    if any(str(item.get("world_id")) not in worlds for item in request_plan):
        raise ValueError("V5-P8 request plan contains a world outside the authorized subset")
    if any(str(item.get("condition")) not in conditions for item in request_plan):
        raise ValueError("V5-P8 request plan contains a condition outside the authorized subset")
    if any(int(item.get("replicate", 0)) < 0 or int(item.get("replicate", 0)) >= proposal_repeats for item in request_plan):
        raise ValueError("V5-P8 request plan contains a replicate outside the authorized subset")
    if set(str(item.get("condition")) for item in request_plan) != set(conditions):
        raise ValueError("V5-P8 request plan must cover every authorized condition")
    if max_unique_provider_attempts < len(request_plan):
        raise ValueError("V5-P8 call cap is smaller than the frozen request plan")
    plan_hash = sha256_json(request_plan)
    estimated_cost = float(sum(float(item.get("estimated_cost_usd", 0.0)) for item in request_plan))
    if estimated_cost > float(max_estimated_cost_usd) + 1e-12:
        raise ValueError("V5-P8 request plan exceeds the proposal cost cap")
    session_seed = f"v5p8-proposed-{plan_hash[:20]}"
    return {
        "schema_version": 3,
        "session_protocol": "v5p8",
        "authorization_id": session_seed,
        "session_id": session_seed,
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "approved_by": None,
        "provider": provider,
        "model": model,
        "scope": ["pilot"],
        "worlds": worlds,
        "conditions": conditions,
        "max_unique_provider_attempts": int(max_unique_provider_attempts),
        "max_estimated_cost_usd": float(max_estimated_cost_usd),
        "parallelism": 1,
        "auto_retry": False,
        "config_hash": config_digest(config),
        "frozen_config_hash": config_digest(config),
        "prompt_hashes": {str(item["request_id"]): str(item.get("prompt_hash", "")) for item in request_plan},
        "request_plan_hash": plan_hash,
        "request_ids": request_ids,
        "request_plan": request_plan,
        "repeats": proposal_repeats,
        "request_namespace": request_namespace,
        "real_api_calls_this_round": 0,
        "old_authorizations_untouched": True,
        "authorization_note": "Offline proposal only; explicit new user authorization naming this exact proposal is required before any HTTP request.",
    }


def create_v5p8_authorization(
    project_root: str | Path,
    config: Any,
    *,
    approved_by: str,
    confirmation: str,
    authorization_note: str,
    request_plan: list[dict[str, Any]],
    proposal_path: str | Path | None = None,
    proposal_sha256: str | None = None,
    require_proposal_binding: bool = False,
    **kwargs: Any,
) -> Path:
    """Create an independent authorized V5P8 session after explicit approval."""
    if approved_by != "user_explicit" or confirmation != V5P8_CONFIRMATION_PHRASE:
        raise PermissionError("V5-P8 authorization requires a new explicit user confirmation")
    record = proposed_v5p8_authorization(project_root, config, request_plan=request_plan, **kwargs)
    if require_proposal_binding and (proposal_path is None or proposal_sha256 is None):
        raise PermissionError("V5-P8 authorization requires a complete proposal file and SHA256 binding")
    if proposal_path is not None or proposal_sha256 is not None:
        if proposal_path is None or proposal_sha256 is None:
            raise PermissionError("proposal file and proposal SHA256 must be supplied together")
        proposal_file = Path(proposal_path).resolve()
        try:
            proposal = json.loads(proposal_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PermissionError("proposal file cannot be read as JSON") from exc
        if not isinstance(proposal, dict):
            raise PermissionError("proposal file must contain an object")
        verified_sha = verify_proposal_digest(proposal, proposal_sha256)
        expected_fields = {
            "provider": record["provider"],
            "model": record["model"],
            "worlds": record["worlds"],
            "conditions": record["conditions"],
            "max_unique_provider_attempts": record["max_unique_provider_attempts"],
            "max_estimated_cost_usd": record["max_estimated_cost_usd"],
            "parallelism": record["parallelism"],
            "auto_retry": record["auto_retry"],
            "frozen_config_hash": record["frozen_config_hash"],
            "request_plan_hash": record["request_plan_hash"],
            "request_ids": record["request_ids"],
            "prompt_hashes": record["prompt_hashes"],
        }
        if record.get("request_namespace") is not None:
            expected_fields["request_namespace"] = record["request_namespace"]
        for key, expected in expected_fields.items():
            if proposal.get(key) != expected:
                raise PermissionError(f"proposal binding mismatch: {key}")
        root = Path(project_root).resolve()
        tree_bindings = {
            "source_tree_hash": root / "src",
            "tests_tree_hash": root / "tests",
            "scripts_tree_hash": root / "scripts",
            "public_world_tree_hash": root / "data" / config.worlds_subdir,
            "private_fixture_tree_hash": root / "private" / config.private_worlds_subdir,
            "docs_tree_hash": root / "docs",
        }
        for field, tree in tree_bindings.items():
            if proposal.get(field) != stable_tree_hash(tree):
                raise PermissionError(f"proposal binding mismatch: {field}")
        record["proposal_sha256"] = verified_sha
        record["proposal_fingerprints"] = {field: proposal[field] for field in tree_bindings}
        record["proposal_file"] = str(proposal_file)
    token = secrets.token_urlsafe(12).replace("-", "_")
    auth_id = f"auth-v5p8-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{token}"
    session_id = f"v5p8_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{token}"
    destination = v5p8_session_dir(project_root, session_id)
    if destination.exists():
        raise PermissionError(f"V5-P8 session already exists: {destination}")
    record.update({
        "authorization_id": auth_id,
        "session_id": session_id,
        "authorization_status": "AUTHORIZED",
        "approved_by": approved_by,
        "confirmed_at": utc_now(),
        "confirmation_method": "explicit_new_v5p8_session_confirmation",
        "authorization_note": authorization_note,
        "history": [{"event": "AUTHORIZED", "at": utc_now(), "stage": "pilot"}],
    })
    _atomic_write(destination / "authorization.json", record)
    (destination / "planned_requests.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in request_plan), encoding="utf-8")
    (destination / "attempt_ledger.jsonl").write_text("", encoding="utf-8")
    return destination / "authorization.json"


def proposed_v5p11_authorization(
    project_root: str | Path,
    config: Any,
    *,
    request_plan: list[dict[str, Any]],
    provider: str = "kimi26",
    model: str = "kimi-k2.6",
    worlds: list[str] | None = None,
    conditions: list[str] | None = None,
    max_unique_provider_attempts: int = 40,
    max_estimated_cost_usd: float = 0.40,
    repeats: int | None = None,
    request_namespace: str | None = None,
) -> dict[str, Any]:
    """Create a non-authorizing V5-P11 proposal bound to the new IV worlds."""
    worlds = list(worlds or ["IV001", "IV002", "IV003", "IV004"])
    conditions = list(conditions or ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"])
    allowed_worlds = ["IV001", "IV002", "IV003", "IV004"]
    allowed_conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    if provider != "kimi26" or model != "kimi-k2.6":
        raise ValueError("V5-P11 proposal is frozen to kimi26/kimi-k2.6")
    if str(config.score_version) != "v5p11":
        raise ValueError("V5-P11 proposal requires score_version=v5p11")
    remainder_worlds = ["IV002", "IV003", "IV004"]
    is_research = str(request_namespace or "").startswith("V5P15")
    is_remainder = worlds == remainder_worlds and conditions == allowed_conditions
    is_recovery = str(request_namespace or "").startswith("V5P12REC") and conditions == allowed_conditions and set(worlds).issubset(set(allowed_worlds))
    is_v5p13 = str(request_namespace or "").startswith("V5P13") and worlds == ["IV002"] and conditions == allowed_conditions
    if is_research:
        configured_worlds = set(getattr(config, "allowed_worlds", None) or [])
        configured_conditions = set(getattr(config, "allowed_conditions", None) or getattr(config, "conditions", None) or [])
        if not worlds or not set(worlds).issubset(configured_worlds) or not conditions or not set(conditions).issubset(configured_conditions):
            raise ValueError("V5-P15 proposal exceeds the frozen research config scope")
    elif worlds != allowed_worlds and not is_remainder and not is_recovery and not is_v5p13:
        raise ValueError("V5-P11 proposal must cover all IV worlds or an explicit V5-P12 remainder/recovery or V5-P13 follow-up scope")
    proposal_repeats = int(getattr(config, "repeats", 2) if repeats is None else repeats)
    expected_calls = len(request_plan) if (is_research or is_recovery or is_v5p13) else (30 if is_remainder else 40)
    allowed_cap = 10.0 if is_research else (0.15 if is_v5p13 else (0.25 if (is_remainder or is_recovery) else 0.40))
    repeats_valid = proposal_repeats == int(getattr(config, "repeats", proposal_repeats)) if is_research else (proposal_repeats == 4 if is_v5p13 else proposal_repeats == 2)
    if not repeats_valid or max_unique_provider_attempts != expected_calls or max_estimated_cost_usd <= 0 or max_estimated_cost_usd > allowed_cap:
        raise ValueError("V5-P11 proposal has an invalid call/cost cap for its frozen scope")
    if request_namespace is None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,100}", str(request_namespace)):
        raise ValueError("V5-P11 request namespace is required and invalid")
    request_ids = [str(item.get("request_id", "")) for item in request_plan]
    if len(request_plan) != expected_calls or any(not item for item in request_ids) or len(set(request_ids)) != expected_calls:
        raise ValueError(f"V5-P11 proposal requires exactly {expected_calls} unique frozen request IDs")
    if any(str(item.get("world_id")) not in worlds or str(item.get("condition")) not in conditions for item in request_plan):
        raise ValueError("V5-P11 request plan contains an out-of-scope world or condition")
    if any((int(item.get("replicate", -1)) < 0 or int(item.get("replicate", -1)) >= proposal_repeats) for item in request_plan):
        raise ValueError("V5-P11 request plan contains an invalid repeat index")
    pairs = {}
    for item in request_plan:
        pairs.setdefault((str(item.get("world_id")), int(item.get("replicate"))), []).append(item)
    expected_pairs = {(world, replicate) for world in worlds for replicate in (0, 1)}
    if is_research or is_recovery or is_v5p13:
        expected_pairs = set(pairs)
    if set(pairs) != expected_pairs or any(len(items) < 1 for items in pairs.values()):
        raise ValueError("V5-P11 request plan must have five requests per authorized world/repeat pair")
    plan_hash = sha256_json(request_plan)
    estimated_cost = float(sum(float(item.get("estimated_cost_usd", 0.0)) for item in request_plan))
    if estimated_cost > float(max_estimated_cost_usd) + 1e-12:
        raise ValueError("V5-P11 request plan exceeds proposal cost cap")
    session_seed = f"v5p11-proposed-{plan_hash[:20]}"
    record = {
        "schema_version": 4,
        "session_protocol": "v5p11",
        "authorization_id": session_seed,
        "session_id": session_seed,
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "approved_by": None,
        "provider": provider,
        "model": model,
        "scope": ["pilot"],
        "worlds": worlds,
        "conditions": conditions,
        "repeats": proposal_repeats,
        "max_unique_provider_attempts": max_unique_provider_attempts,
        "max_estimated_cost_usd": float(max_estimated_cost_usd),
        "parallelism": 1,
        "auto_retry": False,
        "config_hash": config_digest(config),
        "frozen_config_hash": config_digest(config),
        "prompt_hashes": {str(item["request_id"]): str(item.get("prompt_hash", "")) for item in request_plan},
        "request_plan_hash": plan_hash,
        "request_ids": request_ids,
        "request_plan": request_plan,
        "request_namespace": request_namespace,
        "max_output_tokens_by_stage": {"stage2_single": 900, "stage1": 600, "stage2_seq2": 600},
        "real_api_calls_this_round": 0,
        "old_authorizations_untouched": True,
        "authorization_note": "Offline proposal only; explicit new user authorization naming this exact proposal is required before any HTTP request.",
    }
    if is_remainder:
        record["protocol_variant"] = "v5p12_remainder"
        record["remainder_of_historical_plan"] = "IV002-IV004/R0-R1 only; old IV001 failure is excluded and cannot be retried"
    elif is_recovery:
        record["protocol_variant"] = "v5p12_recovery_after_transport_stop"
        record["recovery_pair_keys"] = sorted(f"{world}/R{replicate}" for world, replicate in expected_pairs)
    elif is_v5p13:
        record["protocol_variant"] = "v5p13_iv002_followup"
        record["followup_cohort"] = "additional_followup_cohort_R2_R3"
    elif is_research:
        record["protocol_variant"] = "v5p15_research"
        record["research_protocol"] = "eight_worlds_balanced_positive_negative_v1"
        record["research_scope_is_additive"] = True
    return record


def create_v5p11_authorization(
    project_root: str | Path,
    config: Any,
    *,
    approved_by: str,
    confirmation: str,
    authorization_note: str,
    request_plan: list[dict[str, Any]],
    proposal_path: str | Path | None = None,
    proposal_sha256: str | None = None,
    require_proposal_binding: bool = False,
    **kwargs: Any,
) -> Path:
    """Create an independent V5-P11 session only after exact user approval."""
    if approved_by != "user_explicit" or confirmation != V5P11_CONFIRMATION_PHRASE:
        raise PermissionError("V5-P11 authorization requires a new explicit user confirmation")
    record = proposed_v5p11_authorization(project_root, config, request_plan=request_plan, **kwargs)
    if require_proposal_binding and (proposal_path is None or proposal_sha256 is None):
        raise PermissionError("V5-P11 authorization requires proposal file and SHA256 binding")
    if proposal_path is not None or proposal_sha256 is not None:
        if proposal_path is None or proposal_sha256 is None:
            raise PermissionError("proposal file and proposal SHA256 must be supplied together")
        proposal_file = Path(proposal_path).resolve()
        try:
            proposal = json.loads(proposal_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PermissionError("proposal file cannot be read as JSON") from exc
        verified_sha = verify_proposal_digest(proposal, proposal_sha256)
        expected_fields = {
            "session_protocol": record["session_protocol"], "provider": record["provider"], "model": record["model"],
            "worlds": record["worlds"], "conditions": record["conditions"], "repeats": record["repeats"],
            "max_unique_provider_attempts": record["max_unique_provider_attempts"], "max_estimated_cost_usd": record["max_estimated_cost_usd"],
            "parallelism": record["parallelism"], "auto_retry": record["auto_retry"], "frozen_config_hash": record["frozen_config_hash"],
            "request_plan_hash": record["request_plan_hash"], "request_ids": record["request_ids"], "prompt_hashes": record["prompt_hashes"],
            "request_namespace": record["request_namespace"],
        }
        if "protocol_variant" in record:
            expected_fields["protocol_variant"] = record["protocol_variant"]
        for key, expected in expected_fields.items():
            if proposal.get(key) != expected:
                raise PermissionError(f"V5-P11 proposal binding mismatch: {key}")
        root = Path(project_root).resolve()
        tree_bindings = {
            "source_tree_hash": root / "src", "tests_tree_hash": root / "tests", "scripts_tree_hash": root / "scripts",
            "public_world_tree_hash": root / "data" / config.worlds_subdir, "private_fixture_tree_hash": root / "private" / config.private_worlds_subdir,
            "docs_tree_hash": root / "docs",
        }
        for field, tree in tree_bindings.items():
            if proposal.get(field) != stable_tree_hash(tree):
                raise PermissionError(f"V5-P11 proposal binding mismatch: {field}")
        record["proposal_sha256"] = verified_sha
        record["proposal_fingerprints"] = {field: proposal[field] for field in tree_bindings}
        record["proposal_file"] = str(proposal_file)
    token = secrets.token_urlsafe(12).replace("-", "_")
    auth_id = f"auth-v5p11-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{token}"
    session_id = f"v5p11_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{token}"
    destination = v5p11_session_dir(project_root, session_id)
    if destination.exists():
        raise PermissionError(f"V5-P11 session already exists: {destination}")
    record.update({"authorization_id": auth_id, "session_id": session_id, "authorization_status": "AUTHORIZED", "approved_by": approved_by, "confirmed_at": utc_now(), "confirmation_method": "explicit_new_v5p11_session_confirmation", "authorization_note": authorization_note, "history": [{"event": "AUTHORIZED", "at": utc_now(), "stage": "pilot"}]})
    _atomic_write(destination / "authorization.json", record)
    (destination / "planned_requests.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in request_plan), encoding="utf-8")
    (destination / "attempt_ledger.jsonl").write_text("", encoding="utf-8")
    return destination / "authorization.json"
