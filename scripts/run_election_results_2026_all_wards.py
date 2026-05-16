"""Run the 2026 Birmingham ward election scrape across all wards.

This runner uses Playwright to load the rendered index and ward pages one at a time.
It keeps a checkpoint so interrupted runs can resume, and it skips wards whose page
last-updated date has not changed since the previous successful pull.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sl_core"))

from scripts.scrape_election_results_2026 import (  # noqa: E402
    DEFAULT_START_URL,
    ElectionStandingRecord,
    PartyHistoryRecord,
    WardSummaryRecord,
    collect_ward_links,
    ensure_output_dirs,
    parse_ward_page,
    slugify_url,
    write_csv,
)
from utils import global_variables as gv  # noqa: E402
from scripts.compile_unified_dataset import merge_all_outputs  # noqa: E402


DEFAULT_DELAY_MIN = gv.DEFAULT_DELAY_MIN
DEFAULT_DELAY_MAX = gv.DEFAULT_DELAY_MAX
CHECKPOINT_FILE_NAME = "checkpoint.json"


def polite_delay(delay_min: float, delay_max: float) -> float:
    return random.uniform(delay_min, delay_max)


def fetch_rendered_html(page, url: str, timeout_ms: int) -> str:
    page.goto(url, wait_until="networkidle", timeout=timeout_ms)
    page.wait_for_timeout(750)
    return page.content()


def load_checkpoint(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"wards": {}}
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(checkpoint, dict) and isinstance(checkpoint.get("wards"), dict):
            return checkpoint
    except Exception:
        pass
    return {"wards": {}}


def save_checkpoint(path: Path, checkpoint: Dict[str, object]) -> None:
    path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")


def checkpoint_key(url: str) -> str:
    return urlparse(url).path


def should_skip_ward(checkpoint: Dict[str, object], ward_url: str, page_last_updated: Optional[str]) -> bool:
    wards = checkpoint.get("wards", {})
    if not isinstance(wards, dict):
        return False
    ward_entry = wards.get(checkpoint_key(ward_url), {})
    if not isinstance(ward_entry, dict):
        return False
    return bool(
        ward_entry.get("status") == "complete"
        and ward_entry.get("page_last_updated")
        and page_last_updated
        and ward_entry.get("page_last_updated") == page_last_updated
    )


def load_csv_records(path: Path) -> List[Dict[str, object]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    frame = pd.read_csv(path)
    return frame.to_dict(orient="records")


def record_value(record: object, key: str, default: object = "") -> object:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def remove_ward_records(records: List[Dict[str, object]], ward_name: str) -> List[Dict[str, object]]:
    return [record for record in records if str(record_value(record, "ward_name", "")) != ward_name]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compile_records(
    start_url: str,
    output_dir: Path,
    delay_min: float,
    delay_max: float,
    timeout_ms: int,
    max_wards: Optional[int] = None,
    headed: bool = False,
    force_refresh: bool = False,
) -> Dict[str, object]:
    output_paths = ensure_output_dirs(output_dir)
    checkpoint_path = output_paths["base"] / CHECKPOINT_FILE_NAME
    checkpoint = load_checkpoint(checkpoint_path)

    people_records: Dict[str, Dict[str, object]] = {
        str(record["person_id"]): record
        for record in load_csv_records(output_paths["people"])
        if record.get("person_id")
    }
    party_history_records = load_csv_records(output_paths["party_history"])
    election_standing_records = load_csv_records(output_paths["election_standings"])
    ward_summary_records = load_csv_records(output_paths["ward_summaries"])

    skipped_wards = 0
    processed_wards = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            locale="en-GB",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            print(f"Loading ward index: {start_url}")
            start_html = fetch_rendered_html(page, start_url, timeout_ms=timeout_ms)
            ward_urls = collect_ward_links(start_html, start_url)
            if max_wards is not None:
                ward_urls = ward_urls[:max_wards]

            print(f"Discovered {len(ward_urls)} ward pages")
            if not ward_urls:
                raise SystemExit("No ward result links were found on the index page.")

            for index, ward_url in enumerate(ward_urls, start=1):
                print(f"[{index}/{len(ward_urls)}] Visiting {ward_url}")
                html = fetch_rendered_html(page, ward_url, timeout_ms=timeout_ms)
                ward_data = parse_ward_page(html, ward_url)
                ward_checkpoint_key = checkpoint_key(ward_url)

                if not force_refresh and should_skip_ward(checkpoint, ward_url, ward_data.page_last_updated):
                    skipped_wards += 1
                    checkpoint.setdefault("wards", {})
                    checkpoint["wards"][ward_checkpoint_key] = {
                        **checkpoint["wards"].get(ward_checkpoint_key, {}),
                        "last_checked_at": now_iso(),
                    }
                    save_checkpoint(checkpoint_path, checkpoint)
                    print(f"  -> unchanged since {ward_data.page_last_updated}; skipping compile")
                    continue

                raw_path = output_paths["raw"] / f"{slugify_url(ward_url)}.html"
                raw_path.write_text(html, encoding="utf-8")

                print(f"  -> {ward_data.ward_name}: {len(ward_data.candidates)} candidates")

                people_records = {
                    person_id: record
                    for person_id, record in people_records.items()
                    if str(record_value(record, "first_seen_ward", "")) != ward_data.ward_name
                }
                party_history_records = remove_ward_records(party_history_records, ward_data.ward_name)
                election_standing_records = remove_ward_records(election_standing_records, ward_data.ward_name)
                ward_summary_records = remove_ward_records(ward_summary_records, ward_data.ward_name)

                for candidate in ward_data.candidates:
                    person_id = str(candidate["person_id"])
                    person_name = str(candidate["person_name"])
                    party_name = str(candidate["party_name"])
                    election_date = str(candidate["election_date"])
                    votes_received = int(candidate["votes_received"])
                    is_elected = bool(candidate["is_elected"])
                    source_url = str(candidate["source_url"])

                    people_records[person_id] = {
                        "person_id": person_id,
                        "person_name": person_name,
                        "first_seen_ward": ward_data.ward_name,
                        "source_url": source_url,
                    }

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

                checkpoint.setdefault("wards", {})
                checkpoint["wards"][ward_checkpoint_key] = {
                    "ward_name": ward_data.ward_name,
                    "source_url": ward_url,
                    "page_last_updated": ward_data.page_last_updated,
                    "last_checked_at": now_iso(),
                    "last_pulled_at": now_iso(),
                    "status": "complete",
                    "candidate_count": len(ward_data.candidates),
                }
                save_checkpoint(checkpoint_path, checkpoint)
                processed_wards += 1

                if index < len(ward_urls):
                    delay_seconds = polite_delay(delay_min, delay_max)
                    print(f"  -> sleeping {delay_seconds:.1f}s")
                    time.sleep(delay_seconds)
        finally:
            context.close()
            browser.close()

    people_rows = sorted(people_records.values(), key=lambda row: (row["person_name"], row["person_id"]))
    write_csv(output_paths["people"], people_rows)
    write_csv(output_paths["party_history"], party_history_records)
    write_csv(output_paths["election_standings"], election_standing_records)
    write_csv(output_paths["ward_summaries"], ward_summary_records)

    manifest = {
        "start_url": start_url,
        "ward_count": len(ward_urls),
        "processed_wards": processed_wards,
        "skipped_wards": skipped_wards,
        "people_count": len(people_rows),
        "party_history_count": len(party_history_records),
        "election_standing_count": len(election_standing_records),
        "ward_summary_count": len(ward_summary_records),
        "delay_min_seconds": delay_min,
        "delay_max_seconds": delay_max,
        "generated_at": date.today().isoformat(),
        "mode": "playwright-browser",
        "checkpoint_file": CHECKPOINT_FILE_NAME,
        "force_refresh": force_refresh,
    }
    output_paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # After writing per-run outputs, merge into the canonical master dataset
    try:
        master_dir = Path(gv.DIRECTORIES["output_dir"]) / "current"
        print(f"Merging run outputs into master dataset at {master_dir}")
        merge_all_outputs(Path(gv.DIRECTORIES["output_dir"]), master_dir)
    except Exception as exc:  # pragma: no cover - best-effort merge
        print(f"Warning: failed to merge run outputs into master dataset: {exc}")

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Birmingham 2026 ward scrape across all wards")
    parser.add_argument("--start-url", default=gv.ELECTION_START_URL, help="Ward index page to start from")
    parser.add_argument("--output-dir", default=str(gv.ELECTION_OUTPUT_DIR), help="Directory for CSV outputs")
    parser.add_argument("--delay-min", type=float, default=DEFAULT_DELAY_MIN, help="Minimum seconds to wait between ward pages")
    parser.add_argument("--delay-max", type=float, default=DEFAULT_DELAY_MAX, help="Maximum seconds to wait between ward pages")
    parser.add_argument("--max-wards", type=int, default=None, help="Limit the number of ward pages to scrape")
    parser.add_argument("--headed", action="store_true", help="Show the browser window while scraping")
    parser.add_argument("--timeout-ms", type=int, default=gv.DEFAULT_TIMEOUT_MS, help="Navigation timeout in milliseconds")
    parser.add_argument("--force-refresh", action="store_true", help="Re-pull every ward even if the checkpoint says it is unchanged")
    args = parser.parse_args()

    if args.delay_min < 0 or args.delay_max < 0:
        raise SystemExit("Delay values must be non-negative.")
    if args.delay_max < args.delay_min:
        raise SystemExit("--delay-max must be greater than or equal to --delay-min.")

    output_dir = Path(args.output_dir)
    ensure_output_dirs(output_dir)

    try:
        manifest = compile_records(
            start_url=args.start_url,
            output_dir=output_dir,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            timeout_ms=args.timeout_ms,
            max_wards=args.max_wards,
            headed=args.headed,
            force_refresh=args.force_refresh,
        )
        print("Done")
        print(json.dumps(manifest, indent=2))
    except PlaywrightTimeoutError as exc:
        raise SystemExit(f"Timed out loading a page: {exc}") from exc


if __name__ == "__main__":
    main()