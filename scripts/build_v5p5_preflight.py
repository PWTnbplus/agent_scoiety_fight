from __future__ import annotations

"""Build and freshly validate the V5-P5 offline preflight evidence package.

The builder never copies key files, .env files, runs, or raw credentials.  It
copies the public source plus the private fixtures required by the offline
scorer, then runs tests from a newly extracted archive before the final ZIP is
delivered.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "006_V5P5_PREFLIGHT_AND_AUTH_REQUEST"
STAGE = REPORT / "package_stage"
ZIP_PATH = REPORT / "006_V5P5_PREFLIGHT_AND_AUTH_REQUEST.zip"
FRESH = ROOT / "work" / "v5p5_fresh_extract"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return "MISSING"
    for item in sorted((entry for entry in path.rglob("*") if entry.is_file()), key=lambda value: value.relative_to(path).as_posix()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(sha256(item).encode("ascii"))
    return digest.hexdigest()


def ignore(_path: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".pytest_cache", ".env", ".git", "runs", "package_stage", "fresh_extraction"}
    return {name for name in names if name in ignored or name.endswith((".pyc", ".key"))}


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=ignore)


def copy_source(target: Path) -> None:
    source_root = target / "FULL_REPRO_SOURCE"
    for name in ("src", "tests", "scripts", "config"):
        copy_tree(ROOT / name, source_root / name)
    for name in ("pyproject.toml", ".env.example", ".gitignore", "README.md"):
        shutil.copy2(ROOT / name, source_root / name)
    copy_tree(ROOT / "docs", source_root / "docs")
    for name in ("worlds", "worlds_v2_dev", "worlds_v5p2_dev", "worlds_v5p3_dev", "worlds_v5p4_dev"):
        copy_tree(ROOT / "data" / name, source_root / "data" / name)
    for name in ("worlds", "worlds_v2_dev", "worlds_v5p2_dev", "worlds_v5p3_dev", "worlds_v5p4_dev"):
        copy_tree(ROOT / "private" / name, source_root / "private" / name)


def copy_report(target: Path) -> None:
    destination = target / "reports" / REPORT.name
    destination.mkdir(parents=True, exist_ok=True)
    for item in REPORT.iterdir():
        if item.name in {"package_stage", ZIP_PATH.name, "fresh_extraction", "006_V5P5_PREFLIGHT_AND_AUTH_REQUEST.zip", "ZIP_SHA256.txt", "PACKAGE_FINAL_MANIFEST.json"}:
            continue
        if item.is_dir():
            copy_tree(item, destination / item.name)
        else:
            shutil.copy2(item, destination / item.name)
    package_readme = REPORT / "package_README.md"
    if package_readme.exists():
        shutil.copy2(package_readme, target / "README.md")
    reproduce = REPORT / "REPRODUCE.ps1"
    if reproduce.exists():
        shutil.copy2(reproduce, target / "REPRODUCE.ps1")


def secret_scan(root: Path) -> list[str]:
    findings: list[str] = []
    forbidden_names = {".env", ".key"}
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        if item.name in forbidden_names or item.suffix == ".key":
            findings.append(f"secret_filename:{item.relative_to(root).as_posix()}")
            continue
        try:
            text = item.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lowered = text.lower()
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
    provenance = {
        "package": "006_V5P5_PREFLIGHT_AND_AUTH_REQUEST",
        "source_tree_hash": tree_hash(ROOT / "src"),
        "tests_tree_hash": tree_hash(ROOT / "tests"),
        "scripts_tree_hash": tree_hash(ROOT / "scripts"),
        "config_tree_hash": tree_hash(ROOT / "config"),
        "docs_tree_hash": tree_hash(ROOT / "docs"),
        "v5p4_public_tree_hash": tree_hash(ROOT / "data" / "worlds_v5p4_dev"),
        "v5p4_private_tree_hash": tree_hash(ROOT / "private" / "worlds_v5p4_dev"),
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "real_api_calls_this_round": 0,
        "network_requests_this_round": 0,
        "secret_policy": "no key files, .env files, bearer values, or raw credentials copied",
    }
    destination = STAGE / "reports" / REPORT.name
    (destination / "PACKAGE_PROVENANCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = sorted(path for path in STAGE.rglob("*") if path.is_file())
    checksum = "\n".join(f"{sha256(path)}  {path.relative_to(STAGE).as_posix()}" for path in files) + "\n"
    (STAGE / "SHA256SUMS.txt").write_text(checksum, encoding="utf-8")
    findings = secret_scan(STAGE)
    (destination / "PACKAGE_SECRET_SCAN.json").write_text(json.dumps({"passed": not findings, "findings": findings}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if findings:
        raise RuntimeError("package secret scan failed: " + ", ".join(findings))
    files = sorted(path for path in STAGE.rglob("*") if path.is_file())
    with ZipFile(ZIP_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(STAGE).as_posix())
    return files


def run_fresh_validation() -> tuple[int, str]:
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
        [sys.executable, "scripts/audit_v5p4_prompts.py", "--output", "reports/006_V5P5_PREFLIGHT_AND_AUTH_REQUEST/fresh_prompt_blinding_audit.csv"],
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
    exit_code, validation = run_fresh_validation()
    validation_doc = "# Fresh extraction validation\n\nThe following commands were run from a newly extracted `006_V5P5_PREFLIGHT_AND_AUTH_REQUEST.zip`. No provider adapter or HTTP request was enabled.\n\n```text\n" + validation + "\n```\n\n- authorization_status: PROPOSED_NOT_AUTHORIZED\n- real_api_calls_this_round: 0\n- network_requests_this_round: 0\n"
    (REPORT / "FRESH_EXTRACTION_VALIDATION.md").write_text(validation_doc, encoding="utf-8")
    # Rebuild so the final archive contains the validation document and the
    # exact source/test tree that was just exercised.
    files = build_stage()
    if exit_code != 0:
        raise SystemExit(exit_code)
    zip_digest = sha256(ZIP_PATH)
    (REPORT / "ZIP_SHA256.txt").write_text(zip_digest + "  " + ZIP_PATH.name + "\n", encoding="utf-8")
    manifest = {
        "package": "006_V5P5_PREFLIGHT_AND_AUTH_REQUEST",
        "zip": ZIP_PATH.name,
        "zip_sha256": zip_digest,
        "member_count": len(files),
        "fresh_validation_exit_code": exit_code,
        "authorization_status": "PROPOSED_NOT_AUTHORIZED",
        "real_api_calls_this_round": 0,
        "network_requests_this_round": 0,
    }
    (REPORT / "PACKAGE_FINAL_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
