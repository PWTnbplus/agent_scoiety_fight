from __future__ import annotations

"""Preserve and repair the legacy V3 report path after a V5 runner leak."""

import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "018_V5P13_SCIENCE_DIAG_AND_FINAL"
TARGETS = ["G3_W001_FOUR_ARM_REPORT.md", "G3_W001_PAIRED_DELTAS.csv"]
KNOWN_ARCHIVE = ROOT / "reports" / "001_V5_P0_OFFLINE_PRECHECK" / "supporting_real_v3"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    capture = REPORT / "LEGACY_V3_OVERWRITE_CAPTURE"
    capture.mkdir(parents=True, exist_ok=True)
    records = []
    for name in TARGETS:
        target = ROOT / "reports" / "real_v3" / name
        source = KNOWN_ARCHIVE / name
        if not target.exists() or not source.exists():
            raise FileNotFoundError(name)
        preserved = capture / name
        shutil.copy2(target, preserved)
        shutil.copy2(source, target)
        records.append({"path": str(target), "overwritten_v5p13_capture": str(preserved), "restored_from_known_archive": str(source), "capture_sha256": digest(preserved), "restored_sha256": digest(target), "pre_v5p13_locked_sha256": next((row["sha256"] for row in json.loads((REPORT / "01_HISTORY_BEFORE_SHA256.json").read_text(encoding="utf-8"))["files"] if row["path"] == f"reports/real_v3/{name}"), None)})
    result = {"status": "RESTORED_KNOWN_ARCHIVE_PRELOCK_DIGEST_NOT_RECONSTRUCTABLE", "root_cause": "V5 real runner called the legacy V3 write_g3_report path; V5-P13 evidence itself remains under reports/018 and the new run/session logs.", "records": records, "historical_protection_check": "FAIL_PRELOCK_DIGEST_MISMATCH_REQUIRES_OPERATOR_REVIEW", "no_api_call": True}
    (REPORT / "19_LEGACY_V3_OVERWRITE_REMEDIATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
