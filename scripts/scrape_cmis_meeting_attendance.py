"""Scrape attendance, apologies, and absences from a CMIS meeting page."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sl_core"))

try:  # noqa: E402
    from utils import global_variables as gv
except Exception:  # pragma: no cover - fallback when Streamlit is not installed
    class _FallbackGlobals:
        DIRECTORIES = {"output_dir": Path("output")}

    gv = _FallbackGlobals()

from src.monitoring.meeting_attendance import (  # noqa: E402
    AttendanceSectionSpec,
    MeetingAttendanceRecord,
    build_expected_comparison,
    extract_section_records,
    parse_meeting_summary,
    normalise_whitespace,
    to_dataframe,
)
from src.monitoring.ingest import write_meeting_attendance_to_db  # noqa: E402


DEFAULT_MEETING_URL = (
    "https://birmingham.cmis.uk.com/birmingham/Meetings/tabid/70/ctl/"
    "ViewMeetingPublic/mid/397/Meeting/14834/Committee/39/Default.aspx"
)

DEFAULT_SECTION_SPECS: Tuple[AttendanceSectionSpec, ...] = (
    AttendanceSectionSpec(title="Attended - Committee Members", status_code="attended"),
    AttendanceSectionSpec(title="Attended - Other Members", status_code="attended_other"),
    AttendanceSectionSpec(title="Apologies", status_code="apology", reason_column="Reason for Sending Apology"),
    AttendanceSectionSpec(title="Absent", status_code="absent", reason_column="Reason for Absence"),
)


def build_browser_context(playwright, headed: bool = False):
    browser = playwright.chromium.launch(headless=not headed)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1200},
        locale="en-GB",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    return browser, context


def ensure_output_dirs(base_dir: Path) -> Dict[str, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)
    return {
        "base": base_dir,
        "raw": base_dir / "raw",
        "attendance": base_dir / "attendance.csv",
        "comparison": base_dir / "comparison.csv",
        "manifest": base_dir / "manifest.json",
    }


def read_expected_names(path: Path, name_column: str) -> List[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    frame = pd.read_csv(path)
    if name_column not in frame.columns:
        fallback_columns = [column for column in ("councillor_name", "person_name", "name") if column in frame.columns]
        if not fallback_columns:
            return []
        name_column = fallback_columns[0]
    return [str(value) for value in frame[name_column].dropna().tolist()]


def _click_attendance_tab(page, tab_title: str, timeout_ms: int) -> None:
    locators = [
        page.get_by_text(tab_title, exact=True),
        page.locator("li").filter(has_text=tab_title).first,
        page.locator(".nav, .tabs, ul").filter(has_text=tab_title).first,
    ]
    last_error: Optional[Exception] = None
    for locator in locators:
        try:
            locator.click(timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            page.wait_for_timeout(500)
            return
        except Exception as exc:  # pragma: no cover - fallback path depends on page markup
            last_error = exc
    if last_error is not None:
        raise last_error


def _extract_pager_targets(html: str, section_title: str) -> List[Tuple[int, str]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    fieldset = None
    for candidate in soup.find_all("fieldset"):
        legend = candidate.find("legend")
        if legend and normalise_whitespace(legend.get_text(" ", strip=True)) == section_title:
            fieldset = candidate
            break
    if fieldset is None:
        return []

    grid = fieldset.find("div", class_=re.compile(r"\bRadGrid\b"))
    if grid is None or not grid.get("id"):
        return []

    postback_prefix = grid["id"].replace("_", "$")

    targets: List[Tuple[int, str]] = []
    seen = set()
    for anchor in fieldset.find_all("a", href=True):
        href = anchor["href"]
        if postback_prefix not in href or "__doPostBack" not in href:
            continue
        text = normalise_whitespace(anchor.get_text(" ", strip=True))
        if not text.isdigit():
            continue
        if text in seen:
            continue
        seen.add(text)
        targets.append((int(text), href))
    targets.sort(key=lambda item: item[0])
    return targets


def _collect_pages(page, meeting_url: str, section_title: str, timeout_ms: int, raw_dir: Path) -> List[str]:
    html_pages: List[str] = []
    html = page.content()
    html_pages.append(html)
    (raw_dir / "attendance_page_1.html").write_text(html, encoding="utf-8")

    for page_number, href in _extract_pager_targets(html, section_title):
        if page_number == 1:
            continue
        target_match = re.search(r"__doPostBack\('([^']+)'", href)
        if not target_match:
            continue
        pager_link = page.locator(f'a[href*="{target_match.group(1)}"]')
        pager_link.click(timeout=timeout_ms, force=True, no_wait_after=True)
        page.wait_for_function(
            "marker => document.body.innerText.includes(marker)",
            arg=f"Page {page_number} of",
            timeout=timeout_ms,
        )
        page.wait_for_timeout(500)
        html = page.content()
        html_pages.append(html)
        (raw_dir / f"attendance_page_{page_number}.html").write_text(html, encoding="utf-8")

    return html_pages


def _dedupe_records(records: Sequence[MeetingAttendanceRecord]) -> List[MeetingAttendanceRecord]:
    unique: Dict[Tuple[str, str, str], MeetingAttendanceRecord] = {}
    for record in records:
        key = (record.section_title, record.person_name_key, record.status_code)
        if key not in unique:
            unique[key] = record
    return list(unique.values())


def scrape_meeting_attendance(
    meeting_url: str,
    output_dir: Path,
    expected_roster_csv: Optional[Path],
    expected_name_column: str,
    attendance_tab_title: str,
    section_specs: Sequence[AttendanceSectionSpec],
    timeout_ms: int,
    db_path: Optional[Path] = None,
    headed: bool = False,
) -> Dict[str, object]:
    output_paths = ensure_output_dirs(output_dir)
    output_paths["raw"].mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser, context = build_browser_context(playwright, headed=headed)
        page = context.new_page()

        try:
            page.goto(meeting_url, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(500)
            _click_attendance_tab(page, attendance_tab_title, timeout_ms)

            attended_html_pages = _collect_pages(page, meeting_url, section_specs[0].title, timeout_ms, output_paths["raw"])

            records: List[MeetingAttendanceRecord] = []
            for html in attended_html_pages:
                records.extend(extract_section_records(html, meeting_url, section_specs))

            records = _dedupe_records(records)
            attendance_frame = to_dataframe(records)
            meeting_meta = parse_meeting_summary(attended_html_pages[0], meeting_url)
            if not attendance_frame.empty:
                attendance_frame.sort_values(
                    by=["section_title", "status_code", "person_name"],
                    inplace=True,
                    kind="stable",
                )
            attendance_frame.to_csv(output_paths["attendance"], index=False)

            if db_path is not None:
                write_meeting_attendance_to_db(
                    output_paths["attendance"],
                    db_path=str(db_path),
                    meeting_title=meeting_meta["meeting_title"],
                    meeting_date=meeting_meta["meeting_date"],
                    meeting_url=meeting_meta["meeting_url"],
                )

            if expected_roster_csv is None:
                expected_names = [record.person_name for record in records]
            else:
                expected_names = read_expected_names(expected_roster_csv, expected_name_column)

            meeting_title = (
                records[0].meeting_title if records else meeting_meta["meeting_title"] or ""
            )
            meeting_date = records[0].meeting_date if records else meeting_meta["meeting_date"]
            comparison_rows = build_expected_comparison(
                meeting_url=meeting_url,
                meeting_title=meeting_title,
                meeting_date=meeting_date,
                attendance_records=records,
                expected_names=expected_names,
            )
            comparison_frame = to_dataframe(comparison_rows)
            if not comparison_frame.empty:
                comparison_frame.sort_values(
                    by=["comparison_status", "expected_name"],
                    inplace=True,
                    kind="stable",
                )
            comparison_frame.to_csv(output_paths["comparison"], index=False)

            manifest = {
                "meeting_url": meeting_url,
                "meeting_title": meeting_title,
                "meeting_date": meeting_date,
                "attendance_count": int((attendance_frame["status_code"] == "attended").sum()) if not attendance_frame.empty else 0,
                "apology_count": int((attendance_frame["status_code"] == "apology").sum()) if not attendance_frame.empty else 0,
                "absent_count": int((attendance_frame["status_code"] == "absent").sum()) if not attendance_frame.empty else 0,
                "comparison_rows": len(comparison_rows),
                "expected_roster_csv": str(expected_roster_csv) if expected_roster_csv else None,
                "generated_at": date.today().isoformat(),
                "section_titles": [spec.title for spec in section_specs],
                "privacy_note": "Attendance, apologies, and absences are normalized from the public CMIS meeting page; use a historical roster CSV when comparing older meetings.",
            }
            output_paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            return manifest
        finally:
            context.close()
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape CMIS meeting attendance and compare it to an expected roster")
    parser.add_argument("--meeting-url", default=DEFAULT_MEETING_URL, help="CMIS meeting URL to scrape")
    parser.add_argument(
        "--output-dir",
        default=str(gv.DIRECTORIES["output_dir"] / "development" / "meeting_attendance"),
        help="Directory for CSV outputs",
    )
    parser.add_argument(
        "--expected-roster-csv",
        default=str(gv.DIRECTORIES["output_dir"] / "current" / "councillors.csv"),
        help="CSV used as the expected roster for comparison",
    )
    parser.add_argument("--expected-name-column", default="councillor_name", help="Column name to use from the expected roster CSV")
    parser.add_argument("--attendance-tab-title", default="Attendance", help="Tab title to open before scraping the attendance grid")
    parser.add_argument("--timeout-ms", type=int, default=60000, help="Navigation timeout in milliseconds")
    parser.add_argument("--db-path", default=str(gv.DIRECTORIES["output_dir"] / "data" / "monitoring.sqlite"), help="SQLite database path to update")
    parser.add_argument("--headed", action="store_true", help="Run the browser headed instead of headless")
    args = parser.parse_args()

    expected_roster_csv = Path(args.expected_roster_csv) if args.expected_roster_csv else None
    if expected_roster_csv is not None and not expected_roster_csv.exists():
        expected_roster_csv = None

    manifest = scrape_meeting_attendance(
        meeting_url=args.meeting_url,
        output_dir=Path(args.output_dir),
        expected_roster_csv=expected_roster_csv,
        expected_name_column=args.expected_name_column,
        attendance_tab_title=args.attendance_tab_title,
        section_specs=DEFAULT_SECTION_SPECS,
        timeout_ms=args.timeout_ms,
        db_path=Path(args.db_path) if args.db_path else None,
        headed=args.headed,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()