"""Scrape Birmingham's May 2022 local government election results.

This reuses the 2026 election parsing helpers where possible but adapts the
index and result page structure for the 2022 directory-record pages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sl_core"))
from utils import global_variables as gv  # noqa: E402

from scripts.scrape_election_results_2026 import (  # noqa: E402
    ElectionStandingRecord,
    PartyHistoryRecord,
    WardSummaryRecord,
    build_person_id,
    ensure_output_dirs,
    extract_candidate_rows,
    extract_text_after_heading,
    normalise_whitespace,
    parse_elected_candidates,
    parse_int,
    slugify_url,
    write_csv,
)


DEFAULT_START_URL = "https://www.birmingham.gov.uk/info/50381/past_election_results/2558/local_government_election_results_may_2022"
DEFAULT_ELECTION_DATE = "2022-05-05"


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BCC_Monitoring/1.0 (+polite 2022 election scraper)",
            "Accept-Language": "en-GB,en;q=0.9",
        }
    )
    return session


def fetch_page(session: requests.Session, url: str, timeout: int) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def collect_ward_links(index_html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(index_html, "lxml")
    links: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "/directory_record/" not in href or not href.endswith("_ward_results"):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links


def canonical_ward_name(page_title: str) -> str:
    value = normalise_whitespace(page_title)
    value = re.sub(r"\s+Ward Results$", " Ward", value, flags=re.I)
    return value


def _name_key(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9']+", normalise_whitespace(value).lower())
    return "|".join(sorted(parts))


def load_canonical_names(output_dir: Path) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for filename in ("people.csv", "councillors.csv"):
        path = output_dir / filename
        if not path.exists() or path.stat().st_size == 0:
            continue
        frame = pd.read_csv(path)
        for column in ("person_name", "councillor_name"):
            if column in frame.columns:
                for value in frame[column].dropna().astype(str):
                    canonical = normalise_whitespace(value)
                    key = _name_key(canonical)
                    existing = names.get(key)
                    if existing is None:
                        names[key] = canonical
                        continue
                    existing_has_comma = "," in existing
                    candidate_has_comma = "," in canonical
                    if candidate_has_comma and not existing_has_comma:
                        names[key] = canonical
    return names


def canonicalize_2022_name(raw_name: str, known_names: Dict[str, str]) -> str:
    candidate = normalise_whitespace(raw_name)
    key = _name_key(candidate)
    if key in known_names:
        return known_names[key]

    parts = candidate.split()
    if len(parts) > 1:
        reversed_candidate = normalise_whitespace(" ".join(parts[1:] + [parts[0]]))
        reversed_key = _name_key(reversed_candidate)
        if reversed_key in known_names:
            return known_names[reversed_key]
    return candidate


def parse_ward_page_2022(html: str, source_url: str) -> Dict[str, object]:
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find(re.compile(r"^h1$"))
    page_title = normalise_whitespace(h1.get_text(" ", strip=True)) if h1 else ""
    ward_name = canonical_ward_name(page_title)
    page_text = soup.get_text("\n", strip=True)

    elected_candidates = parse_elected_candidates(soup)
    elected_names = {candidate["person_name"].lower() for candidate in elected_candidates}
    candidate_rows = extract_candidate_rows(soup)

    total_votes_cast = sum(int(row["votes_received"]) for row in candidate_rows)
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
                "election_date": DEFAULT_ELECTION_DATE,
                "party_name": party_name,
                "votes_received": votes_received,
                "is_elected": is_elected,
                "source_url": source_url,
            }
        )

    return {
        "ward_name": ward_name,
        "election_date": DEFAULT_ELECTION_DATE,
        "page_last_updated": None,
        "number_of_councillors_elected": len(elected_candidates) or None,
        "turnout_percent": None,
        "total_potential_voters": None,
        "candidates": candidates,
        "elected_candidates": elected_candidates,
        "page_text": page_text,
        "source_url": source_url,
        "total_votes_cast": total_votes_cast,
    }


def normalise_ward_candidates(candidates: Sequence[Dict[str, object]], known_names: Dict[str, str]) -> List[Dict[str, object]]:
    normalised: List[Dict[str, object]] = []
    for candidate in candidates:
        person_name = canonicalize_2022_name(str(candidate["person_name"]), known_names)
        normalised.append({**candidate, "person_name": person_name, "person_id": build_person_id(person_name)})
    return normalised


def scrape_ward_urls(session: requests.Session, start_url: str, timeout: int, max_wards: Optional[int]) -> List[str]:
    start_html = fetch_page(session, start_url, timeout)
    ward_urls = collect_ward_links(start_html, start_url)
    if max_wards is not None:
        ward_urls = ward_urls[:max_wards]
    return ward_urls


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Birmingham May 2022 election results")
    parser.add_argument("--start-url", default=DEFAULT_START_URL, help="2022 results index page")
    parser.add_argument("--output-dir", default=str(gv.DIRECTORIES["output_dir"] / "election_2022_may"), help="Directory for CSV outputs")
    parser.add_argument("--timeout", type=int, default=gv.DEFAULT_TIMEOUT_MS // 1000, help="HTTP timeout in seconds")
    parser.add_argument("--max-wards", type=int, default=None, help="Limit the number of ward pages to scrape")
    parser.add_argument("--single-url", default=None, help="Scrape a single ward result page")
    args = parser.parse_args()

    output_paths = ensure_output_dirs(Path(args.output_dir))
    session = build_session()
    known_names = load_canonical_names(Path(gv.DIRECTORIES["output_dir"]) / "current")

    ward_urls = [args.single_url] if args.single_url else scrape_ward_urls(session, args.start_url, args.timeout, args.max_wards)

    people_records: Dict[str, Dict[str, object]] = {}
    party_history_records: List[PartyHistoryRecord] = []
    election_standing_records: List[ElectionStandingRecord] = []
    ward_summary_records: List[WardSummaryRecord] = []

    for index, ward_url in enumerate(ward_urls, start=1):
        print(f"[{index}/{len(ward_urls)}] Fetching {ward_url}")
        html = fetch_page(session, ward_url, args.timeout)
        raw_path = output_paths["raw"] / f"{slugify_url(ward_url)}.html"
        raw_path.write_text(html, encoding="utf-8")

        ward_data = parse_ward_page_2022(html, ward_url)
        ward_data["candidates"] = normalise_ward_candidates(ward_data["candidates"], known_names)
        print(f"  -> {ward_data['ward_name']}: {len(ward_data['candidates'])} candidates")

        for candidate in ward_data["candidates"]:
            person_id = str(candidate["person_id"])
            person_name = str(candidate["person_name"])
            party_name = str(candidate["party_name"])
            election_date = str(candidate["election_date"])
            votes_received = int(candidate["votes_received"])
            is_elected = bool(candidate["is_elected"])
            source_url = str(candidate["source_url"])

            people_records.setdefault(
                person_id,
                {
                    "person_id": person_id,
                    "person_name": person_name,
                    "first_seen_ward": ward_data["ward_name"],
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
                    ward_name=ward_data["ward_name"],
                    votes_received=votes_received,
                    is_elected=is_elected,
                    party_name=party_name,
                    source_url=source_url,
                )
            )

        ward_summary_records.append(
            WardSummaryRecord(
                election_date=ward_data["election_date"],
                ward_name=ward_data["ward_name"],
                number_of_candidates=len(ward_data["candidates"]),
                total_votes_cast=ward_data["total_votes_cast"],
                total_potential_voters=None,
                turnout_percent=None,
                number_of_councillors_elected=ward_data["number_of_councillors_elected"],
                source_url=ward_url,
            )
        )

    people_rows = sorted(people_records.values(), key=lambda row: (row["person_name"], row["person_id"]))
    write_csv(output_paths["people"], people_rows)
    write_csv(output_paths["party_history"], party_history_records)
    write_csv(output_paths["election_standings"], election_standing_records)
    write_csv(output_paths["ward_summaries"], ward_summary_records)

    manifest = {
        "start_url": args.start_url,
        "single_url": args.single_url,
        "ward_count": len(ward_urls),
        "people_count": len(people_rows),
        "party_history_count": len(party_history_records),
        "election_standing_count": len(election_standing_records),
        "ward_summary_count": len(ward_summary_records),
        "generated_at": date.today().isoformat(),
        "election_date": DEFAULT_ELECTION_DATE,
    }
    output_paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
