from __future__ import annotations

import json
import re
from pathlib import Path

from .schema import WorldPublicView


EVIDENCE_RE = re.compile(r"\b([TS]\d{2})\b")


def _evidence_ids(text: str, prefix: str) -> tuple[str, ...]:
    return tuple(sorted({match.group(1) for match in EVIDENCE_RE.finditer(text) if match.group(1).startswith(prefix)}))


def load_world(project_root: str | Path, world_id: str, source_variant: str = "related") -> WorldPublicView:
    if source_variant not in {"related", "irrelevant"}:
        raise ValueError("source_variant must be related or irrelevant")
    root = Path(project_root) / "data" / "worlds" / world_id
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    target_notes = (root / "target_notes.md").read_text(encoding="utf-8")
    source_file = root / ("source_related.md" if source_variant == "related" else "source_irrelevant.md")
    source_note = source_file.read_text(encoding="utf-8")
    menu = json.loads((root / "candidate_experiments.json").read_text(encoding="utf-8"))
    experiments = tuple(dict(item) for item in menu["experiments"])
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
