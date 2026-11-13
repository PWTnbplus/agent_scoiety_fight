from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "v4_preflight"


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


def git_status() -> str:
    try:
        return subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=False).stdout
    except OSError:
        return "git unavailable"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    old_paths = [
        ROOT / "runs" / "v3_real_gate_state.json",
        ROOT / "runs" / "real_authorization_manifest.json",
        ROOT / "reports" / "real_v3",
    ]
    old_paths.extend(sorted((ROOT / "runs").glob("real_kimi26_g1_*")))
    old_paths.extend(sorted((ROOT / "runs").glob("real_kimi26_probe_*")))
    old_paths.append(ROOT / "runs" / "real_kimi26_w001_v3_01")
    records: list[dict[str, str | int]] = []
    for path in old_paths:
        if not path.exists():
            continue
        if path.is_file():
            records.append({"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "kind": "file", "size": path.stat().st_size})
        else:
            records.append({"path": str(path.relative_to(ROOT)), "sha256": tree_digest(path), "kind": "tree", "size": sum(item.stat().st_size for item in path.rglob("*") if item.is_file())})
    immutable = OUT / "IMMUTABLE_INPUTS.csv"
    with immutable.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "kind", "size", "sha256"])
        writer.writeheader()
        writer.writerows(records)
    private_hashes = {}
    for world in sorted((ROOT / "private" / "worlds_v2_dev").glob("W*")):
        truth = world / "hidden_truth.json"
        oracle = world / "oracle_results.json"
        private_hashes[world.name] = {
            "hidden_truth_sha256": sha256_file(truth) if truth.exists() else None,
            "oracle_results_sha256": sha256_file(oracle) if oracle.exists() else None,
        }
    audit = {
        "audit_version": "v4-preflight-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(ROOT),
        "historical_v3_status": "READ_ONLY",
        "historical_real_request_count": 6,
        "historical_request_ids": [
            item.get("request_id") for item in json.loads((ROOT / "runs" / "v3_real_gate_state.json").read_text(encoding="utf-8")).get("attempts", [])
        ],
        "source_tree_sha256": tree_digest(ROOT / "src"),
        "tests_tree_sha256": tree_digest(ROOT / "tests"),
        "config_hashes": {path.name: sha256_file(path) for path in sorted((ROOT / "config").glob("*.json"))},
        "public_world_hashes": {world.name: tree_digest(world) for world in sorted((ROOT / "data" / "worlds_v2_dev").glob("W*"))},
        "private_oracle_hashes_only": private_hashes,
        "immutable_inputs_csv": str(immutable.relative_to(ROOT)),
        "git_status_at_freeze": git_status(),
        "safety": {"api_key_included": False, "private_values_included": False, "real_api_called_by_this_script": False},
    }
    (OUT / "V3_FROZEN_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"audit": str(OUT / "V3_FROZEN_AUDIT.json"), "immutable": str(immutable), "source_tree_sha256": audit["source_tree_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
