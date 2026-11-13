from __future__ import annotations

"""Create the isolated, blinded V5-P4 offline validation worlds."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from generate_v5p3_cv_worlds import generate_worlds  # noqa: E402


def main() -> None:
    generate_worlds(
        ROOT / "data" / "worlds_v5p4_dev",
        ROOT / "private" / "worlds_v5p4_dev",
        namespace="v5p4",
    )


if __name__ == "__main__":
    main()
