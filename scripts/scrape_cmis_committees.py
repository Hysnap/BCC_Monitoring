"""Scrape the public Birmingham CMIS committee directory and public committee pages.

The goal is privacy-safe scaffolding: keep only public committee references,
committee page links, and public webcast/video links. Do not persist member,
attendance, or other person-level data yet.

Users will need to register for CMIS access to reach deeper meeting data.
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


DEFAULT_COMMITTEE_INDEX_URL = "https://birmingham.cmis.uk.com/birmingham/Committee.aspx"


@dataclass(frozen=True)
class CommitteeRecord:
    committee_name: str
    committee_url: str
    source_url: str
    notes: Optional[str] = None


@dataclass(frozen=True)
class CommitteeSourceRecord:
    committee_name: str
    committee_url: str
    source_url: str
    linked_url: str
    linked_title: Optional[str]
    link_type: str


def normalise_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BCC_Monitoring/1.0 (+privacy-safe CMIS committee scraper)",
            "Accept-Language": "en-GB,en;q=0.9",
        }
    )
    return session


def fetch_html(session: requests.Session, url: str, timeout: int = 30) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def extract_committees(index_html: str, base_url: str) -> List[CommitteeRecord]:
    soup = BeautifulSoup(index_html, "lxml")
    committees: List[CommitteeRecord] = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "/Committee/" not in href or href.endswith("Committee.aspx"):
            continue
        committee_name = normalise_whitespace(anchor.get_text(" ", strip=True))
        if not committee_name:
            continue
        committee_url = urljoin(base_url, href)
        key = (committee_name.lower(), committee_url)
        if key in seen:
            continue
        seen.add(key)
        committees.append(
            CommitteeRecord(
                committee_name=committee_name,
                committee_url=committee_url,
                source_url=base_url,
                notes="Public committee directory listing",
            )
        )
    return committees


def extract_source_links(html: str, committee_name: str, committee_url: str) -> List[CommitteeSourceRecord]:
    soup = BeautifulSoup(html, "lxml")
    source_links: List[CommitteeSourceRecord] = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = urljoin(committee_url, anchor["href"])
        linked_title = normalise_whitespace(anchor.get_text(" ", strip=True)) or None
        link_type = "source"

        if "public-i.tv" in href or "youtube.com" in href or "youtu.be" in href:
            link_type = "video"
        elif "cmis.uk.com" in href and "/Committee/" in href:
            link_type = "committee"
        elif "CMISRegistration" in href or "login.aspx" in href:
            link_type = "access"

        if link_type == "access":
            continue

        key = (href, linked_title or "", link_type)
        if key in seen:
            continue
        seen.add(key)
        source_links.append(
            CommitteeSourceRecord(
                committee_name=committee_name,
                committee_url=committee_url,
                source_url=committee_url,
                linked_url=href,
                linked_title=linked_title,
                link_type=link_type,
            )
        )

    return source_links


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
        "committees": base_dir / "committees.csv",
        "source_links": base_dir / "committee_source_links.csv",
        "manifest": base_dir / "manifest.json",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape the Birmingham CMIS committee directory")
    parser.add_argument("--index-url", default=DEFAULT_COMMITTEE_INDEX_URL, help="CMIS committee directory URL")
    parser.add_argument("--output-dir", default=str(gv.DIRECTORIES["output_dir"] / "cmis_committees"), help="Directory for outputs")
    parser.add_argument("--max-committees", type=int, default=None, help="Limit number of committee pages to inspect")
    args = parser.parse_args()

    output_paths = ensure_output_dirs(Path(args.output_dir))
    output_paths["raw"].mkdir(parents=True, exist_ok=True)

    session = build_session()
    index_html = fetch_html(session, args.index_url)
    (output_paths["raw"] / "committee_index.html").write_text(index_html, encoding="utf-8")

    committees = extract_committees(index_html, args.index_url)
    if args.max_committees is not None:
        committees = committees[: args.max_committees]

    source_links: List[CommitteeSourceRecord] = []
    for index, committee in enumerate(committees, start=1):
        print(f"[{index}/{len(committees)}] Fetching {committee.committee_url}")
        committee_html = fetch_html(session, committee.committee_url)
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", committee.committee_url.split("/")[-1].replace(".aspx", ""))
        (output_paths["raw"] / f"{slug}.html").write_text(committee_html, encoding="utf-8")
        source_links.extend(extract_source_links(committee_html, committee.committee_name, committee.committee_url))

    write_csv(output_paths["committees"], committees)
    write_csv(output_paths["source_links"], source_links)

    manifest = {
        "index_url": args.index_url,
        "committee_count": len(committees),
        "source_link_count": len(source_links),
        "generated_at": date.today().isoformat(),
        "privacy_note": "CMIS access may require public registration; compiled outputs should retain only public-office references and source URLs.",
    }
    output_paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
