from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.analysis_v5p11 import analyze_v5p11_run, write_not_run_analysis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "v5p11_main.json")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "015_V5P11_PROJECT_FINISH")
    parser.add_argument("--real-status", default="NOT_RUN")
    args = parser.parse_args()
    result = write_not_run_analysis(ROOT, args.config, args.output_dir) if args.run_dir is None else analyze_v5p11_run(ROOT, args.config, args.run_dir, args.output_dir, real_status=args.real_status)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
