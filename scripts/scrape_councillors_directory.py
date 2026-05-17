"""Scrape the Birmingham councillors directory and profile pages.

This produces a lightweight current-councillor directory and a link table that
can be joined against the election results dataset.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sl_core"))
from utils import global_variables as gv  # noqa: E402


DEFAULT_DIRECTORY_URL = "https://www.birmingham.gov.uk/councillors/name"


@dataclass(frozen=True)
class CouncillorRecord:
    councillor_name: str
    ward_name: str
    party_name: str
    councillor_url: str
    councillor_id: Optional[str]
    page_last_updated: Optional[str]
    joined_council: Optional[str] = None
    office_expires: Optional[str] = None
    council_service: Optional[str] = None
    telephone: Optional[str] = None
    email: Optional[str] = None
    has_surgery: bool = False
    surgery_summary: Optional[str] = None
    register_of_interests_url: Optional[str] = None


@dataclass(frozen=True)
class CouncillorLinkRecord:
    person_id: str
    person_name: str
    ward_name: str
    status: str
    councillor_url: Optional[str]
    councillor_id: Optional[str]
    council_service: Optional[str]
    page_last_updated: Optional[str]
    source: str


def normalise_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def build_person_id(person_name: str) -> str:
    import hashlib

    return hashlib.sha1(normalise_whitespace(person_name).lower().encode("utf-8")).hexdigest()[:16]


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BCC_Monitoring/1.0 (+polite councillor directory scraper)",
            "Accept-Language": "en-GB,en;q=0.9",
        }
    )
    return session


def fetch_html(session: requests.Session, url: str, timeout: int = 30) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def extract_profile_links(directory_html: str, base_url: str) -> List[Tuple[str, str, str, str]]:
    soup = BeautifulSoup(directory_html, "lxml")
    links: List[Tuple[str, str, str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not re.search(r"/councillors/\d+/", href):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        text = normalise_whitespace(anchor.get_text(" ", strip=True))
        if "Ward:" not in text or "Party:" not in text:
            continue
        seen.add(absolute)
        links.append((absolute, text, href, anchor.get("href", "")))
    return links


def parse_directory_entry(text: str) -> Tuple[str, str, str]:
    name_match = re.match(r"^(.*?)\s+Ward:\s+(.*?)\s+Party:\s+(.*)$", text)
    if not name_match:
        return text, "", ""
    return normalise_whitespace(name_match.group(1)), normalise_whitespace(name_match.group(2)), normalise_whitespace(name_match.group(3))


def parse_councillor_profile(html: str, url: str) -> CouncillorRecord:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)

    h1 = soup.find(re.compile(r"^h1$"))
    page_title = normalise_whitespace(h1.get_text(" ", strip=True)) if h1 else ""
    councillor_name = page_title.replace("Councillor ", "").strip() if page_title else ""

    ward = ""
    party = ""
    ward_party_match = re.search(r"Ward:\s*(.*?)\s+Party:\s*(.*?)(?:\n|$)", text, re.S)
    if ward_party_match:
        ward = normalise_whitespace(ward_party_match.group(1))
        party = normalise_whitespace(ward_party_match.group(2))
    else:
        ward_match = re.search(r"Ward:\s*([^\n]+)", text)
        party_match = re.search(r"Party:\s*([^\n]+)", text)
        if ward_match:
            ward = normalise_whitespace(ward_match.group(1))
        if party_match:
            party = normalise_whitespace(party_match.group(1))

    joined = None
    office_expires = None
    service = None
    telephone = None
    email = None
    has_surgery = False
    surgery_summary = None
    register_url = None

    for line in text.splitlines():
        line = normalise_whitespace(line)
        if line.startswith("Joined council:"):
            joined = normalise_whitespace(line.split(":", 1)[1])
        elif line.startswith("Office expires:"):
            office_expires = normalise_whitespace(line.split(":", 1)[1])
        elif line.startswith("Council service:"):
            service = normalise_whitespace(line.split(":", 1)[1])
        elif line.startswith("Telephone:"):
            telephone = normalise_whitespace(line.split(":", 1)[1])
        elif line.startswith("Email:"):
            email = normalise_whitespace(line.split(":", 1)[1])

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "Statutory Register of Interests" in normalise_whitespace(anchor.get_text(" ", strip=True)):
            register_url = urljoin(url, href)

    if "Advice surgeries" in text or "surgeries" in text.lower():
        has_surgery = True
        match = re.search(r"\|\s*(.*?)\s*\|\s*(.*?)\s*\|", text, re.S)
        if match:
            surgery_summary = f"{normalise_whitespace(match.group(1))} @ {normalise_whitespace(match.group(2))}"

    councillor_id = None
    match = re.search(r"/councillors/(\d+)/", url)
    if match:
        councillor_id = match.group(1)

    return CouncillorRecord(
        councillor_name=councillor_name,
        ward_name=ward,
        party_name=party,
        councillor_url=url,
        councillor_id=councillor_id,
        page_last_updated=_parse_page_last_updated(text),
        joined_council=joined,
        office_expires=office_expires,
        council_service=service,
        telephone=telephone,
        email=email,
        has_surgery=has_surgery,
        surgery_summary=surgery_summary,
        register_of_interests_url=register_url,
    )


def _parse_page_last_updated(text: str) -> Optional[str]:
    match = re.search(r"Page last updated:\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", text)
    if not match:
        return None
    try:
        from dateutil import parser as date_parser

        return date_parser.parse(match.group(1), fuzzy=True).date().isoformat()
    except Exception:
        return None


def load_election_people(output_dir: Path) -> List[Dict[str, object]]:
    people_path = output_dir / "people.csv"
    if not people_path.exists() or people_path.stat().st_size == 0:
        return []
    return pd.read_csv(people_path).to_dict(orient="records")


def build_link_records(
    directory_records: Sequence[CouncillorRecord],
    election_people: Sequence[Dict[str, object]],
) -> List[CouncillorLinkRecord]:
    current_lookup = {record.councillor_name.lower(): record for record in directory_records}
    link_records: List[CouncillorLinkRecord] = []
    seen_people = set()

    for person in election_people:
        person_name = normalise_whitespace(str(person.get("person_name", "")))
        ward_name = normalise_whitespace(str(person.get("first_seen_ward", "")))
        person_id = str(person.get("person_id", "")) or build_person_id(person_name)
        profile = current_lookup.get(person_name.lower())
        seen_people.add(person_name.lower())
        if profile:
            link_records.append(
                CouncillorLinkRecord(
                    person_id=person_id,
                    person_name=person_name,
                    ward_name=ward_name,
                    status="current_councillor",
                    councillor_url=profile.councillor_url,
                    councillor_id=profile.councillor_id,
                    council_service=profile.council_service,
                    page_last_updated=profile.page_last_updated,
                    source="election_people + councillors_directory",
                )
            )
        else:
            link_records.append(
                CouncillorLinkRecord(
                    person_id=person_id,
                    person_name=person_name,
                    ward_name=ward_name,
                    status="not_listed_currently",
                    councillor_url=None,
                    councillor_id=None,
                    council_service=None,
                    page_last_updated=None,
                    source="election_people_only",
                )
            )

    for record in directory_records:
        if record.councillor_name.lower() in seen_people:
            continue
        link_records.append(
            CouncillorLinkRecord(
                person_id=build_person_id(record.councillor_name),
                person_name=record.councillor_name,
                ward_name=record.ward_name,
                status="directory_only_current",
                councillor_url=record.councillor_url,
                councillor_id=record.councillor_id,
                council_service=record.council_service,
                page_last_updated=record.page_last_updated,
                source="councillors_directory_only",
            )
        )

    return link_records


def write_csv(path: Path, records: Sequence[object]) -> None:
    if not records:
        path.write_text("", encoding="utf-8")
        return
    frame = pd.DataFrame([asdict(record) if hasattr(record, "__dataclass_fields__") else record for record in records])
    frame.to_csv(path, index=False)


def ensure_output_dirs(base_dir: Path) -> Dict[str, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)
    return {
        "base": base_dir,
        "raw": base_dir / "raw",
        "profiles": base_dir / "profiles",
        "manifest": base_dir / "manifest.json",
        "councillors": base_dir / "councillors.csv",
        "links": base_dir / "councillor_links.csv",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape the Birmingham councillors directory")
    parser.add_argument("--directory-url", default=DEFAULT_DIRECTORY_URL, help="Councillor listing page")
    parser.add_argument(
        "--output-dir",
        default=str(gv.DIRECTORIES["output_dir"] / "current"),
        help="Directory for outputs (canonical: output/current)",
    )
    parser.add_argument("--election-output-dir", default=str(gv.ELECTION_OUTPUT_DIR), help="Existing election output directory for person joins")
    args = parser.parse_args()

    output_paths = ensure_output_dirs(Path(args.output_dir))
    output_paths["raw"].mkdir(parents=True, exist_ok=True)
    output_paths["profiles"].mkdir(parents=True, exist_ok=True)

    session = build_session()
    directory_html = fetch_html(session, args.directory_url)
    (output_paths["raw"] / "councillors_directory.html").write_text(directory_html, encoding="utf-8")

    links = extract_profile_links(directory_html, args.directory_url)
    directory_records: List[CouncillorRecord] = []
    for index, (profile_url, _, _, _) in enumerate(links, start=1):
        print(f"[{index}/{len(links)}] Fetching {profile_url}")
        profile_html = fetch_html(session, profile_url)
        profile_path = output_paths["profiles"] / f"{re.sub(r'[^a-zA-Z0-9_-]+', '_', profile_url.split('/')[-1])}.html"
        profile_path.write_text(profile_html, encoding="utf-8")
        directory_records.append(parse_councillor_profile(profile_html, profile_url))

    election_people = load_election_people(Path(args.election_output_dir))
    link_records = build_link_records(directory_records, election_people)

    write_csv(output_paths["councillors"], directory_records)
    write_csv(output_paths["links"], link_records)

    # optional: write into DB with change logging
    if "--write-db" in " ".join(sys.argv):
        try:
            from src.monitoring.ingest import write_councillors_links_to_db

            print("Writing councillor links to DB...")
            write_councillors_links_to_db(output_paths["links"], db_path=None, dry_run=False)
        except Exception as e:
            print(f"Failed to write to DB: {e}")

    manifest = {
        "directory_url": args.directory_url,
        "councillor_count": len(directory_records),
        "link_count": len(link_records),
        "generated_at": date.today().isoformat(),
    }
    output_paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
