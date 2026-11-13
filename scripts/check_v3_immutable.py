from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file() and "__pycache__" not in item.parts:
            digest.update(str(item.relative_to(path)).replace("\\", "/").encode("utf-8"))
            digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def main() -> None:
    expected = {}
    with (ROOT / "reports" / "v4_preflight" / "IMMUTABLE_INPUTS.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            expected[row["path"]] = row["sha256"]
    actual = {}
    for relative, old_hash in expected.items():
        path = ROOT / relative
        actual[relative] = tree_digest(path) if path.is_dir() else sha256_file(path)
    mismatches = [path for path, old_hash in expected.items() if actual[path] != old_hash]
    result = {"status": "PASS" if not mismatches else "FAIL", "mismatches": mismatches, "checked": len(expected), "old_files_modified": bool(mismatches)}
    destination = ROOT / "reports" / "v4_preflight" / "V3_IMMUTABLE_CHECK.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if mismatches:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
