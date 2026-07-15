"""Driver: enumerate CMIS meeting pages and run attendance extractor in series.

Usage: python scripts/run_meeting_attendance_batch.py [--before YYYY-MM-DD] [--output-root output/meeting_attendance] [--sample N]

This script is polite: it pauses between runs and runs headless by default.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import List

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sl_core"))

from src.monitoring.meeting_attendance import (
    AttendanceSectionSpec,
    MeetingAttendanceRecord,
    build_expected_comparison,
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

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sl_core"))

try:
    from scripts.scrape_cmis_meeting_attendance import scrape_meeting_attendance, DEFAULT_SECTION_SPECS
except Exception:
    # fallback import path when executed as module
    from scrape_cmis_meeting_attendance import scrape_meeting_attendance, DEFAULT_SECTION_SPECS  # type: ignore

DEFAULT_MEETINGS_INDEX = "https://birmingham.cmis.uk.com/birmingham/Meetings.aspx"
DEFAULT_COMMITTEES_INDEX = "https://birmingham.cmis.uk.com/birmingham/Committee.aspx"


def extract_committee_links(index_html: str) -> List[str]:
    soup = BeautifulSoup(index_html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/Committee/" in href and not href.endswith("Committee.aspx"):
            links.append(href)
    # make unique preserving order
    return list(dict.fromkeys(links))


def extract_meetings_from_committee(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    meetings = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "ViewMeetingPublic" in href or "/Meetings/tabid" in href or "/Meeting/" in href:
            meetings.append(href)
    return list(dict.fromkeys(meetings))


def fetch_meetings_index(url: str, timeout: int = 30) -> str:
    session = requests.Session()
    session.headers.update({"User-Agent": "BCC_Monitoring/1.0 (meeting enumerator)"})
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_meeting_links(index_html: str) -> List[dict]:
    soup = BeautifulSoup(index_html, "lxml")
    meetings = []
    # CMIS index typically lists rows with a date and a link to ViewMeetingPublic
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "ViewMeetingPublic" not in href and "/Meetings/" not in href:
            continue
        text = anchor.get_text(" ", strip=True)
        # Try to find a neighbouring date cell
        parent = anchor.parent
        meeting_date = None
        for sibling in parent.find_all_next(text=True, limit=6):
            txt = sibling.strip()
            try:
                # common formats: 1 January 2025
                dt = datetime.strptime(txt, "%d %B %Y")
                meeting_date = dt.date()
                break
            except Exception:
                continue

        meetings.append({"url": href, "title": text, "date": meeting_date})
    # Deduplicate by url
    seen = set()
    uniq = []
    for m in meetings:
        if m["url"] in seen:
            continue
        seen.add(m["url"])
        uniq.append(m)
    return uniq


def normalize_url(href: str) -> str:
    if href.startswith("http"):
        return href
    return f"https://birmingham.cmis.uk.com{href}" if href.startswith("/") else f"https://birmingham.cmis.uk.com/birmingham/{href}"


def _click_attendance_tab(page, tab_title: str, timeout_ms: int) -> None:
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


def _extract_pager_targets(html: str, section_title: str) -> List[tuple]:
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


def _collect_pages(page, section_title: str, timeout_ms: int, raw_dir: Path) -> List[str]:
    html_pages = []
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
        try:
            pager_link.click(timeout=timeout_ms, force=True, no_wait_after=True)
            page.wait_for_function(
                "marker => document.body.innerText.includes(marker)",
                arg=f"Page {page_number} of",
                timeout=timeout_ms,
            )
            page.wait_for_timeout(500)
        except Exception:
            # try clicking by text
            try:
                page.get_by_text(str(page_number)).click(timeout=timeout_ms)
                page.wait_for_timeout(500)
            except Exception:
                continue
        html = page.content()
        html_pages.append(html)
        (raw_dir / f"attendance_page_{page_number}.html").write_text(html, encoding="utf-8")

    return html_pages


def slug_from_url(url: str) -> str:
    return url.rstrip("/\n\r").split("/")[-1].replace(".aspx", "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch run meeting attendance extraction")
    parser.add_argument("--before", default="2025-12-01", help="Include meetings before this date (YYYY-MM-DD)")
    parser.add_argument("--index-url", default=DEFAULT_MEETINGS_INDEX, help="CMIS meetings index URL")
    parser.add_argument("--output-root", default=str(Path("output") / "meeting_attendance"), help="Root output folder")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds to wait between runs")
    parser.add_argument("--timeout-ms", type=int, default=60000, help="Per-meeting navigation timeout in ms")
    parser.add_argument("--headed", action="store_true", help="Run browser headed for debugging")
    parser.add_argument("--sample", type=int, default=0, help="Run only the first N meetings (for testing)")
    args = parser.parse_args()

    cutoff = datetime.strptime(args.before, "%Y-%m-%d").date()
    index_html = fetch_meetings_index(args.index_url)
    meetings = extract_meeting_links(index_html)

    # If the meetings index doesn't yield public meeting links, enumerate committee pages
    if not meetings:
        print("No meeting links found on the Meetings index; enumerating committee pages...")
        committee_index_html = fetch_meetings_index(DEFAULT_COMMITTEES_INDEX)
        committee_links = extract_committee_links(committee_index_html)
        meetings_found = []
        for cl in committee_links:
            c_url = normalize_url(cl)
            try:
                resp = requests.get(c_url, timeout=30)
                resp.raise_for_status()
                for mlink in extract_meetings_from_committee(resp.text):
                    meetings_found.append({"url": mlink, "title": "", "date": None})
            except Exception as exc:
                print(f" -> failed to fetch committee {c_url}: {exc}")
        # dedupe
        seen = set()
        meetings = []
        for m in meetings_found:
            if m["url"] in seen:
                continue
            seen.add(m["url"])
            meetings.append(m)

    # normalize and filter
    filtered = []
    for m in meetings:
        url = normalize_url(m["url"])
        mdate = m.get("date")
        if mdate is None:
            # attempt to parse a meeting id from url and include conservatively
            filtered.append({"url": url, "date": None, "title": m.get("title")})
            continue
        if mdate < cutoff:
            filtered.append({"url": url, "date": mdate, "title": m.get("title")})

    if args.sample and args.sample > 0:
        filtered = filtered[: args.sample]

    print(f"Found {len(filtered)} meetings to process (before {cutoff})")

    # If still empty, try a JS-enabled discovery using Playwright
    if not filtered:
        print("Attempting JS-based discovery of meeting links via Playwright...")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-GB")
            page = ctx.new_page()
            try:
                try:
                    page.goto(args.index_url, wait_until="networkidle", timeout=60000)
                except Exception:
                    # fallback to domcontentloaded and allow manual interaction/login
                    try:
                        page.goto(args.index_url, wait_until="domcontentloaded", timeout=60000)
                    except Exception:
                        pass
                page.wait_for_timeout(1000)
                anchors = page.locator('a[href*="ViewMeetingPublic"], a[href*="/Meeting/"]')
                urls = set()
                for i in range(anchors.count()):
                    try:
                        href = anchors.nth(i).get_attribute("href") or ""
                        if href:
                            urls.add(normalize_url(href))
                    except Exception:
                        continue

                # Also try clicking 'more...' links to expand hidden meetings
                more_links = page.get_by_text("more...", exact=False)
                for idx in range(more_links.count()):
                    try:
                        more_links.nth(idx).click()
                        page.wait_for_timeout(300)
                    except Exception:
                        continue
                anchors = page.locator('a[href*="ViewMeetingPublic"], a[href*="/Meeting/"]')
                for i in range(anchors.count()):
                    try:
                        href = anchors.nth(i).get_attribute("href") or ""
                        if href:
                            urls.add(normalize_url(href))
                    except Exception:
                        continue

                meetings = [{"url": u, "title": "", "date": None} for u in sorted(urls)]
                if args.sample and args.sample > 0:
                    meetings = meetings[: args.sample]
                filtered = meetings
                print(f"Playwright discovered {len(filtered)} meeting links")
            finally:
                ctx.close()
                browser.close()

    for i, meeting in enumerate(filtered, start=1):
        url = meeting["url"]
        print(f"[{i}/{len(filtered)}] Processing {url} (date={meeting.get('date')})")
        out_dir = Path(args.output_root) / slug_from_url(url)
        try:
            manifest = scrape_meeting_attendance(
                meeting_url=url,
                output_dir=out_dir,
                expected_roster_csv=None,
                expected_name_column="councillor_name",
                attendance_tab_title="Attendance",
                section_specs=DEFAULT_SECTION_SPECS,
                timeout_ms=args.timeout_ms,
                headed=args.headed,
            )
            print(f" -> OK: {manifest.get('attendance_count', 0)} attended")
        except Exception as exc:
            print(f" -> ERROR for {url}: {exc}")
        time.sleep(args.delay)


if __name__ == "__main__":
    main()
