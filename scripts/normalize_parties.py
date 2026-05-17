"""Detect and optionally normalize party name variants across CSVs and DB.

Run without `--apply` to preview changes. Use `--apply` to update CSVs and DB.
"""
from __future__ import annotations

import argparse
import sqlalchemy
import re
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.monitoring import database as db


CSV_FILES = [
    Path("output") / "current" / "party_history.csv",
    Path("output") / "current" / "election_standings.csv",
    Path("output") / "current" / "councillors.csv",
]


def canonicalize_label(raw: str) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    s0 = s.lower()
    # strip leading 'the '
    s0 = re.sub(r"^the\s+", "", s0)
    # remove trailing ' candidate' or ' (candidate)'
    s0 = re.sub(r"\s*\(candidate\)$", "", s0)
    s0 = re.sub(r"\s+candidate$", "", s0)
    s0 = s0.replace("-", " ")
    s0 = re.sub(r"\s+", " ", s0)

    # known mappings
    if "conservative" in s0:
        return "Conservative Party"
    if "labour" in s0:
        return "Labour Party"
    if "liberal democrat" in s0 or "liberal democrats" in s0 or "liberal" == s0:
        return "Liberal Democrats"
    if "green" in s0:
        return "Green Party"
    if "independent" in s0:
        return "Independent"
    # fallback: title case
    return s.title()


def gather_variants() -> Dict[str, List[str]]:
    variants = {}
    # from CSVs
    for p in CSV_FILES:
        if not p.exists():
            continue
        df = pd.read_csv(p)
        for col in [c for c in df.columns if "party" in c.lower()]:
            for val in df[col].dropna().unique():
                canon = canonicalize_label(val)
                variants.setdefault(canon, set()).add(str(val))

    # from DB parties
    engine = db.get_engine(None)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        rows = session.query(db.Party).all()
        for r in rows:
            canon = canonicalize_label(r.name)
            variants.setdefault(canon, set()).add(r.name)

    # convert sets to sorted lists
    return {k: sorted(list(v)) for k, v in variants.items()}


def preview():
    variants = gather_variants()
    print("Proposed canonical mappings (canonical -> variants):")
    for canon, vals in sorted(variants.items()):
        if len(vals) > 1:
            print(f"{canon} -> {vals}")
    return variants


def apply_changes(variants):
    # update CSVs in-place with backups
    import time
    for p in CSV_FILES:
        if not p.exists():
            continue
        df = pd.read_csv(p)
        for col in [c for c in df.columns if "party" in c.lower()]:
            df[col] = df[col].apply(lambda v: canonicalize_label(v) if pd.notna(v) else v)
        # write backup then overwrite; avoid clobbering existing backups
        backup = p.with_suffix(p.suffix + ".bak")
        if backup.exists():
            backup = p.with_suffix(p.suffix + f".bak.{int(time.time())}")
        p.rename(backup)
        df.to_csv(p, index=False)
        print(f"Updated CSV: {p} (backup at {backup})")

    # update DB parties: merge duplicates into canonical name safely
    engine = db.get_engine(None)
    from sqlalchemy.orm import Session
    from sqlalchemy import select, func

    with Session(engine) as session:
        # group existing parties by canonical name
        parties = session.query(db.Party).all()
        groups = {}
        for p in parties:
            canon = canonicalize_label(p.name)
            groups.setdefault(canon, []).append(p)

        for canon, parts in groups.items():
            if len(parts) == 1:
                # ensure canonical name
                p = parts[0]
                if p.name != canon:
                    # rename safely
                    p.name = canon
                    session.flush()
                continue

            # choose primary: prefer exact name match, else by usage count in person_events
            primary = None
            for p in parts:
                if p.name == canon:
                    primary = p
                    break
            if not primary:
                # choose by count of references
                counts = {}
                for p in parts:
                    cnt = session.query(func.count()).select_from(db.PersonEvent).filter(db.PersonEvent.party_id == p.id).scalar()
                    counts[p.id] = cnt
                primary_id = max(counts, key=counts.get)
                primary = next(p for p in parts if p.id == primary_id)

            # ensure primary has canonical name
            primary.name = canon
            session.flush()

            # reassign others to primary and delete
            for p in parts:
                if p.id == primary.id:
                    continue
                # reassign person_events
                session.execute(
                    sqlalchemy.text("UPDATE person_events SET party_id = :primary WHERE party_id = :old"),
                    {"primary": primary.id, "old": p.id},
                )
                session.delete(p)
            session.commit()
            print(f"Merged {len(parts)-1} parties into '{canon}' (id={primary.id})")

        print("DB party normalization applied.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Apply changes to CSVs and DB")
    args = p.parse_args()
    variants = preview()
    if args.apply:
        apply_changes(variants)


if __name__ == "__main__":
    main()
