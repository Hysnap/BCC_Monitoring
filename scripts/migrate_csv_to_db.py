"""Migrate canonical CSVs in `output/current/` into the relational DB.

Run with `--dry-run` to preview changes (doesn't write to DB).
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pandas as pd

from src.monitoring import database as db


def _to_date(val):
    """Convert a value to a Python date or return None."""
    if val is None:
        return None
    # handle pandas NA/NaT
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    try:
        import pandas as _pd

        if isinstance(val, _pd.Timestamp):
            return val.date()
    except Exception:
        pass
    # try generic conversion
    try:
        from datetime import datetime

        if isinstance(val, str) and val.strip() == "":
            return None
        if isinstance(val, datetime):
            return val.date()
        dt = pd.to_datetime(val)
        try:
            if pd.isna(dt):
                return None
        except Exception:
            pass
        return dt.date()
    except Exception:
        return None


def get_council(session):
    council = session.query(db.Council).filter(db.Council.code == "birmingham").first()
    if not council:
        council = db.Council(code="birmingham", name="Birmingham City Council")
        session.add(council)
        session.flush()
    return council


def get_or_create_person(session, council_id: int, person_uid: str, canonical_name: str, source_url: Optional[str]):
    p = (
        session.query(db.Person)
        .filter(db.Person.council_id == council_id)
        .filter(db.Person.person_uid == person_uid)
        .first()
    )
    if p:
        return p, False
    p = db.Person(council_id=council_id, person_uid=person_uid, canonical_name=canonical_name, source_url=source_url)
    session.add(p)
    session.flush()
    return p, True


def get_or_create_party(session, council_id: int, name: str, source_url: Optional[str]):
    if not name or pd.isna(name):
        return None, False
    q = session.query(db.Party).filter(db.Party.council_id == council_id).filter(db.Party.name == name)
    p = q.first()
    if p:
        return p, False
    p = db.Party(council_id=council_id, name=name, source_url=source_url)
    session.add(p)
    session.flush()
    return p, True


def get_or_create_ward(session, council_id: int, name: str, valid_from: Optional[str], source_url: Optional[str]):
    if not name or pd.isna(name):
        return None, False
    q = session.query(db.Ward).filter(db.Ward.council_id == council_id).filter(db.Ward.name == name)
    w = q.first()
    if w:
        return w, False
    w = db.Ward(council_id=council_id, name=name, valid_from=valid_from, source_url=source_url)
    session.add(w)
    session.flush()
    return w, True


def ensure_event_type(session, code: str):
    ev = session.query(db.EventType).filter(db.EventType.code == code).first()
    if ev:
        return ev
    ev = db.EventType(code=code, name=code)
    session.add(ev)
    session.flush()
    return ev


def migrate(args):
    engine = db.get_engine(args.db)
    from sqlalchemy.orm import Session

    people_csv = Path("output") / "current" / "people.csv"
    party_csv = Path("output") / "current" / "party_history.csv"
    standings_csv = Path("output") / "current" / "election_standings.csv"
    wards_csv = Path("output") / "current" / "ward_summaries.csv"
    councillors_csv = Path("output") / "current" / "councillors.csv"

    stats = {"people_created": 0, "parties_created": 0, "wards_created": 0, "events_created": 0, "events_elected": 0}

    with Session(engine) as session:
        council = get_council(session)

        # ensure baseline event types exist
        for code in ("election_candidate", "elected_councillor", "related_party", "council_post_held"):
            ensure_event_type(session, code)

        # people
        if people_csv.exists():
            df = pd.read_csv(people_csv)
            for _, r in df.iterrows():
                person_uid = str(r.person_id)
                name = r.person_name
                src = r.get("source_url") if "source_url" in r else None
                _, created = get_or_create_person(session, council.id, person_uid, name, src)
                if created:
                    stats["people_created"] += 1

        # parties from party_history -> create parties and related_party events
        if party_csv.exists():
            df = pd.read_csv(party_csv)
            for _, r in df.iterrows():
                pid = str(r.person_id)
                party_name = r.party_name
                src = r.get("source_url") if "source_url" in r else None
                party_obj, created = get_or_create_party(session, council.id, party_name, src)
                if created:
                    stats["parties_created"] += 1
                # attach person event
                person = session.query(db.Person).filter(db.Person.council_id == council.id).filter(db.Person.person_uid == pid).first()
                if person:
                    evt = session.query(db.EventType).filter(db.EventType.code == "related_party").first()
                    party_id = int(party_obj.id) if party_obj and party_obj.id is not None else None
                    event_type_id = int(evt.id) if evt and evt.id is not None else None
                    pe = db.PersonEvent(
                        council_id=int(council.id),
                        person_id=int(person.id),
                        event_type_id=event_type_id,
                        party_id=party_id,
                        effective_from=_to_date(r.get("effective_from") if "effective_from" in r else None),
                        effective_to=_to_date(r.get("effective_to") if "effective_to" in r else None),
                        source_url=src,
                    )
                    session.add(pe)
                    stats["events_created"] += 1

        # wards
        if wards_csv.exists():
            df = pd.read_csv(wards_csv)
            for _, r in df.iterrows():
                ward_name = r.ward_name
                src = r.get("source_url") if "source_url" in r else None
                _, created = get_or_create_ward(session, council.id, ward_name, _to_date(r.get("election_date")), src)
                if created:
                    stats["wards_created"] += 1

        # election standings -> candidate events and elected events
        if standings_csv.exists():
            df = pd.read_csv(standings_csv)
            for _, r in df.iterrows():
                pid = str(r.person_id) if not pd.isna(r.person_id) else None
                if pid is None:
                    continue
                person = session.query(db.Person).filter(db.Person.council_id == council.id).filter(db.Person.person_uid == pid).first()
                # ensure party exists
                party_obj = None
                if "party_name" in r and not pd.isna(r.party_name):
                    party_obj, _ = get_or_create_party(session, council.id, r.party_name, r.get("source_url") if "source_url" in r else None)
                ward_obj = None
                if "ward_name" in r and not pd.isna(r.ward_name):
                    ward_obj = session.query(db.Ward).filter(db.Ward.council_id == council.id).filter(db.Ward.name == r.ward_name).first()
                if person:
                    evt_candidate = session.query(db.EventType).filter(db.EventType.code == "election_candidate").first()
                    party_id = int(party_obj.id) if party_obj and party_obj.id is not None else None
                    ward_id = int(ward_obj.id) if ward_obj and ward_obj.id is not None else None
                    event_type_id = int(evt_candidate.id) if evt_candidate and evt_candidate.id is not None else None
                    pe = db.PersonEvent(
                        council_id=int(council.id),
                        person_id=int(person.id),
                        event_type_id=event_type_id,
                        party_id=party_id,
                        ward_id=ward_id,
                        event_value=str(r.get("votes_received")) if "votes_received" in r else None,
                        source_url=r.get("source_url") if "source_url" in r else None,
                        effective_from=_to_date(r.get("effective_from") if "effective_from" in r else None),
                    )
                    session.add(pe)
                    stats["events_created"] += 1
                    # if elected, add elected_councillor event
                    if str(r.get("is_elected")).lower() in ("true", "1"):
                        evt_win = session.query(db.EventType).filter(db.EventType.code == "elected_councillor").first()
                        party_id2 = int(party_obj.id) if party_obj and party_obj.id is not None else None
                        ward_id2 = int(ward_obj.id) if ward_obj and ward_obj.id is not None else None
                        event_type_id2 = int(evt_win.id) if evt_win and evt_win.id is not None else None
                        pe2 = db.PersonEvent(
                            council_id=int(council.id),
                            person_id=int(person.id),
                            event_type_id=event_type_id2,
                            party_id=party_id2,
                            ward_id=ward_id2,
                            effective_from=_to_date(r.get("effective_from") if "effective_from" in r else None),
                            source_url=r.get("source_url") if "source_url" in r else None,
                        )
                        session.add(pe2)
                        stats["events_created"] += 1
                        stats["events_elected"] += 1

        # councillors.csv -> council_post_held events
        if councillors_csv.exists():
            df = pd.read_csv(councillors_csv)
            for _, r in df.iterrows():
                name = r.get("councillor_name")
                # try to match by person_uid using people.csv mapping
                # people.csv person_id is used as person_uid; try to find by canonical name if no match
                person = None
                # primary: exact match on `people.canonical_name`
                if name and not pd.isna(name):
                    person = (
                        session.query(db.Person)
                        .filter(db.Person.council_id == council.id)
                        .filter(db.Person.canonical_name == name)
                        .first()
                    )
                # fallback: create a new Person record
                if not person:
                    # create a synthetic uid
                    uid = f"migrated:{name}"
                    person, created = get_or_create_person(session, council.id, uid, name, None)
                    if created:
                        stats["people_created"] += 1

                party_obj = None
                if "party_name" in r and not pd.isna(r.party_name):
                    party_obj, created = get_or_create_party(session, council.id, r.party_name, r.get("councillor_url") if "councillor_url" in r else None)
                    if created:
                        stats["parties_created"] += 1

                ward_obj = None
                if "ward_name" in r and not pd.isna(r.ward_name):
                    ward_obj = session.query(db.Ward).filter(db.Ward.council_id == council.id).filter(db.Ward.name == r.ward_name).first()

                evt = session.query(db.EventType).filter(db.EventType.code == "council_post_held").first()
                party_id3 = int(party_obj.id) if party_obj and getattr(party_obj, "id", None) is not None else None
                ward_id3 = int(ward_obj.id) if ward_obj and getattr(ward_obj, "id", None) is not None else None
                event_type_id3 = int(evt.id) if evt and getattr(evt, "id", None) is not None else None
                pe = db.PersonEvent(
                    council_id=int(council.id),
                    person_id=int(person.id),
                    event_type_id=event_type_id3,
                    party_id=party_id3,
                    ward_id=ward_id3,
                    effective_from=_to_date(r.get('effective_from') if 'effective_from' in r else None),
                    effective_to=_to_date(r.get('effective_to') if 'effective_to' in r else None),
                    source_url=r.get('councillor_url') if 'councillor_url' in r else None,
                )
                session.add(pe)
                stats["events_created"] += 1

        # end with commit or dry-run
        if args.dry_run:
            session.rollback()
            print("Dry-run complete. No database changes committed.")
        else:
            session.commit()
            print("Migration committed to DB.")

    # write a short report
    out = Path("output") / "development"
    out.mkdir(parents=True, exist_ok=True)
    report = out / ("migration_report" + ("_dryrun.csv" if args.dry_run else ".csv"))
    pd.DataFrame([stats]).to_csv(report, index=False)
    print(f"Wrote report: {report}")
    print(stats)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=None, help="path to sqlite DB (optional)")
    p.add_argument("--dry-run", action="store_true", help="Do not commit changes; preview only")
    args = p.parse_args()
    migrate(args)


if __name__ == "__main__":
    main()


