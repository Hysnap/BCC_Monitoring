"""Compatibility wrapper for the unified dataset merger.

The real implementation now lives in `scripts/compile_unified_dataset_local.py`.
This wrapper keeps the old entrypoint working while ensuring the code path stays
local-only and single-sourced.
"""

from __future__ import annotations

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.compile_unified_dataset_local import merge_all_outputs  # noqa: E402


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Merge run outputs into a canonical master directory")
    parser.add_argument("--output-root", default="output", help="Root folder containing run outputs")
    parser.add_argument("--master-dir", default="output/current", help="Directory to write merged outputs into")
    args = parser.parse_args()
    manifest = merge_all_outputs(Path(args.output_root), Path(args.master_dir))
    print(json.dumps(manifest, indent=2))
