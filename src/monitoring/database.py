"""Relational data model for multi-council monitoring.

Design goals:
- Single source of truth via normalized core entities.
- Temporal tracking for event validity and change history.
- Compliance metadata with public source URLs and validity windows.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import Boolean
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import create_engine
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship


class Base(DeclarativeBase):
    pass


class Council(Base):
    __tablename__ = "councils"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    homepage_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    council_id: Mapped[int] = mapped_column(
        ForeignKey("councils.id"),
        index=True,
    )
    person_uid: Mapped[str] = mapped_column(String(64), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    first_seen_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_valid_from: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    source_valid_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    council: Mapped[Council] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "council_id",
            "person_uid",
            name="uq_people_council_person_uid",
        ),
    )


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    council_id: Mapped[int] = mapped_column(
        ForeignKey("councils.id"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), index=True)
    short_name: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_valid_from: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    source_valid_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("council_id", "name", name="uq_parties_council_name"),
    )


class Ward(Base):
    __tablename__ = "wards"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    council_id: Mapped[int] = mapped_column(
        ForeignKey("councils.id"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), index=True)
    ward_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "council_id",
            "name",
            "valid_from",
            name="uq_wards_temporal_name",
        ),
    )


class EventType(Base):
    __tablename__ = "event_types"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Label(Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    label_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("labels.id"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)

    label_group: Mapped[Optional["Label"]] = relationship(
        remote_side="Label.id",
    )


class Committee(Base):
    __tablename__ = "committees"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    council_id: Mapped[int] = mapped_column(
        ForeignKey("councils.id"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), index=True)
    public_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_held_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "council_id",
            "title",
            "first_held_date",
            name="uq_committees_temporal",
        ),
    )


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    council_id: Mapped[int] = mapped_column(
        ForeignKey("councils.id"),
        index=True,
    )
    committee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("committees.id"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), index=True)
    meeting_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    public_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_valid_from: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    source_valid_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )


class PersonEvent(Base):
    __tablename__ = "person_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    council_id: Mapped[int] = mapped_column(
        ForeignKey("councils.id"),
        index=True,
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id"),
        index=True,
    )
    event_type_id: Mapped[int] = mapped_column(
        ForeignKey("event_types.id"),
        index=True,
    )
    party_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("parties.id"),
        nullable=True,
    )
    ward_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("wards.id"),
        nullable=True,
    )
    committee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("committees.id"),
        nullable=True,
    )
    meeting_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("meetings.id"),
        nullable=True,
    )

    event_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        index=True,
    )
    effective_from: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    effective_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_valid_from: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    source_valid_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )


class PersonEventLabel(Base):
    __tablename__ = "person_event_labels"

    person_event_id: Mapped[int] = mapped_column(
        ForeignKey("person_events.id"),
        primary_key=True,
    )
    label_id: Mapped[int] = mapped_column(
        ForeignKey("labels.id"),
        primary_key=True,
    )


class EntityLabel(Base):
    __tablename__ = "entity_labels"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    council_id: Mapped[int] = mapped_column(
        ForeignKey("councils.id"),
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_key: Mapped[str] = mapped_column(String(128), index=True)
    label_id: Mapped[int] = mapped_column(
        ForeignKey("labels.id"),
        index=True,
    )
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "council_id",
            "entity_type",
            "entity_key",
            "label_id",
            "valid_from",
            name="uq_entity_labels_temporal",
        ),
    )


class ChangeLog(Base):
    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    council_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("councils.id"),
        nullable=True,
        index=True,
    )
    table_name: Mapped[str] = mapped_column(String(128), index=True)
    record_id: Mapped[str] = mapped_column(String(128), index=True)
    field_name: Mapped[str] = mapped_column(String(128))
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(128), default="pipeline")
    changed_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        index=True,
    )
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_valid_from: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    source_valid_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )


def get_engine(db_path: Optional[Path | str] = None):
    if db_path is None:
        resolved = Path("output") / "data" / "monitoring.sqlite"
    else:
        resolved = Path(db_path)
    if not resolved.is_absolute():
        resolved = Path(__file__).resolve().parents[2] / resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{resolved}", future=True)


def create_schema(db_path: Optional[Path | str] = None) -> None:
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)


def seed_reference_data(db_path: Optional[Path | str] = None) -> None:
    """Seed baseline event types and common label groups."""
    from sqlalchemy.orm import Session

    engine = get_engine(db_path)
    with Session(engine) as session:
        if not session.query(Council).filter(
            Council.code == "birmingham"
        ).first():
            session.add(
                Council(code="birmingham", name="Birmingham City Council")
            )

        baseline_event_types = [
            ("election_candidate", "Election candidate"),
            ("elected_councillor", "Elected councillor"),
            ("related_party", "Related party"),
            (
                "submitted_declaration_of_interests",
                "Submitted declaration of interests",
            ),
            ("changed_surgery_details", "Changed surgery details"),
            ("attended_meeting", "Attended meeting"),
            (
                "absence_reason_provided",
                "Gave reasons for absence at meeting",
            ),
            ("committee_membership", "Committee membership"),
            ("council_post_held", "Council post held"),
        ]
        for code, name in baseline_event_types:
            if not session.query(EventType).filter(
                EventType.code == code
            ).first():
                session.add(EventType(code=code, name=name))

        groups = [
            ("usage_event_class", "Event classification"),
            ("usage_quality", "Data quality"),
            ("usage_compliance", "Compliance"),
            ("usage_reporting", "Reporting"),
        ]
        for code, name in groups:
            if not session.query(Label).filter(Label.code == code).first():
                session.add(Label(code=code, name=name, is_group=True))

        session.commit()
