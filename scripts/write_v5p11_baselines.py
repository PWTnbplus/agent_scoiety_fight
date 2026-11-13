from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mini_science.analysis import write_baselines_by_world, write_cheap_baselines, write_oracle_audit
from mini_science.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "v5p11_main.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "015_V5P11_PROJECT_FINISH" / "BASELINES.csv")
    args = parser.parse_args()
    config = load_config(args.config)
    write_baselines_by_world(ROOT, config, args.output, random_seed=config.plan_seed)
    write_cheap_baselines(ROOT, config, args.output.parent / "cheap_baselines.csv")
    write_oracle_audit(ROOT, config, args.output.parent / "oracle_action_information_gain.csv")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
