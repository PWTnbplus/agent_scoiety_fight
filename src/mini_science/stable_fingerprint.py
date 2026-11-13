from __future__ import annotations

"""Canonical, fail-closed fingerprints for authorization-scoped trees."""

import hashlib
import json
from pathlib import Path


CACHE_DIRS = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".coverage_cache",
})
TRANSIENT_NAMES = frozenset({".DS_Store", "Thumbs.db"})
TRANSIENT_SUFFIXES = frozenset({".pyc", ".pyo", ".swp", ".swo", ".tmp"})


def _is_transient(path: Path) -> bool:
    return path.name in TRANSIENT_NAMES or path.name.startswith("~$") or path.suffix.lower() in TRANSIENT_SUFFIXES


def stable_tree_manifest(root: Path | str) -> list[dict[str, str]]:
    """Return the canonical relative-path/content digest rows for ``root``.

    Generated caches are excluded explicitly. All other files, regardless of
    extension, remain part of the fingerprint. Missing roots, unreadable
    files, and symlinks fail closed so an authorization cannot be created from
    an incomplete or ambiguous tree.
    """

    base = Path(root)
    if not base.is_dir() or base.is_symlink():
        raise ValueError(f"not a valid non-symlink directory: {base}")
    rows: list[dict[str, str]] = []
    for path in base.rglob("*"):
        relative = path.relative_to(base)
        if path.is_symlink():
            raise ValueError(f"symlink encountered in frozen tree: {relative.as_posix()}")
        if any(part in CACHE_DIRS for part in relative.parts):
            continue
        if not path.is_file() or _is_transient(path):
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"cannot read frozen tree file: {relative.as_posix()}") from exc
        rows.append({
            "relative_path": relative.as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    rows.sort(key=lambda row: row["relative_path"])
    return rows


def stable_tree_hash(root: Path | str) -> str:
    """Hash canonical relative paths and content, independent of caches/order."""

    payload = json.dumps(
        stable_tree_manifest(root),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
