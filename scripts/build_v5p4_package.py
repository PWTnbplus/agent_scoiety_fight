from __future__ import annotations

"""Build and smoke-test the self-contained V5-P4 evidence ZIP."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "005_V5P4_READY_FOR_AUTH"
STAGE = REPORT / "package_stage"
ZIP_PATH = REPORT / "005_V5P4_READY_FOR_AUTH.zip"
FRESH = ROOT / "work" / "v5p4_fresh_extract"


def ignore(_path: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {"__pycache__", ".pytest_cache", ".env"} or name.endswith((".pyc", ".key"))}


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(source, target, ignore=ignore)


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


def copy_source(target: Path) -> None:
    source_root = target / "FULL_REPRO_SOURCE"
    for name in ("src", "tests", "scripts", "config"):
        copy_tree(ROOT / name, source_root / name)
    for name in ("pyproject.toml", ".env.example", ".gitignore", "README.md"):
        shutil.copy2(ROOT / name, source_root / name)
    for name in ("worlds", "worlds_v2_dev", "worlds_v5p2_dev", "worlds_v5p3_dev", "worlds_v5p4_dev"):
        copy_tree(ROOT / "data" / name, source_root / "data" / name)
    for name in ("worlds", "worlds_v2_dev", "worlds_v5p2_dev", "worlds_v5p3_dev", "worlds_v5p4_dev"):
        copy_tree(ROOT / "private" / name, source_root / "private" / name)


def copy_report(target: Path) -> None:
    destination = target / "reports" / "005_V5P4_READY_FOR_AUTH"
    destination.mkdir(parents=True, exist_ok=True)
    for item in REPORT.iterdir():
        if item.name in {"package_stage", ZIP_PATH.name, "fresh_extraction"}:
            continue
        if item.is_dir():
            copy_tree(item, destination / item.name)
        else:
            shutil.copy2(item, destination / item.name)
    shutil.copy2(REPORT / "package_README.md", target / "README.md")
    shutil.copy2(REPORT / "REPRODUCE.ps1", target / "REPRODUCE.ps1")


def build_stage() -> list[Path]:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    STAGE.mkdir(parents=True)
    copy_source(STAGE)
    copy_report(STAGE)
    provenance = {
        "package": "005_V5P4_READY_FOR_AUTH",
        "source_tree_hash": tree_hash(ROOT / "src"),
        "tests_tree_hash": tree_hash(ROOT / "tests"),
        "scripts_tree_hash": tree_hash(ROOT / "scripts"),
        "v5p4_public_tree_hash": tree_hash(ROOT / "data" / "worlds_v5p4_dev"),
        "v5p4_private_tree_hash": tree_hash(ROOT / "private" / "worlds_v5p4_dev"),
        "historical_hash_comparison": json.loads((REPORT / "HISTORICAL_HASH_COMPARISON.json").read_text(encoding="utf-8"))["historical_paths_stable"],
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "real_api_calls_this_round": 0,
        "secret_policy": "no key files or secrets copied",
    }
    prior_provenance = REPORT / "PACKAGE_PROVENANCE.json"
    if prior_provenance.exists():
        try:
            provenance.update({key: value for key, value in json.loads(prior_provenance.read_text(encoding="utf-8")).items() if key in {"fresh_validation_exit_code"}})
        except json.JSONDecodeError:
            pass
    (STAGE / "reports" / "005_V5P4_READY_FOR_AUTH" / "PACKAGE_PROVENANCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = sorted(path for path in STAGE.rglob("*") if path.is_file())
    checksum = "\n".join(f"{sha256(path)}  {path.relative_to(STAGE).as_posix()}" for path in files) + "\n"
    (STAGE / "SHA256SUMS.txt").write_text(checksum, encoding="utf-8")
    with ZipFile(ZIP_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(item for item in STAGE.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(STAGE).as_posix())
    return files


def run_fresh_validation() -> tuple[int, str]:
    if FRESH.exists():
        shutil.rmtree(FRESH)
    FRESH.mkdir(parents=True)
    with ZipFile(ZIP_PATH) as archive:
        archive.extractall(FRESH)
    env = dict(__import__("os").environ)
    source_root = FRESH / "FULL_REPRO_SOURCE"
    env["PYTHONPATH"] = str(source_root / "src")
    commands = [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "mini_science.cli", "validate-worlds", "--config", "config/v5p4_offline_dev.json"],
    ]
    chunks: list[str] = []
    exit_code = 0
    for command in commands:
        result = subprocess.run(command, cwd=source_root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        chunks.append("$ " + " ".join(command) + "\nexit_code=" + str(result.returncode) + "\n" + result.stdout + result.stderr)
        exit_code = max(exit_code, result.returncode)
    return exit_code, "\n".join(chunks)


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    files = build_stage()
    exit_code, validation = run_fresh_validation()
    validation_doc = "# Fresh extraction validation\n\nThe following commands were run from a newly extracted `005_V5P4_READY_FOR_AUTH.zip`:\n\n```text\n" + validation + "```\n\n- API provider: not invoked\n- real_api_calls_this_round: 0\n"
    (REPORT / "FRESH_EXTRACTION_VALIDATION.md").write_text(validation_doc, encoding="utf-8")
    (REPORT / "PACKAGE_PROVENANCE.json").write_text(json.dumps({"fresh_validation_exit_code": exit_code, "authorization_status": "PROPOSED_NOT_AUTHORIZED", "real_api_calls_this_round": 0}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Include the validation document in the final archive.  The source and
    # tests are unchanged between the first and second build.
    files = build_stage()
    if exit_code != 0:
        raise SystemExit(exit_code)
    print(f"built {ZIP_PATH} with {len(files) + 1} files; fresh validation passed")


if __name__ == "__main__":
    main()
