from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "003_V5P2_OFFLINE_DEVELOPMENT"
STAGE = REPORT / "package_stage"
ZIP_PATH = REPORT / "V5P2_OFFLINE_REPRO.zip"
OLD_RUN = ROOT / "runs" / "v5_p1_real_w001_20261112_145649"


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".env", "*.key"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and "__pycache__" not in item.parts):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    return digest.hexdigest()


def copy_old_evidence(target: Path) -> None:
    allowed = {"results.csv", "paired_deltas.csv", "manifest.json", "events.jsonl", "call_ledger.jsonl", "attempt_results.jsonl", "run_plan.jsonl", "config_frozen.json", "report.md"}
    target.mkdir(parents=True, exist_ok=True)
    for name in allowed:
        source = OLD_RUN / name
        if source.exists():
            shutil.copy2(source, target / name)
    artifacts_target = target / "agent_artifacts"
    if (OLD_RUN / "agent_artifacts").exists():
        copy_tree(OLD_RUN / "agent_artifacts", artifacts_target)


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    STAGE.mkdir(parents=True)
    for name in ("src", "tests", "scripts", "config"):
        copy_tree(ROOT / name, STAGE / name)
    shutil.copy2(ROOT / "pyproject.toml", STAGE / "pyproject.toml")
    shutil.copy2(ROOT / ".env.example", STAGE / ".env.example")
    (STAGE / "data").mkdir()
    copy_tree(ROOT / "data" / "worlds_v5p2_dev", STAGE / "data" / "worlds_v5p2_dev")
    copy_tree(ROOT / "data" / "worlds_v2_dev", STAGE / "data" / "worlds_v2_dev")
    (STAGE / "private").mkdir()
    copy_tree(ROOT / "private" / "worlds_v5p2_dev", STAGE / "private" / "worlds_v5p2_dev")
    copy_tree(ROOT / "private" / "worlds_v2_dev", STAGE / "private" / "worlds_v2_dev")
    (STAGE / "private_test_fixtures").mkdir()
    copy_tree(ROOT / "private" / "worlds_v5p2_dev", STAGE / "private_test_fixtures" / "worlds_v5p2_dev")
    package_reports = STAGE / "reports" / "003_V5P2_OFFLINE_DEVELOPMENT"
    package_reports.mkdir(parents=True)
    for source in REPORT.iterdir():
        if source.name in {"package_stage", "V5P2_OFFLINE_REPRO.zip"}:
            continue
        destination = package_reports / source.name
        if source.is_dir():
            copy_tree(source, destination)
        else:
            shutil.copy2(source, destination)
    shutil.copy2(REPORT / "package_README.md", STAGE / "README.md")
    shutil.copy2(REPORT / "REPRODUCE.ps1", STAGE / "REPRODUCE.ps1")
    copy_old_evidence(STAGE / "evidence" / "historical_v5p1_real_w001")

    hash_records = {
        "source_tree_hash": tree_hash(ROOT / "src"),
        "tests_tree_hash": tree_hash(ROOT / "tests"),
        "scripts_tree_hash": tree_hash(ROOT / "scripts"),
        "historical_v5p1_run_tree_hash": tree_hash(OLD_RUN),
        "historical_v5p1_zip_sha256": sha256_file(ROOT / "V5_W001_REAL_RESULT_EVIDENCE.zip"),
        "new_development_worlds_tree_hash": tree_hash(ROOT / "data" / "worlds_v5p2_dev"),
        "new_private_fixture_tree_hash": tree_hash(ROOT / "private" / "worlds_v5p2_dev"),
    }
    (package_reports / "HISTORICAL_HASHES.json").write_text(json.dumps(hash_records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (REPORT / "HISTORICAL_HASHES.json").write_text(json.dumps(hash_records, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = sorted(path for path in STAGE.rglob("*") if path.is_file())
    checksum_lines = [f"{sha256_file(path)}  {path.relative_to(STAGE).as_posix()}" for path in files]
    (STAGE / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    shutil.copy2(STAGE / "SHA256SUMS.txt", REPORT / "SHA256SUMS.txt")
    with ZipFile(ZIP_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(item for item in STAGE.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(STAGE).as_posix())
    print(f"built {ZIP_PATH} with {len(files) + 1} files")


if __name__ == "__main__":
    main()
