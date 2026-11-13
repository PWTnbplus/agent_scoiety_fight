from __future__ import annotations

"""Build and freshly validate the V5-P6 zero-cost evidence package."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

from mini_science.stable_fingerprint import stable_tree_hash


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "008_V5P6_HASH_FIX_AND_NEW_PROPOSAL"
STAGE = REPORT / "package_stage"
ZIP_PATH = REPORT / "008_V5P6_HASH_FIX_AND_AUTH_REQUEST.zip"
FRESH = ROOT / "work" / "v5p6_fresh_extract"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ignore(_path: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".env", ".git", "runs", "package_stage", "fresh_extraction"}
    return {name for name in names if name in ignored or name.endswith((".pyc", ".pyo", ".key"))}


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=ignore)


def copy_source(target: Path) -> None:
    source_root = target / "FULL_REPRO_SOURCE"
    for name in ("src", "tests", "scripts", "config"):
        copy_tree(ROOT / name, source_root / name)
    for name in ("pyproject.toml", ".env.example", ".gitignore", "README.md", "AGENTS.md"):
        shutil.copy2(ROOT / name, source_root / name)
    copy_tree(ROOT / "docs", source_root / "docs")
    for name in ("worlds", "worlds_v2_dev", "worlds_v5p2_dev", "worlds_v5p3_dev", "worlds_v5p4_dev"):
        copy_tree(ROOT / "data" / name, source_root / "data" / name)
    for name in ("worlds", "worlds_v2_dev", "worlds_v5p2_dev", "worlds_v5p3_dev", "worlds_v5p4_dev"):
        copy_tree(ROOT / "private" / name, source_root / "private" / name)


def copy_report(target: Path) -> None:
    destination = target / "reports" / REPORT.name
    destination.mkdir(parents=True, exist_ok=True)
    excluded = {"package_stage", ZIP_PATH.name, "fresh_extraction", "ZIP_SHA256.txt", "PACKAGE_FINAL_MANIFEST.json"}
    for item in REPORT.iterdir():
        if item.name in excluded:
            continue
        if item.is_dir():
            copy_tree(item, destination / item.name)
        else:
            shutil.copy2(item, destination / item.name)
    if (REPORT / "package_README.md").exists():
        shutil.copy2(REPORT / "package_README.md", target / "README.md")
    if (REPORT / "REPRODUCE.ps1").exists():
        shutil.copy2(REPORT / "REPRODUCE.ps1", target / "REPRODUCE.ps1")


def secret_scan(root: Path) -> list[str]:
    findings: list[str] = []
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        if item.name == ".env" or item.suffix == ".key":
            findings.append(f"secret_filename:{item.relative_to(root).as_posix()}")
            continue
        try:
            text = item.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(r"authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{20,}", text, re.IGNORECASE):
            findings.append(f"bearer_value:{item.relative_to(root).as_posix()}")
        if re.search(r"\bsk-[A-Za-z0-9]{20,}\b", text):
            findings.append(f"openai_like_key:{item.relative_to(root).as_posix()}")
    return findings


def build_stage() -> list[Path]:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    STAGE.mkdir(parents=True)
    copy_source(STAGE)
    copy_report(STAGE)
    proposal = json.loads((REPORT / "API_AUTHORIZATION_PROPOSAL.json").read_text(encoding="utf-8"))
    provenance = {
        "package": "008_V5P6_HASH_FIX_AND_AUTH_REQUEST",
        "source_tree_hash": stable_tree_hash(ROOT / "src"),
        "tests_tree_hash": stable_tree_hash(ROOT / "tests"),
        "scripts_tree_hash": stable_tree_hash(ROOT / "scripts"),
        "config_tree_hash": stable_tree_hash(ROOT / "config"),
        "docs_tree_hash": stable_tree_hash(ROOT / "docs"),
        "public_world_tree_hash": stable_tree_hash(ROOT / "data" / "worlds_v5p4_dev"),
        "private_fixture_tree_hash": stable_tree_hash(ROOT / "private" / "worlds_v5p4_dev"),
        "proposal_sha256": proposal["proposal_sha256"],
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "real_api_calls_this_round": 0,
        "network_requests_this_round": 0,
        "secret_policy": "no key files, .env files, bearer values, or raw credentials copied",
    }
    destination = STAGE / "reports" / REPORT.name
    (destination / "PACKAGE_PROVENANCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    findings = secret_scan(STAGE)
    (destination / "PACKAGE_SECRET_SCAN.json").write_text(json.dumps({"passed": not findings, "findings": findings}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if findings:
        raise RuntimeError("package secret scan failed: " + ", ".join(findings))
    files = sorted(path for path in STAGE.rglob("*") if path.is_file())
    (STAGE / "SHA256SUMS.txt").write_text("\n".join(f"{sha256(path)}  {path.relative_to(STAGE).as_posix()}" for path in files) + "\n", encoding="utf-8")
    with ZipFile(ZIP_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(item for item in STAGE.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(STAGE).as_posix())
    return files


def fresh_validate() -> tuple[int, str]:
    if FRESH.exists():
        shutil.rmtree(FRESH)
    FRESH.mkdir(parents=True)
    with ZipFile(ZIP_PATH) as archive:
        archive.extractall(FRESH)
    source_root = FRESH / "FULL_REPRO_SOURCE"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(source_root / "src")
    commands = [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "mini_science.cli", "validate-worlds", "--config", "config/v5p4_offline_dev.json"],
        [sys.executable, "scripts/audit_v5p4_prompts.py", "--output", "reports/008_V5P6_HASH_FIX_AND_NEW_PROPOSAL/fresh_prompt_blinding.csv"],
    ]
    chunks: list[str] = []
    exit_code = 0
    for command in commands:
        result = subprocess.run(command, cwd=source_root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        chunks.append("$ " + " ".join(command) + "\nexit_code=" + str(result.returncode) + "\n" + result.stdout + result.stderr)
        exit_code = max(exit_code, result.returncode)
    findings = secret_scan(FRESH)
    chunks.append("secret_scan_exit_code=" + ("0" if not findings else "1") + "\n" + json.dumps(findings, ensure_ascii=False))
    if findings:
        exit_code = max(exit_code, 1)
    return exit_code, "\n".join(chunks)


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    files = build_stage()
    exit_code, validation = fresh_validate()
    (REPORT / "FRESH_EXTRACTION_VALIDATION.md").write_text("# Fresh extraction validation\n\n```text\n" + validation + "\n```\n\n- real_api_calls_this_round: 0\n- network_requests_this_round: 0\n", encoding="utf-8")
    placeholder = {"package": "008_V5P6_HASH_FIX_AND_AUTH_REQUEST", "zip": ZIP_PATH.name, "zip_sha256": "see ZIP_SHA256.txt", "member_count": len(files), "fresh_validation_exit_code": exit_code, "authorization_status": "PROPOSED_NOT_AUTHORIZED", "real_api_calls_this_round": 0}
    (REPORT / "PACKAGE_FINAL_MANIFEST.json").write_text(json.dumps(placeholder, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    build_stage()
    if exit_code != 0:
        raise SystemExit(exit_code)
    digest = sha256(ZIP_PATH)
    final = dict(placeholder, zip_sha256=digest, member_count=len([item for item in ZipFile(ZIP_PATH).namelist() if not item.endswith("/")]))
    (REPORT / "ZIP_SHA256.txt").write_text(digest + "  " + ZIP_PATH.name + "\n", encoding="utf-8")
    (REPORT / "PACKAGE_FINAL_MANIFEST.json").write_text(json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(final, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
