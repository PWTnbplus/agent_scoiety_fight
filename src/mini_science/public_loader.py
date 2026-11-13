from __future__ import annotations

import json
import re
from pathlib import Path

from .schema import WorldPublicView
from .world_registry import assert_world_available, world_paths


EVIDENCE_RE = re.compile(r"\b([TS]\d{2})\b")


def _evidence_ids(text: str, prefix: str) -> tuple[str, ...]:
    return tuple(sorted({match.group(1) for match in EVIDENCE_RE.finditer(text) if match.group(1).startswith(prefix)}))


def load_world(project_root: str | Path, world_id: str, source_variant: str = "related", *, worlds_subdir: str = "worlds") -> WorldPublicView:
    if source_variant not in {"related", "irrelevant"}:
        raise ValueError("source_variant must be related or irrelevant")
    # Public loading validates the ID and public files only; it never opens the
    # private scoring directory.
    from types import SimpleNamespace
    config_stub = SimpleNamespace(worlds_subdir=worlds_subdir, private_worlds_subdir="__not_loaded__", allowed_worlds=())
    assert_world_available(project_root, config_stub, world_id, require_private=False)
    root, _ = world_paths(project_root, config_stub, world_id)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    target_notes = (root / "target_notes.md").read_text(encoding="utf-8")
    source_file = root / ("source_related.md" if source_variant == "related" else "source_irrelevant.md")
    source_note = source_file.read_text(encoding="utf-8")
    menu = json.loads((root / "candidate_experiments.json").read_text(encoding="utf-8"))
    if str(manifest.get("world_id")) != str(world_id):
        raise ValueError(f"manifest world_id mismatch for {world_id}")
    if not isinstance(manifest.get("candidate_models"), list) or not manifest["candidate_models"]:
        raise ValueError(f"candidate_models missing for {world_id}")
    if not isinstance(menu, dict) or not isinstance(menu.get("experiments"), list):
        raise ValueError(f"candidate experiment menu missing for {world_id}")
    experiments = tuple(dict(item) for item in menu["experiments"])
    variable_schema = manifest.get("public_variable_schema") or {}
    source_variable_ids = tuple(str(item) for item in variable_schema.get("source", ("source_state", "source_time")))
    target_variable_ids = tuple(str(item) for item in variable_schema.get("target", ("target_state", "target_time")))
    if not source_variable_ids or not target_variable_ids:
        raise ValueError(f"public variable schema missing for {world_id}")
    view = WorldPublicView(
        world_id=str(manifest["world_id"]),
        target_domain=str(manifest["target_domain"]),
        source_domain=str(manifest["source_domain"]),
        target_notes=target_notes,
        source_note=source_note,
        candidate_models=tuple(manifest["candidate_models"]),
        experiments=experiments,
        measurement=str(menu["measurement"]),
        target_evidence_ids=_evidence_ids(target_notes, "T"),
        source_evidence_ids=_evidence_ids(source_note, "S"),
        source_variable_ids=source_variable_ids,
        target_variable_ids=target_variable_ids,
    )
    if not view.target_evidence_ids or not view.source_evidence_ids:
        raise ValueError(f"public evidence IDs missing for {world_id}")
    # The loader itself must not read private files. This explicit text check is
    # a cheap defense against accidentally embedding private labels in prompts.
    public_text = json.dumps(view.prompt_payload(), ensure_ascii=False)
    for marker in ("hidden_truth", "oracle_results", "true_law", "ig_star", "top1_score"):
        if marker in public_text:
            raise AssertionError(f"private marker leaked through public loader: {marker}")
    return view
