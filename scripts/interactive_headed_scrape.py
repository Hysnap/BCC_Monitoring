"""Interactive headed scraper.

1. Opens the Committee index in a headed Playwright browser.
2. Let you log in and navigate to any meeting page.
3. Press Enter in the terminal to scrape the currently-open meeting page.
4. Repeat until you type 'done'.

This reuses the same Playwright `page` for scraping so your logged-in session is preserved.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path
from typing import List

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sl_core"))

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from src.monitoring.meeting_attendance import (
    AttendanceSectionSpec,
    MeetingAttendanceRecord,
    extract_section_records,
    normalise_whitespace,
    to_dataframe,
)


DEFAULT_SECTION_SPECS = (
    AttendanceSectionSpec(title="Attended - Committee Members", status_code="attended"),
    AttendanceSectionSpec(title="Attended - Other Members", status_code="attended_other"),
    AttendanceSectionSpec(title="Apologies", status_code="apology", reason_column="Reason for Sending Apology"),
    AttendanceSectionSpec(title="Absent", status_code="absent", reason_column="Reason for Absence"),
)


def normalise_url(href: str) -> str:
    if href.startswith("http"):
        return href
    return f"https://birmingham.cmis.uk.com{href}" if href.startswith("/") else f"https://birmingham.cmis.uk.com/birmingham/{href}"


def slug_from_url(url: str) -> str:
    return url.rstrip("/\n\r").split("/")[-1].replace(".aspx", "")


def click_attendance_tab(page, tab_title: str, timeout_ms: int = 60000) -> None:
    locators = [
        page.get_by_text(tab_title, exact=True),
        page.locator("li").filter(has_text=tab_title).first,
        page.locator(".nav, .tabs, ul").filter(has_text=tab_title).first,
    ]
    last_error = None
    for locator in locators:
        try:
            locator.click(timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            page.wait_for_timeout(500)
            return
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error


def extract_pager_targets(html: str, section_title: str) -> List[tuple]:
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

    targets = []
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


def collect_pages(page, section_title: str, timeout_ms: int, raw_dir: Path) -> List[str]:
    html_pages = []
    html = page.content()
    html_pages.append(html)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "attendance_page_1.html").write_text(html, encoding="utf-8")

    for page_number, href in extract_pager_targets(html, section_title):
        if page_number == 1:
            continue
        target_match = re.search(r"__doPostBack\('([^']+)'", href)
        if not target_match:
            continue
        pager_link = page.locator(f'a[href*="{target_match.group(1)}"]')
        try:
            pager_link.click(timeout=timeout_ms, force=True, no_wait_after=True)
            page.wait_for_function(
                "marker => document.body.innerText.includes(marker)",
                arg=f"Page {page_number} of",
                timeout=timeout_ms,
            )
            page.wait_for_timeout(500)
        except Exception:
            try:
                page.get_by_text(str(page_number)).click(timeout=timeout_ms)
                page.wait_for_timeout(500)
            except Exception:
                continue
        html = page.content()
        html_pages.append(html)
        (raw_dir / f"attendance_page_{page_number}.html").write_text(html, encoding="utf-8")

    return html_pages


def scrape_current_page(page, output_root: Path, timeout_ms: int = 60000):
    meeting_url = page.url
    slug = slug_from_url(meeting_url)
    out_dir = output_root / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"

    try:
        click_attendance_tab(page, "Attendance", timeout_ms)
    except Exception as exc:
        print(f"Could not open Attendance tab: {exc}")

    html_pages = collect_pages(page, DEFAULT_SECTION_SPECS[0].title, timeout_ms, raw_dir)

    records: List[MeetingAttendanceRecord] = []
    for html in html_pages:
        records.extend(extract_section_records(html, meeting_url, DEFAULT_SECTION_SPECS))

    # dedupe simple
    unique = {}
    for r in records:
        key = (r.section_title, r.person_name_key, r.status_code)
        if key not in unique:
            unique[key] = r
    records = list(unique.values())

    attendance_frame = to_dataframe(records)
    if not attendance_frame.empty:
        attendance_frame.sort_values(by=["section_title", "status_code", "person_name"], inplace=True)
    attendance_frame.to_csv(out_dir / "attendance.csv", index=False)

    if not records:
        expected_names = []
    else:
        expected_names = [r.person_name for r in records]

    meeting_title = records[0].meeting_title if records else ""
    meeting_date = records[0].meeting_date if records else None
    comparison_rows = []
    # reuse build_expected_comparison if available; otherwise build minimal
    try:
        from src.monitoring.meeting_attendance import build_expected_comparison

        comparison_rows = build_expected_comparison(
            meeting_url=meeting_url,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            attendance_records=records,
            expected_names=expected_names,
        )
    except Exception:
        pass

    if comparison_rows:
        to_dataframe(comparison_rows).to_csv(out_dir / "comparison.csv", index=False)

    manifest = {
        "meeting_url": meeting_url,
        "meeting_title": meeting_title,
        "meeting_date": meeting_date,
        "attendance_count": int((attendance_frame["status_code"] == "attended").sum()) if not attendance_frame.empty else 0,
        "apology_count": int((attendance_frame["status_code"] == "apology").sum()) if not attendance_frame.empty else 0,
        "absent_count": int((attendance_frame["status_code"] == "absent").sum()) if not attendance_frame.empty else 0,
        "generated_at": date.today().isoformat(),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, default=str, indent=2), encoding="utf-8")
    print(f"Saved attendance to {out_dir}")


def main():
    output_root = Path("output") / "meeting_attendance"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-GB")
        page = context.new_page()
        page.goto("https://birmingham.cmis.uk.com/birmingham/Committee.aspx")
        print("Browser opened. Please log in if required and navigate to a meeting page.")
        print("When ready, press Enter here to scrape the current page. Type 'done' and Enter to finish.")
        while True:
            cmd = input("Ready> ").strip()
            if cmd.lower() in ("done", "exit", "quit"):
                break
            try:
                scrape_current_page(page, output_root)
            except Exception as exc:
                print(f"Extraction failed: {exc}")
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
