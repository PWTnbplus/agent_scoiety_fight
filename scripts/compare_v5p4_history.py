from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "005_V5P4_READY_FOR_AUTH"


def main() -> None:
    before = json.loads((REPORT / "HISTORICAL_HASH_BEFORE.json").read_text(encoding="utf-8"))
    after = json.loads((REPORT / "HISTORICAL_HASH_AFTER.json").read_text(encoding="utf-8"))
    paths = sorted(set(before["targets"]) | set(after["targets"]))
    rows = []
    stable = True
    for path in paths:
        left = before["targets"].get(path, {})
        right = after["targets"].get(path, {})
        same = left == right
        stable = stable and same
        rows.append({"path": path, "before": left, "after": right, "stable": same})
    result = {"historical_paths_stable": stable, "secret_policy": "hashes_and_metadata_only", "comparisons": rows}
    (REPORT / "HISTORICAL_HASH_COMPARISON.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"historical_paths_stable": stable, "count": len(rows)}, ensure_ascii=False, sort_keys=True))
    if not stable:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
