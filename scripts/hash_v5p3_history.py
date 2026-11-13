from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "004_V5P3_OFFLINE_AND_AUTH_REQUEST" / "HISTORY_HASHES_BEFORE.json"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    if path.is_file():
        return file_hash(path)
    digest = hashlib.sha256()
    for item in sorted((entry for entry in path.rglob("*") if entry.is_file()), key=lambda value: value.as_posix()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(file_hash(item).encode("ascii"))
    return digest.hexdigest()


def main() -> None:
    targets = [
        "runs/v5_p1_real_w001_20261112_145649",
        "runs/real_api_sessions",
        "data/worlds",
        "data/worlds_v2_dev",
        "private/worlds",
        "private/worlds_v2_dev",
        "reports/001_V5_P0_OFFLINE_PRECHECK",
        "reports/002_V5_P1_OFFLINE_RECHECK",
        "reports/003_V5P2_OFFLINE_DEVELOPMENT",
        "V5_W001_REAL_RESULT_EVIDENCE.zip",
        "v4_offline_preflight_evidence.zip",
        "v5_p0_pre_paid_evidence_final.zip",
    ]
    result = {target: tree_hash(ROOT / target) for target in targets}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
