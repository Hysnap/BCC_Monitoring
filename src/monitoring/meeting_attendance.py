"""Helpers for CMIS meeting attendance scraping and comparison."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class AttendanceSectionSpec:
    """Describe one CMIS attendance section and the status it represents."""

    title: str
    status_code: str
    reason_column: Optional[str] = None


@dataclass(frozen=True)
class MeetingAttendanceRecord:
    meeting_url: str
    meeting_title: str
    meeting_date: Optional[str]
    section_title: str
    status_code: str
    person_name: str
    person_name_key: str
    person_url: Optional[str]
    person_id: Optional[str]
    reason: Optional[str]
    page_number: Optional[int]
    page_count: Optional[int]
    source_url: str


@dataclass(frozen=True)
class MeetingAttendanceComparisonRecord:
    meeting_url: str
    meeting_title: str
    meeting_date: Optional[str]
    expected_name: str
    expected_name_key: str
    observed_status: Optional[str]
    observed_section: Optional[str]
    observed_page_number: Optional[int]
    observed_person_url: Optional[str]
    reason: Optional[str]
    comparison_status: str
    source_url: str


def normalise_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalise_person_name(value: str) -> str:
    value = normalise_whitespace(value)
    value = re.sub(r"^(Councillor|Cllr\.?|Councillor\s+the\s+Lord\s+Mayor)\s+", "", value, flags=re.I)
    return value.casefold()


def build_person_id(person_name: str) -> str:
    import hashlib

    return hashlib.sha1(normalise_person_name(person_name).encode("utf-8")).hexdigest()[:16]


def parse_meeting_summary(html: str, meeting_url: str) -> Dict[str, Optional[str]]:
    """Extract the title/date fields from a CMIS meeting page."""

    soup = BeautifulSoup(html, "lxml")
    heading = soup.find("h1")
    title = normalise_whitespace(heading.get_text(" ", strip=True)) if heading else ""

    committee_name: Optional[str] = None
    meeting_date: Optional[str] = None

    summary = soup.find(string=re.compile(r"Committee:\s*"))
    if summary:
        summary_text = normalise_whitespace(summary.parent.get_text(" ", strip=True)) if summary.parent else normalise_whitespace(str(summary))
        match = re.search(r"Committee:\s*(.*?)\s+Date/Time:\s*(.*?)\s+Status:", summary_text)
        if match:
            committee_name = normalise_whitespace(match.group(1)) or None
            meeting_date = normalise_whitespace(match.group(2)) or None

    return {
        "meeting_title": title,
        "committee_name": committee_name,
        "meeting_date": meeting_date,
        "meeting_url": meeting_url,
    }


def _find_section_fieldset(soup: BeautifulSoup, section_title: str):
    for fieldset in soup.find_all("fieldset"):
        legend = fieldset.find("legend")
        if not legend:
            continue
        if normalise_whitespace(legend.get_text(" ", strip=True)) == section_title:
            return fieldset
    return None


def _parse_page_marker(fieldset) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    marker = fieldset.get_text(" ", strip=True)
    match = re.search(r"Page\s+(\d+)\s+of\s+(\d+),\s+items\s+(\d+)\s+to\s+(\d+)\s+of\s+(\d+)", marker)
    if not match:
        return None, None, None, None
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(5))


def extract_section_records(
    html: str,
    meeting_url: str,
    section_specs: Sequence[AttendanceSectionSpec],
) -> List[MeetingAttendanceRecord]:
    """Extract row-level attendance records from one rendered meeting page."""

    soup = BeautifulSoup(html, "lxml")
    meeting_meta = parse_meeting_summary(html, meeting_url)
    records: List[MeetingAttendanceRecord] = []

    for section in section_specs:
        fieldset = _find_section_fieldset(soup, section.title)
        if fieldset is None:
            continue

        page_number, page_count, _, _ = _parse_page_marker(fieldset)
        grid = fieldset.find("div", class_=re.compile(r"\bRadGrid\b"))
        table = grid.find("table") if grid else fieldset.find("table")
        if table is None:
            continue

        for row in table.find_all("tr", attrs={"role": "row"}):
            cells = row.find_all("td")
            if not cells:
                continue
            first_cell = cells[0]
            link = first_cell.find("a", href=True)
            person_name = normalise_whitespace(link.get_text(" ", strip=True)) if link else normalise_whitespace(first_cell.get_text(" ", strip=True))
            if not person_name or person_name.lower() in {"name", "reason for sending apology", "reason for absence"}:
                continue

            person_url = link["href"] if link else None
            person_id = None
            if person_url:
                match = re.search(r"/id/(\d+)/", person_url)
                if match:
                    person_id = match.group(1)

            reason = None
            if len(cells) > 1:
                reason_text = normalise_whitespace(cells[1].get_text(" ", strip=True))
                reason = reason_text or None

            records.append(
                MeetingAttendanceRecord(
                    meeting_url=meeting_meta["meeting_url"] or meeting_url,
                    meeting_title=meeting_meta["meeting_title"] or "",
                    meeting_date=meeting_meta["meeting_date"],
                    section_title=section.title,
                    status_code=section.status_code,
                    person_name=person_name,
                    person_name_key=normalise_person_name(person_name),
                    person_url=person_url,
                    person_id=person_id,
                    reason=reason,
                    page_number=page_number,
                    page_count=page_count,
                    source_url=meeting_url,
                )
            )

    return records


def build_expected_comparison(
    meeting_url: str,
    meeting_title: str,
    meeting_date: Optional[str],
    attendance_records: Sequence[MeetingAttendanceRecord],
    expected_names: Iterable[str],
) -> List[MeetingAttendanceComparisonRecord]:
    """Compare an expected roster against the observed attendance records."""

    observed: Dict[str, MeetingAttendanceRecord] = {}
    precedence = {"attended": 3, "apology": 2, "absent": 1}

    for record in attendance_records:
        key = record.person_name_key
        current = observed.get(key)
        if current is None or precedence.get(record.status_code, 0) > precedence.get(current.status_code, 0):
            observed[key] = record

    comparison_rows: List[MeetingAttendanceComparisonRecord] = []
    seen_expected = set()

    for expected_name in expected_names:
        expected_name = normalise_whitespace(str(expected_name))
        if not expected_name:
            continue
        expected_key = normalise_person_name(expected_name)
        seen_expected.add(expected_key)
        observed_record = observed.get(expected_key)
        comparison_rows.append(
            MeetingAttendanceComparisonRecord(
                meeting_url=meeting_url,
                meeting_title=meeting_title,
                meeting_date=meeting_date,
                expected_name=expected_name,
                expected_name_key=expected_key,
                observed_status=observed_record.status_code if observed_record else None,
                observed_section=observed_record.section_title if observed_record else None,
                observed_page_number=observed_record.page_number if observed_record else None,
                observed_person_url=observed_record.person_url if observed_record else None,
                reason=observed_record.reason if observed_record else None,
                comparison_status="matched" if observed_record else "missing",
                source_url=meeting_url,
            )
        )

    for record in attendance_records:
        if record.person_name_key in seen_expected:
            continue
        comparison_rows.append(
            MeetingAttendanceComparisonRecord(
                meeting_url=meeting_url,
                meeting_title=meeting_title,
                meeting_date=meeting_date,
                expected_name=record.person_name,
                expected_name_key=record.person_name_key,
                observed_status=record.status_code,
                observed_section=record.section_title,
                observed_page_number=record.page_number,
                observed_person_url=record.person_url,
                reason=record.reason,
                comparison_status="unexpected",
                source_url=meeting_url,
            )
        )

    return comparison_rows


def to_dataframe(records: Sequence[object]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    return pd.DataFrame([record.__dict__ if hasattr(record, "__dict__") else record for record in records])