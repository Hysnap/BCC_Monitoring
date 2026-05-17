"""Helpers to ingest CSV/scraper outputs into the monitoring DB with change logging.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from . import database as db


def _to_date(val):
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def _record_change(session, council_id: Optional[int], table_name: str, record_key: str, field_name: str, old, new, source_url: Optional[str] = None):
    cl = db.ChangeLog(
        council_id=council_id,
        table_name=table_name,
        record_id=str(record_key),
        field_name=field_name,
        old_value=str(old) if old is not None else None,
        new_value=str(new) if new is not None else None,
        change_reason="ingest",
        changed_by="scraper",
        source_url=source_url,
    )
    session.add(cl)


def write_councillors_links_to_db(links_csv: Path | str, db_path: Optional[str] = None, dry_run: bool = False):
    """Ingest `councillor_links.csv` into people/parties/wards/person_events with change logs.

    links_csv: path to councillor_links.csv
    db_path: optional sqlite path to pass to db.get_engine
    dry_run: if True, roll back at the end
    """
    links_csv = Path(links_csv)
    if not links_csv.exists():
        raise FileNotFoundError(links_csv)

    df = pd.read_csv(links_csv)

    engine = db.get_engine(db_path)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        council = session.query(db.Council).filter(db.Council.code == "birmingham").first()
        if not council:
            council = db.Council(code="birmingham", name="Birmingham City Council")
            session.add(council)
            session.flush()

        evt = session.query(db.EventType).filter(db.EventType.code == "council_post_held").first()
        if not evt:
            evt = db.EventType(code="council_post_held", name="Council post held")
            session.add(evt)
            session.flush()

        for _, r in df.iterrows():
            pid = str(r.get("person_id"))
            name = r.get("person_name")
            ward_name = r.get("ward_name")
            party_name = r.get("party_name") if "party_name" in r else None
            joined = r.get("joined_council") if "joined_council" in r else None
            left = r.get("office_expires") if "office_expires" in r else None
            source = r.get("source") if "source" in r else None

            # person
            person = (
                session.query(db.Person)
                .filter(db.Person.council_id == council.id)
                .filter(db.Person.person_uid == pid)
                .first()
            )
            if not person:
                person = db.Person(council_id=council.id, person_uid=pid, canonical_name=name, source_url=source)
                session.add(person)
                session.flush()
                _record_change(session, council.id, "people", pid, "created", None, name, source)
            else:
                # detect name change
                if person.canonical_name != name:
                    _record_change(session, council.id, "people", pid, "canonical_name", person.canonical_name, name, source)
                    person.canonical_name = name
                if getattr(person, "source_url", None) != source:
                    _record_change(session, council.id, "people", pid, "source_url", getattr(person, "source_url", None), source, source)
                    person.source_url = source

            # party
            party_obj = None
            if party_name and not pd.isna(party_name):
                party_obj = (
                    session.query(db.Party)
                    .filter(db.Party.council_id == council.id)
                    .filter(db.Party.name == party_name)
                    .first()
                )
                if not party_obj:
                    party_obj = db.Party(council_id=council.id, name=party_name, source_url=source)
                    session.add(party_obj)
                    session.flush()
                    _record_change(session, council.id, "parties", party_name, "created", None, party_name, source)

            # ward
            ward_obj = None
            if ward_name and not pd.isna(ward_name):
                ward_obj = (
                    session.query(db.Ward)
                    .filter(db.Ward.council_id == council.id)
                    .filter(db.Ward.name == ward_name)
                    .first()
                )
                if not ward_obj:
                    ward_obj = db.Ward(council_id=council.id, name=ward_name, source_url=source)
                    session.add(ward_obj)
                    session.flush()
                    _record_change(session, council.id, "wards", ward_name, "created", None, ward_name, source)

            # person event (council_post_held)
            pe = db.PersonEvent(
                council_id=council.id,
                person_id=person.id,
                event_type_id=evt.id,
                party_id=party_obj.id if party_obj else None,
                ward_id=ward_obj.id if ward_obj else None,
                effective_from=_to_date(joined),
                effective_to=_to_date(left),
                source_url=source,
            )
            session.add(pe)
            session.flush()
            _record_change(session, council.id, "person_events", pe.id, "created", None, f"event_type={evt.code}", source)

        if dry_run:
            session.rollback()
        else:
            session.commit()
