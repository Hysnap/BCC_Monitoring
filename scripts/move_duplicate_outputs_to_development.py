"""Move duplicate output directories into output/development/archived.

This helper is idempotent and intended to be run once by maintainers to collect
old or duplicated run outputs (for example `output/councillors`) into a single
`output/development/archived/` area so future scripts target the canonical
`output/current` directory only.

Usage:
    python -m scripts.move_duplicate_outputs_to_development

Behavior:
- Finds directories directly under `output/` that contain a `councillors.csv` file
  (excluding `current` and `development`).
- Moves each such directory into `output/development/archived/<dirname>-<timestamp>`.
- Leaves files intact; prints actions taken.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "output"
DEVELOPMENT_DIR = OUTPUT_ROOT / "development" / "archived"
EXCLUDE = {"current", "development"}


def _ensure_dev_dir() -> None:
    DEVELOPMENT_DIR.mkdir(parents=True, exist_ok=True)


def _find_duplicate_dirs() -> list[Path]:
    result = []
    if not OUTPUT_ROOT.exists():
        return result
    for child in OUTPUT_ROOT.iterdir():
        if not child.is_dir():
            continue
        if child.name in EXCLUDE:
            continue
        if (child / "councillors.csv").exists():
            result.append(child)
    return result


def _move_dir(src: Path) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dest = DEVELOPMENT_DIR / f"{src.name}-{ts}"
    # If dest exists, append a numeric suffix
    i = 1
    base_dest = dest
    while dest.exists():
        dest = Path(str(base_dest) + f"-{i}")
        i += 1
    shutil.move(str(src), str(dest))
    return dest


def main() -> int:
    _ensure_dev_dir()
    duplicates = _find_duplicate_dirs()
    if not duplicates:
        print("No duplicate output dirs containing councillors.csv found.")
        return 0
    for src in duplicates:
        dest = _move_dir(src)
        print(f"Moved {src} -> {dest}")
    print("Done. Review output/development/archived for moved folders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
