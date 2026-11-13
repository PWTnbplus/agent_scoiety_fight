from __future__ import annotations

"""Record source-tree drift after the already-authorized API session."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "018_V5P13_SCIENCE_DIAG_AND_FINAL"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.stable_fingerprint import stable_tree_hash


def main() -> int:
    proposal = json.loads((REPORT / "10_V5P13_NEW_FROZEN_PROPOSAL.json").read_text(encoding="utf-8"))
    config = json.loads((ROOT / "config" / "v5p11_main.json").read_text(encoding="utf-8"))
    trees = {
        "source_tree_hash": ROOT / "src",
        "tests_tree_hash": ROOT / "tests",
        "scripts_tree_hash": ROOT / "scripts",
        "public_world_tree_hash": ROOT / "data" / config["worlds_subdir"],
        "private_fixture_tree_hash": ROOT / "private" / config["private_worlds_subdir"],
        "docs_tree_hash": ROOT / "docs",
    }
    current = {field: stable_tree_hash(path) for field, path in trees.items()}
    changed = {field: {"frozen": proposal.get(field), "current": current[field]} for field in trees if proposal.get(field) != current[field]}
    value = {
        "status": "POST_RUN_ANALYSIS_ONLY_CHANGES_RECORDED" if changed else "NO_POST_RUN_TREE_DRIFT",
        "api_session_already_closed": True,
        "new_api_calls": 0,
        "proposal_sha256": proposal.get("proposal_sha256"),
        "frozen_tree_hashes": {field: proposal.get(field) for field in trees},
        "current_tree_hashes": current,
        "changed_trees": changed,
        "interpretation": "Any listed drift was introduced after the V5-P13 API stop for diagnostics, remediation, tests, or packaging; it was not used to authorize or issue another provider request.",
    }
    (REPORT / "20_POST_RUN_SOURCE_CHANGE_AUDIT.json").write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
