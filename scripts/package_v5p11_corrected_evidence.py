from __future__ import annotations

import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "016_V5P11_REAL_20261113T072222Z"
RUN = ROOT / "runs" / "real_v5p11_IV001_IV004_20261113T072222Z"
SESSION = ROOT / "runs" / "real_api_sessions" / "v5p11_20261113T072254Z_4QaXzSJmGYKikoua"
DEST = REPORT / "RESTRICTED_REAL_EVIDENCE_POSTRUN_CORRECTED.zip"
ALLOW_EXT = {".jsonl", ".json", ".csv", ".md", ".txt", ".log"}


def add_tree(archive: zipfile.ZipFile, source_root: Path, prefix: str) -> None:
    for file in sorted(source_root.rglob("*")):
        if not file.is_file() or file.suffix.lower() not in ALLOW_EXT or file == DEST:
            continue
        rel_parts = {part.lower() for part in file.relative_to(source_root).parts}
        if rel_parts & {"__pycache__", "api_key", ".env", ".git"} or any("secret" in part or "password" in part for part in rel_parts):
            continue
        if file.stat().st_size > 20_000_000:
            continue
        content = file.read_bytes()
        if re.search(rb"authorization\s*[:=]\s*[\"']?bearer\s+", content, flags=re.I):
            raise RuntimeError(f"credential-bearing log refused: {file}")
        archive.writestr(f"{prefix}/{file.relative_to(source_root).as_posix()}", content)


def main() -> None:
    with zipfile.ZipFile(DEST, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as archive:
        add_tree(archive, RUN, "run")
        add_tree(archive, REPORT, "report")
        for name in ("attempt_ledger.jsonl", "planned_requests.jsonl", "gate_state.json"):
            path = SESSION / name
            if path.is_file():
                archive.write(path, f"session/{name}")
    print(DEST)
    print(__import__("hashlib").sha256(DEST.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
