from __future__ import annotations

"""Configuration-driven world discovery and path safety."""

import re
from pathlib import Path
from typing import Iterable

from .config import ExperimentConfig


WORLD_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
REQUIRED_PUBLIC_FILES = frozenset({"manifest.json", "candidate_experiments.json", "target_notes.md", "source_related.md", "source_irrelevant.md"})
REQUIRED_PRIVATE_FILES = frozenset({"hidden_truth.json", "oracle_results.json"})


def validate_world_id(world_id: str) -> str:
    value = str(world_id)
    if not WORLD_ID_RE.fullmatch(value):
        raise ValueError(f"invalid world id: {value!r}")
    return value


def _under(root: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def world_paths(project_root: str | Path, config: ExperimentConfig, world_id: str) -> tuple[Path, Path]:
    validate_world_id(world_id)
    root = Path(project_root).resolve()
    public_root = (root / "data" / config.worlds_subdir).resolve()
    private_root = (root / "private" / config.private_worlds_subdir).resolve()
    public = public_root / world_id
    private = private_root / world_id
    if not _under(public_root, public) or not _under(private_root, private):
        raise ValueError(f"world path escapes configured roots: {world_id!r}")
    return public, private


def assert_world_available(project_root: str | Path, config: ExperimentConfig, world_id: str, *, require_private: bool = True) -> str:
    value = validate_world_id(world_id)
    public, private = world_paths(project_root, config, value)
    if not public.is_dir():
        raise ValueError(f"unknown world: {value}")
    missing_public = sorted(name for name in REQUIRED_PUBLIC_FILES if not (public / name).is_file())
    if missing_public:
        raise ValueError(f"world {value} missing public files: {','.join(missing_public)}")
    if require_private:
        if not private.is_dir():
            raise ValueError(f"world {value} missing private scoring fixture")
        missing_private = sorted(name for name in REQUIRED_PRIVATE_FILES if not (private / name).is_file())
        if missing_private:
            raise ValueError(f"world {value} missing private files: {','.join(missing_private)}")
    return value


def configured_world_ids(project_root: str | Path, config: ExperimentConfig, *, require_private: bool = True) -> list[str]:
    root = Path(project_root).resolve()
    if config.allowed_worlds:
        candidates = [validate_world_id(world_id) for world_id in config.allowed_worlds]
    else:
        public_root = (root / "data" / config.worlds_subdir).resolve()
        if not public_root.is_dir():
            return []
        candidates = sorted(path.name for path in public_root.iterdir() if path.is_dir() and WORLD_ID_RE.fullmatch(path.name))
    result: list[str] = []
    for world_id in candidates:
        assert_world_available(root, config, world_id, require_private=require_private)
        if world_id not in result:
            result.append(world_id)
    return result


def resolve_worlds(project_root: str | Path, config: ExperimentConfig, requested: str | Iterable[str] | None, *, require_private: bool = True) -> list[str]:
    available = configured_world_ids(project_root, config, require_private=require_private)
    if requested is None or (isinstance(requested, str) and requested.strip().lower() == "all"):
        return list(available)
    if isinstance(requested, str):
        selected = [item.strip() for item in requested.split(",") if item.strip()]
    else:
        selected = [str(item) for item in requested]
    unknown = []
    result: list[str] = []
    for world_id in selected:
        try:
            validate_world_id(world_id)
        except ValueError:
            unknown.append(world_id)
            continue
        if world_id not in available:
            unknown.append(world_id)
        elif world_id not in result:
            result.append(world_id)
    if unknown:
        raise ValueError(f"unknown world: {', '.join(unknown)}")
    return result
