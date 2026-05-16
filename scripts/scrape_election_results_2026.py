"""Scrape Birmingham 2026 ward election results from rendered pages.

The script is intentionally polite: it crawls from the ward index page,
adds a delay between requests, caches responses during development, and
writes normalized CSV outputs that can be published separately via GitHub Pages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import urljoin, urlparse
import sys

import pandas as pd
import requests_cache
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sl_core"))
from utils import global_variables as gv  # noqa: E402
from scripts.compile_unified_dataset import merge_all_outputs  # noqa: E402


DEFAULT_START_URL = gv.ELECTION_START_URL


@dataclass(frozen=True)
class PartyHistoryRecord:
    person_id: str
    person_name: str
    party_name: str
    effective_from: str
    effective_to: str
    is_current: bool
    source_url: str


@dataclass(frozen=True)
class ElectionStandingRecord:
    person_id: str
    person_name: str
    election_date: str
    ward_name: str
    votes_received: int
    is_elected: bool
    party_name: str
    source_url: str


@dataclass(frozen=True)
class WardSummaryRecord:
    election_date: str
    ward_name: str
    number_of_candidates: int
    total_votes_cast: int
    total_potential_voters: Optional[int]
    turnout_percent: Optional[float]
    number_of_councillors_elected: Optional[int]
    source_url: str


@dataclass(frozen=True)
class WardPageData:
    ward_name: str
    election_date: str
    page_last_updated: Optional[str]
    number_of_councillors_elected: Optional[int]
    turnout_percent: Optional[float]
    total_potential_voters: Optional[int]
    candidates: List[Dict[str, object]]
    elected_candidates: List[Dict[str, str]]


def normalise_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def build_person_id(person_name: str) -> str:
    canonical = normalise_whitespace(person_name).lower()
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def parse_int(value: str) -> Optional[int]:
    cleaned = re.sub(r"[^0-9]", "", value or "")
    return int(cleaned) if cleaned else None


def canonical_ward_name(page_title: str) -> str:
    match = re.match(r"^(.*?)\s+Ward results\s+\d{4}$", normalise_whitespace(page_title), re.I)
    if match:
        return f"{match.group(1)} Ward"
    return normalise_whitespace(page_title)


def parse_election_date(text: str) -> Optional[str]:
    match = re.search(r"poll took place on\s+([^\.]+)\.", text, re.I)
    if not match:
        return None
    try:
        return date_parser.parse(match.group(1), fuzzy=True).date().isoformat()
    except Exception:
        return None


def parse_page_last_updated(text: str) -> Optional[str]:
    match = re.search(r"Page last updated:\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", text, re.I)
    if not match:
        return None
    try:
        return date_parser.parse(match.group(1), fuzzy=True).date().isoformat()
    except Exception:
        return None


def parse_turnout(text: str) -> Optional[float]:
    match = re.search(r"Turnout:\s*([0-9]+(?:\.[0-9]+)?)%", text, re.I)
    return float(match.group(1)) if match else None


def parse_elected_count(text: str) -> Optional[int]:
    match = re.search(r"number of councillors elected for this ward is\s+(\d+)", text, re.I)
    return int(match.group(1)) if match else None


def extract_text_after_heading(soup: BeautifulSoup, heading_text: str) -> List[str]:
    heading = None
    for candidate in soup.find_all(re.compile(r"^h[1-6]$")):
        if normalise_whitespace(candidate.get_text(" ", strip=True)).lower() == heading_text.lower():
            heading = candidate
            break
    if heading is None:
        return []

    lines: List[str] = []
    for sibling in heading.next_siblings:
        if getattr(sibling, "name", None) and re.match(r"^h[1-6]$", sibling.name or "", re.I):
            break
        if hasattr(sibling, "get_text"):
            text = normalise_whitespace(sibling.get_text("\n", strip=True))
            if text:
                lines.extend([line.strip() for line in text.splitlines() if line.strip()])
        elif isinstance(sibling, str):
            text = normalise_whitespace(sibling)
            if text:
                lines.extend([line.strip() for line in text.splitlines() if line.strip()])
    return lines


def parse_elected_candidates(soup: BeautifulSoup) -> List[Dict[str, str]]:
    lines = extract_text_after_heading(soup, "Candidates elected")
    candidates: List[Dict[str, str]] = []
    for line in lines:
        match = re.match(r"^(.*?)\s*-\s*(.*?)\s*-\s*(.*?)$", normalise_whitespace(line))
        if not match:
            continue
        candidates.append(
            {
                "person_name": normalise_whitespace(match.group(1)),
                "party_name": normalise_whitespace(match.group(2)),
                "status": normalise_whitespace(match.group(3)),
            }
        )
    return candidates


def extract_candidate_rows(soup: BeautifulSoup) -> List[Dict[str, object]]:
    candidate_rows: List[Dict[str, object]] = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [normalise_whitespace(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
            if len(cells) != 3:
                continue
            if not cells[0] or cells[0].lower() in {"candidate", "name"}:
                continue
            votes = parse_int(cells[2])
            if votes is None:
                continue
            rows.append({"person_name": cells[0], "party_name": cells[1], "votes_received": votes})
        if len(rows) >= 2:
            candidate_rows = rows
            break
    return candidate_rows


def parse_ward_page(html: str, source_url: str) -> WardPageData:
    soup = BeautifulSoup(html, "lxml")
    page_title = ""
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        heading_text = normalise_whitespace(heading.get_text(" ", strip=True))
        if "Ward results" in heading_text:
            page_title = heading_text
            break
    if not page_title:
        title_tag = soup.find(re.compile(r"^h1$"))
        page_title = normalise_whitespace(title_tag.get_text(" ", strip=True)) if title_tag else ""
    ward_name = canonical_ward_name(page_title)

    page_text = soup.get_text("\n", strip=True)
    election_date = parse_election_date(page_text) or "2026-05-07"
    page_last_updated = parse_page_last_updated(page_text)
    elected_count = parse_elected_count(page_text)
    turnout_percent = parse_turnout(page_text)
    elected_candidates = parse_elected_candidates(soup)
    elected_names = {candidate["person_name"].lower() for candidate in elected_candidates}
    candidate_rows = extract_candidate_rows(soup)

    total_votes_cast = sum(int(row["votes_received"]) for row in candidate_rows)
    total_potential_voters: Optional[int] = None
    if turnout_percent and turnout_percent > 0:
        total_potential_voters = round(total_votes_cast / (turnout_percent / 100.0))

    candidates = []
    for row in candidate_rows:
        person_name = normalise_whitespace(str(row["person_name"]))
        party_name = normalise_whitespace(str(row["party_name"]))
        votes_received = int(row["votes_received"])
        is_elected = person_name.lower() in elected_names
        candidates.append(
            {
                "person_id": build_person_id(person_name),
                "person_name": person_name,
                "ward_name": ward_name,
                "election_date": election_date,
                "party_name": party_name,
                "votes_received": votes_received,
                "is_elected": is_elected,
                "source_url": source_url,
            }
        )

    return WardPageData(
        ward_name=ward_name,
        election_date=election_date,
        page_last_updated=page_last_updated,
        number_of_councillors_elected=elected_count,
        turnout_percent=turnout_percent,
        total_potential_voters=total_potential_voters,
        candidates=candidates,
        elected_candidates=elected_candidates,
    )


def collect_ward_links(index_html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(index_html, "lxml")
    links: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "/info/50385/election_2026_candidates/" not in href:
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links


def build_session(cache_dir: Path, use_cache: bool) -> requests_cache.CachedSession:
    if use_cache:
        session = requests_cache.CachedSession(
            cache_name=str(cache_dir / "http_cache"),
            backend="sqlite",
            expire_after=60 * 60 * 24,
        )
    else:
        session = requests_cache.CachedSession(backend="memory", expire_after=0)
    session.headers.update(
        {
            "User-Agent": "BCC_Monitoring/1.0 (+polite election-results scraper)",
            "Accept-Language": "en-GB,en;q=0.9",
        }
    )
    return session


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential_jitter(initial=2, max=20),
    stop=stop_after_attempt(3),
)
def fetch_page(session: requests_cache.CachedSession, url: str, timeout: int) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def write_csv(path: Path, records: Sequence[object]) -> None:
    if not records:
        path.write_text("", encoding="utf-8")
        return
    frame = pd.DataFrame([asdict(record) if hasattr(record, "__dataclass_fields__") else record for record in records])
    frame.to_csv(path, index=False)


def ensure_output_dirs(base_dir: Path) -> Dict[str, Path]:
    raw_dir = base_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return {
        "base": base_dir,
        "raw": raw_dir,
        "people": base_dir / "people.csv",
        "party_history": base_dir / "party_history.csv",
        "election_standings": base_dir / "election_standings.csv",
        "ward_summaries": base_dir / "ward_summaries.csv",
        "manifest": base_dir / "manifest.json",
    }


def slugify_url(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").split("/")[-1]
    if not slug:
        slug = "index"
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", slug)


def scrape_ward_urls(
    session: requests_cache.CachedSession,
    start_url: str,
    timeout: int,
    max_wards: Optional[int],
) -> List[str]:
    start_html = fetch_page(session, start_url, timeout)
    ward_urls = collect_ward_links(start_html, start_url)
    if max_wards is not None:
        ward_urls = ward_urls[:max_wards]
    return ward_urls


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Birmingham 2026 ward election results")
    parser.add_argument("--start-url", default=DEFAULT_START_URL, help="Ward index page to start from")
    parser.add_argument("--output-dir", default=str(gv.ELECTION_OUTPUT_DIR), help="Directory for CSV outputs")
    parser.add_argument("--delay", type=float, default=gv.DEFAULT_DELAY_MIN, help="Seconds to wait between ward requests")
    parser.add_argument("--timeout", type=int, default=gv.DEFAULT_TIMEOUT_MS // 1000, help="HTTP timeout in seconds")
    parser.add_argument("--max-wards", type=int, default=None, help="Limit the number of ward pages to scrape")
    parser.add_argument("--no-cache", action="store_true", help="Disable HTTP response caching")
    parser.add_argument("--single-url", default=None, help="Scrape one ward page directly instead of the index")
    args = parser.parse_args()

    output_paths = ensure_output_dirs(Path(args.output_dir))
    session = build_session(output_paths["base"], use_cache=not args.no_cache)

    if args.single_url:
        ward_urls = [args.single_url]
    else:
        ward_urls = scrape_ward_urls(session, args.start_url, args.timeout, args.max_wards)

    all_people: Dict[str, Dict[str, object]] = {}
    party_history_records: List[PartyHistoryRecord] = []
    election_standing_records: List[ElectionStandingRecord] = []
    ward_summary_records: List[WardSummaryRecord] = []

    for index, ward_url in enumerate(ward_urls, start=1):
        print(f"[{index}/{len(ward_urls)}] Fetching {ward_url}")
        html = fetch_page(session, ward_url, args.timeout)

        raw_path = output_paths["raw"] / f"{slugify_url(ward_url)}.html"
        raw_path.write_text(html, encoding="utf-8")

        ward_data = parse_ward_page(html, ward_url)
        print(f"  -> {ward_data.ward_name}: {len(ward_data.candidates)} candidates")

        for candidate in ward_data.candidates:
            person_id = str(candidate["person_id"])
            person_name = str(candidate["person_name"])
            party_name = str(candidate["party_name"])
            election_date = str(candidate["election_date"])
            votes_received = int(candidate["votes_received"])
            is_elected = bool(candidate["is_elected"])
            source_url = str(candidate["source_url"])

            all_people.setdefault(
                person_id,
                {
                    "person_id": person_id,
                    "person_name": person_name,
                    "first_seen_ward": ward_data.ward_name,
                    "source_url": source_url,
                },
            )

            party_history_records.append(
                PartyHistoryRecord(
                    person_id=person_id,
                    person_name=person_name,
                    party_name=party_name,
                    effective_from=election_date,
                    effective_to="",
                    is_current=True,
                    source_url=source_url,
                )
            )

            election_standing_records.append(
                ElectionStandingRecord(
                    person_id=person_id,
                    person_name=person_name,
                    election_date=election_date,
                    ward_name=ward_data.ward_name,
                    votes_received=votes_received,
                    is_elected=is_elected,
                    party_name=party_name,
                    source_url=source_url,
                )
            )

        ward_summary_records.append(
            WardSummaryRecord(
                election_date=ward_data.election_date,
                ward_name=ward_data.ward_name,
                number_of_candidates=len(ward_data.candidates),
                total_votes_cast=sum(int(candidate["votes_received"]) for candidate in ward_data.candidates),
                total_potential_voters=ward_data.total_potential_voters,
                turnout_percent=ward_data.turnout_percent,
                number_of_councillors_elected=ward_data.number_of_councillors_elected,
                source_url=ward_url,
            )
        )

        if args.delay > 0 and index < len(ward_urls):
            time.sleep(args.delay)

    people_records = sorted(all_people.values(), key=lambda row: (row["person_name"], row["person_id"]))

    write_csv(output_paths["people"], people_records)
    write_csv(output_paths["party_history"], party_history_records)
    write_csv(output_paths["election_standings"], election_standing_records)
    write_csv(output_paths["ward_summaries"], ward_summary_records)

    manifest = {
        "start_url": args.start_url,
        "single_url": args.single_url,
        "ward_count": len(ward_urls),
        "people_count": len(people_records),
        "party_history_count": len(party_history_records),
        "election_standing_count": len(election_standing_records),
        "ward_summary_count": len(ward_summary_records),
        "generated_at": date.today().isoformat(),
    }
    output_paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Done")
    print(json.dumps(manifest, indent=2))
    # If this run isn't explicitly a development run, merge into the canonical master dataset
    try:
        base = Path(args.output_dir)
        if "development" not in str(base):
            master_dir = Path(gv.DIRECTORIES["output_dir"]) / "current"
            print(f"Merging this run into master dataset at {master_dir}")
            merge_all_outputs(Path(gv.DIRECTORIES["output_dir"]), master_dir)
    except Exception as exc:  # pragma: no cover - best effort
        print(f"Warning: failed to merge run outputs into master dataset: {exc}")


if __name__ == "__main__":
    main()