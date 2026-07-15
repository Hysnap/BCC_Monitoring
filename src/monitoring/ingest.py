"""Helpers to ingest CSV/scraper outputs into the monitoring DB with change logging.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from pandas.errors import EmptyDataError

from . import database as db
from .meeting_attendance import build_person_id


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


def write_meeting_attendance_to_db(
    attendance_csv: Path | str,
    db_path: Optional[str] = None,
    dry_run: bool = False,
    meeting_title: Optional[str] = None,
    meeting_date: Optional[str] = None,
    meeting_url: Optional[str] = None,
):
    """Ingest `attendance.csv` into meetings/person_events with change logs.

    The CSV remains the raw export, but this writes the same run into the canonical SQLite database.
    """

    attendance_csv = Path(attendance_csv)
    if not attendance_csv.exists():
        raise FileNotFoundError(attendance_csv)

    if attendance_csv.stat().st_size == 0:
        df = pd.DataFrame()
    else:
        try:
            df = pd.read_csv(attendance_csv)
        except EmptyDataError:
            df = pd.DataFrame()

    db.create_schema(db_path)
    db.seed_reference_data(db_path)

    engine = db.get_engine(db_path)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        council = session.query(db.Council).filter(db.Council.code == "birmingham").first()
        if not council:
            council = db.Council(code="birmingham", name="Birmingham City Council")
            session.add(council)
            session.flush()

        attended_evt = session.query(db.EventType).filter(db.EventType.code == "attended_meeting").first()
        if not attended_evt:
            attended_evt = db.EventType(code="attended_meeting", name="Attended meeting")
            session.add(attended_evt)
            session.flush()

        absence_evt = session.query(db.EventType).filter(db.EventType.code == "absence_reason_provided").first()
        if not absence_evt:
            absence_evt = db.EventType(
                code="absence_reason_provided",
                name="Gave reasons for absence at meeting",
            )
            session.add(absence_evt)
            session.flush()

        csv_meeting_title = (
            str(df["meeting_title"].dropna().iloc[0])
            if "meeting_title" in df.columns and not df["meeting_title"].dropna().empty
            else ""
        )
        csv_meeting_date_value = (
            df["meeting_date"].dropna().iloc[0]
            if "meeting_date" in df.columns and not df["meeting_date"].dropna().empty
            else None
        )
        csv_meeting_date = _to_date(csv_meeting_date_value) if csv_meeting_date_value is not None else None
        csv_meeting_url = (
            str(df["meeting_url"].dropna().iloc[0])
            if "meeting_url" in df.columns and not df["meeting_url"].dropna().empty
            else None
        )

        meeting_title = meeting_title or csv_meeting_title
        meeting_date_value = meeting_date or csv_meeting_date
        meeting_url = meeting_url or csv_meeting_url
        meeting_date = _to_date(meeting_date_value) if meeting_date_value is not None else None

        committee = None
        if meeting_title:
            committee = (
                session.query(db.Committee)
                .filter(db.Committee.council_id == council.id)
                .filter(db.Committee.title == meeting_title)
                .first()
            )
            if not committee:
                committee = db.Committee(
                    council_id=council.id,
                    title=meeting_title,
                    public_url=meeting_url,
                    first_held_date=meeting_date,
                )
                session.add(committee)
                session.flush()
                _record_change(session, council.id, "committees", committee.id, "created", None, meeting_title, meeting_url)

        meeting = None
        if meeting_title or meeting_date or meeting_url:
            meeting_query = session.query(db.Meeting).filter(db.Meeting.council_id == council.id)
            if meeting_title:
                meeting_query = meeting_query.filter(db.Meeting.title == meeting_title)
            if meeting_date is not None:
                meeting_query = meeting_query.filter(db.Meeting.meeting_date == meeting_date)
            if meeting_url:
                meeting_query = meeting_query.filter(db.Meeting.public_url == meeting_url)
            meeting = meeting_query.first()
            if not meeting:
                meeting = db.Meeting(
                    council_id=council.id,
                    committee_id=committee.id if committee else None,
                    title=meeting_title or (meeting_url or "Meeting"),
                    meeting_date=meeting_date,
                    public_url=meeting_url,
                )
                session.add(meeting)
                session.flush()
                _record_change(session, council.id, "meetings", meeting.id, "created", None, meeting.title, meeting_url)

        if df.empty:
            if dry_run:
                session.rollback()
            else:
                session.commit()
            return

        for _, row in df.iterrows():
            person_name = row.get("person_name")
            if pd.isna(person_name):
                continue
            person_name = str(person_name)
            person_uid = str(row.get("person_id")) if not pd.isna(row.get("person_id")) else build_person_id(person_name)
            person_url = str(row.get("person_url")) if not pd.isna(row.get("person_url")) else None
            status_code = str(row.get("status_code")) if not pd.isna(row.get("status_code")) else ""
            reason = str(row.get("reason")) if "reason" in df.columns and not pd.isna(row.get("reason")) else None
            section_title = str(row.get("section_title")) if not pd.isna(row.get("section_title")) else None

            person = (
                session.query(db.Person)
                .filter(db.Person.council_id == council.id)
                .filter(db.Person.person_uid == person_uid)
                .first()
            )
            if not person:
                person = db.Person(
                    council_id=council.id,
                    person_uid=person_uid,
                    canonical_name=person_name,
                    source_url=person_url or meeting_url,
                )
                session.add(person)
                session.flush()
                _record_change(session, council.id, "people", person_uid, "created", None, person_name, person_url or meeting_url)
            elif person.canonical_name != person_name:
                _record_change(session, council.id, "people", person_uid, "canonical_name", person.canonical_name, person_name, person_url or meeting_url)
                person.canonical_name = person_name

            event_type = attended_evt if status_code in {"attended", "attended_other"} else absence_evt
            event_value = reason if reason else status_code or None

            event = db.PersonEvent(
                council_id=council.id,
                person_id=person.id,
                event_type_id=event_type.id,
                committee_id=committee.id if committee else None,
                meeting_id=meeting.id if meeting else None,
                event_value=event_value,
                event_notes=section_title,
                effective_from=meeting_date,
                source_url=person_url or meeting_url,
                source_valid_from=meeting_date,
            )
            session.add(event)
            session.flush()
            _record_change(session, council.id, "person_events", event.id, "created", None, event_type.code, person_url or meeting_url)

        if dry_run:
            session.rollback()
        else:
            session.commit()
