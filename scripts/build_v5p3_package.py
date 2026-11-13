from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "004_V5P3_OFFLINE_AND_AUTH_REQUEST"
STAGE = REPORT / "package_stage"
ZIP_PATH = REPORT / "004_V5P3_OFFLINE_AND_AUTH_REQUEST.zip"
OLD_RUN = ROOT / "runs" / "v5_p1_real_w001_20261112_145649"


def ignore(path: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {"__pycache__", ".pytest_cache", ".env"} or name.endswith((".pyc", ".key"))}


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=ignore)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted((entry for entry in path.rglob("*") if entry.is_file()), key=lambda value: value.as_posix()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(sha256(item).encode("ascii"))
    return digest.hexdigest()


def copy_historical_evidence(target: Path) -> None:
    allowed = {"results.csv", "paired_deltas.csv", "manifest.json", "events.jsonl", "call_ledger.jsonl", "attempt_results.jsonl", "run_plan.jsonl", "config_frozen.json", "report.md"}
    target.mkdir(parents=True, exist_ok=True)
    for name in allowed:
        source = OLD_RUN / name
        if source.exists():
            shutil.copy2(source, target / name)
    if (OLD_RUN / "agent_artifacts").exists():
        copy_tree(OLD_RUN / "agent_artifacts", target / "agent_artifacts")


def copy_project_subset(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in ("src", "tests", "scripts", "config"):
        copy_tree(ROOT / name, target / name)
    for name in ("pyproject.toml", ".env.example"):
        shutil.copy2(ROOT / name, target / name)
    for name in ("worlds", "worlds_v2_dev", "worlds_v5p2_dev", "worlds_v5p3_dev"):
        source = ROOT / "data" / name
        if source.exists():
            copy_tree(source, target / "data" / name)
        source = ROOT / "private" / name
        if source.exists():
            copy_tree(source, target / "private" / name)


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    STAGE.mkdir(parents=True)
    copy_project_subset(STAGE)
    copy_project_subset(STAGE / "reproducible_src")
    copy_historical_evidence(STAGE / "evidence" / "historical_v5p1_real_w001")
    package_reports = STAGE / "reports" / "004_V5P3_OFFLINE_AND_AUTH_REQUEST"
    package_reports.mkdir(parents=True)
    for item in REPORT.iterdir():
        if item.name in {"package_stage", ZIP_PATH.name}:
            continue
        destination = package_reports / item.name
        if item.is_dir():
            copy_tree(item, destination)
        else:
            shutil.copy2(item, destination)
    shutil.copy2(REPORT / "package_README.md", STAGE / "README.md")
    shutil.copy2(REPORT / "REPRODUCE.ps1", STAGE / "REPRODUCE.ps1")

    provenance = {
        "source_tree_hash": tree_hash(ROOT / "src"),
        "tests_tree_hash": tree_hash(ROOT / "tests"),
        "scripts_tree_hash": tree_hash(ROOT / "scripts"),
        "cv_public_tree_hash": tree_hash(ROOT / "data" / "worlds_v5p3_dev"),
        "cv_private_tree_hash": tree_hash(ROOT / "private" / "worlds_v5p3_dev"),
        "historical_v5p1_run_tree_hash": tree_hash(OLD_RUN),
        "historical_evidence_zip_sha256": sha256(ROOT / "V5_W001_REAL_RESULT_EVIDENCE.zip"),
        "api_authorization_proposal_status": "PROPOSED_NOT_AUTHORIZED",
    }
    (STAGE / "reports" / "004_V5P3_OFFLINE_AND_AUTH_REQUEST" / "PACKAGE_PROVENANCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (REPORT / "PACKAGE_PROVENANCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = sorted(item for item in STAGE.rglob("*") if item.is_file())
    checksum = "\n".join(f"{sha256(item)}  {item.relative_to(STAGE).as_posix()}" for item in files) + "\n"
    (STAGE / "SHA256SUMS.txt").write_text(checksum, encoding="utf-8")
    (REPORT / "SHA256SUMS.txt").write_text(checksum, encoding="utf-8")
    with ZipFile(ZIP_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for item in sorted(path for path in STAGE.rglob("*") if path.is_file()):
            archive.write(item, item.relative_to(STAGE).as_posix())
    print(f"built {ZIP_PATH} with {len(files) + 1} files")


if __name__ == "__main__":
    main()
