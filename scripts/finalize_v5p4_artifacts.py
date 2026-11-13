from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "005_V5P4_READY_FOR_AUTH"
ZIP_PATH = REPORT / "005_V5P4_READY_FOR_AUTH.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    with ZipFile(ZIP_PATH) as archive:
        names = sorted(item.filename for item in archive.infolist())
        forbidden_files = [name for name in names if name.lower().endswith((".key", ".pem", ".p12", ".pfx")) or name.lower().endswith("/.env") or name.lower() == ".env"]
        suspicious: list[str] = []
        for item in archive.infolist():
            if item.is_dir():
                continue
            text = archive.read(item).decode("utf-8", errors="ignore")
            if re.search(r"(?i)sk-[A-Za-z0-9]{24,}", text):
                suspicious.append(item.filename + "::key-like-token")
            if re.search(r"(?i)Bearer\s+[A-Za-z0-9+/=_-]{32,}", text):
                suspicious.append(item.filename + "::bearer-like-token")
    proposal = json.loads((REPORT / "API_AUTHORIZATION_PROPOSAL.json").read_text(encoding="utf-8"))
    result = {
        "zip_path": str(ZIP_PATH),
        "zip_sha256": sha256(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_file_count": len(names),
        "forbidden_key_files": forbidden_files,
        "suspicious_secret_matches": suspicious,
        "secret_scan_status": "PASS" if not forbidden_files and not suspicious else "FAIL",
        "authorization_status": proposal.get("authorization_status"),
        "real_api_calls_this_round": proposal.get("real_api_calls_this_round"),
        "historical_hashes_stable": json.loads((REPORT / "HISTORICAL_HASH_COMPARISON.json").read_text(encoding="utf-8")).get("historical_paths_stable"),
        "fresh_extraction_validation": "PASS" if "97 passed" in (REPORT / "FRESH_EXTRACTION_VALIDATION.md").read_text(encoding="utf-8") else "UNVERIFIED",
    }
    (REPORT / "FINAL_PACKAGE_MANIFEST.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (REPORT / "FINAL_PACKAGE_SHA256.txt").write_text(result["zip_sha256"] + "  005_V5P4_READY_FOR_AUTH.zip\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["secret_scan_status"] != "PASS" or result["authorization_status"] != "PROPOSED_NOT_AUTHORIZED" or result["real_api_calls_this_round"] != 0 or result["historical_hashes_stable"] is not True:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
