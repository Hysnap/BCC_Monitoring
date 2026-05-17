"""Initialize the SQLite relational schema and seed baseline reference data.

Usage:
    python scripts/init_database.py
    python scripts/init_database.py --db-path output/data/monitoring.db
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.monitoring.database import (  # noqa: E402
    create_schema,
    seed_reference_data,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize monitoring SQLite schema"
    )
    parser.add_argument(
        "--db-path",
        default="output/data/monitoring.sqlite",
        help="SQLite file path",
    )
    args = parser.parse_args()

    create_schema(args.db_path)
    seed_reference_data(args.db_path)
    print(f"Initialized database at: {args.db_path}")


if __name__ == "__main__":
    main()
