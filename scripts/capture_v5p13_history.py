from __future__ import annotations

"""Capture immutable hashes for historical reports/runs before or after V5-P13."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def capture(root: Path, output: Path) -> dict[str, object]:
    report_root = root / "reports" / "018_V5P13_SCIENCE_DIAG_AND_FINAL"
    entries: list[dict[str, object]] = []
    for base in (root / "reports", root / "runs"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or report_root in path.parents or path == report_root:
                continue
            if base.name == "runs" and path.parts and any(part.startswith("real_v5p13") for part in path.parts):
                continue
            entries.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": digest(path)})
    value = {"schema_version": 1, "source_mutation": "NONE", "file_count": len(entries), "files": entries}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = capture(args.root.resolve(), args.output.resolve())
    print(json.dumps({"output": str(args.output.resolve()), "file_count": value["file_count"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
