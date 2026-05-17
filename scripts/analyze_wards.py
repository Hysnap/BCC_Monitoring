"""Analyze wards in DB and canonical CSVs.

Prints:
- number of wards in SQLite DB at output/data/monitoring.sqlite
- number of unique `ward_name` values in output/current/ward_summaries.csv
- normalized-name groups that map to multiple originals
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from collections import defaultdict
import re
import pandas as pd


DB_PATH = Path("output") / "data" / "monitoring.sqlite"
CSV_PATH = Path("output") / "current" / "ward_summaries.csv"


def normalize(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).lower().strip())


def main():
    print("WARD ANALYSIS REPORT")
    print("--------------------")

    if DB_PATH.exists():
        con = sqlite3.connect(str(DB_PATH))
        cur = con.cursor()
        # try wards table
        try:
            cur.execute("SELECT COUNT(*) FROM wards")
            ward_count = cur.fetchone()[0]
            print(f"Wards table rows: {ward_count}")
        except Exception as e:
            print(f"Could not read wards table: {e}")
        con.close()
    else:
        print(f"DB not found at {DB_PATH}")

    if CSV_PATH.exists():
        df = pd.read_csv(CSV_PATH)
        total_rows = len(df)
        unique_names = df["ward_name"].nunique()
        print(f"Ward rows in CSV: {total_rows}")
        print(f"Unique `ward_name` in CSV: {unique_names}")

        # normalized groups
        norm_map = defaultdict(list)
        for name in sorted(df["ward_name"].dropna().unique()):
            norm = normalize(name)
            norm_map[norm].append(name)

        dup_groups = {k: v for k, v in norm_map.items() if len(v) > 1}
        print(f"Normalized groups with multiple originals: {len(dup_groups)}")
        if dup_groups:
            print("\nNormalized name -> originals (count)")
            for norm, originals in sorted(dup_groups.items()):
                print(f"{norm} -> {originals} ({len(originals)})")
    else:
        print(f"CSV not found at {CSV_PATH}")


if __name__ == "__main__":
    main()
