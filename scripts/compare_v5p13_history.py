from __future__ import annotations

"""Capture post-run hashes and compare only paths present in the pre-run lock."""

import argparse
import json
from pathlib import Path

from capture_v5p13_history import capture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    report = root / "reports" / "018_V5P13_SCIENCE_DIAG_AND_FINAL"
    before = json.loads((report / "01_HISTORY_BEFORE_SHA256.json").read_text(encoding="utf-8"))
    after_path = report / "02_HISTORY_AFTER_SHA256.json"
    after = capture(root, after_path)
    before_map = {str(row["path"]): str(row["sha256"]) for row in before.get("files", [])}
    after_map = {str(row["path"]): str(row["sha256"]) for row in after.get("files", [])}
    changed = sorted(path for path, digest in before_map.items() if after_map.get(path) != digest)
    missing = sorted(path for path in before_map if path not in after_map)
    result = {"status": "PASS" if not changed and not missing else "FAIL", "before_file_count": len(before_map), "after_file_count": len(after_map), "changed_historical_paths": changed, "missing_historical_paths": missing, "new_paths_not_in_before": sorted(set(after_map) - set(before_map)), "source_mutation": "NONE" if not changed and not missing else "HISTORICAL_CHANGE_DETECTED"}
    (report / "03_HISTORY_IMMUTABILITY_CHECK.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
