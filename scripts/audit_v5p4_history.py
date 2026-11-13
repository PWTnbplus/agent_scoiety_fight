from __future__ import annotations

"""Hash-only audit of V3/V4/V5 historical evidence and authorization files."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted((entry for entry in path.rglob("*") if entry.is_file()), key=lambda value: value.relative_to(path).as_posix()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(sha256(item).encode("ascii"))
    return digest.hexdigest()


def targets() -> list[Path]:
    paths = [
        ROOT / "runs" / "real_authorization_manifest.json",
        ROOT / "runs" / "v3_real_gate_state.json",
        ROOT / "runs" / "real_api_sessions",
        ROOT / "runs" / "v5_p1_real_w001_20261112_145649",
        ROOT / "V5_W001_REAL_RESULT_EVIDENCE.zip",
        ROOT / "real_v3_run_evidence.zip",
        ROOT / "v4_offline_preflight_evidence.zip",
        ROOT / "v5_offline_pre_gate_evidence.zip",
        ROOT / "reports" / "004_V5P3_OFFLINE_AND_AUTH_REQUEST.zip",
    ]
    return paths


def snapshot() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for path in targets():
        rel = path.relative_to(ROOT).as_posix()
        if not path.exists():
            result[rel] = {"status": "NOT_FOUND"}
        elif path.is_dir():
            result[rel] = {"status": "PRESENT", "kind": "directory", "sha256_tree": tree_hash(path), "file_count": sum(1 for item in path.rglob("*") if item.is_file())}
        else:
            result[rel] = {"status": "PRESENT", "kind": "file", "sha256": sha256(path), "bytes": path.stat().st_size}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    value = {"project_root": str(ROOT), "secret_policy": "hashes_and_metadata_only; no authorization contents or keys emitted", "targets": snapshot()}
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
