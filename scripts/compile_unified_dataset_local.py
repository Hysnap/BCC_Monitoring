"""Local-only merge of all existing output folders into output/current.

This script never touches the source website. It reads the CSVs already on disk,
resolves councillor/election name variants locally, and rebuilds the unified
current dataset with a single person identity per matched councillor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd
from dateutil import parser as date_parser


def _load_csv(path: Path) -> List[Dict[str, object]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        return pd.read_csv(path).to_dict(orient="records")
    except Exception:
        return []


def _write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False)


def _parse_date(value: str) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date_parser.parse(text, fuzzy=True).date().isoformat()
    except Exception:
        return None


def _subtract_one_day(iso_date: str) -> str:
    parsed = datetime.fromisoformat(iso_date)
    return (parsed.date() - timedelta(days=1)).isoformat()


def _tokens(value: str) -> Tuple[str, ...]:
    return tuple(sorted(re.findall(r"[A-Za-z0-9']+", str(value or "").lower())))


def _token_set(value: str) -> Set[str]:
    return set(_tokens(value))


def _person_id(value: str) -> str:
    return hashlib.sha1(str(value or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def _prefer_name(existing: str, candidate: str) -> str:
    existing = str(existing or "").strip()
    candidate = str(candidate or "").strip()
    if not existing:
        return candidate
    if not candidate:
        return existing
    if "," in candidate and "," not in existing:
        return candidate
    if len(candidate) > len(existing):
        return candidate
    return existing


def _load_output_dirs(output_root: Path, master_dir_name: str) -> List[Path]:
    priority = {
        "election_2026_all_wards": 0,
        "election_2022_may": 1,
        "councillors": 2,
        "cmis_committees_test": 3,
        "publication": 4,
        "checkpoints": 5,
        "data": 6,
        "raw_html": 7,
    }
    dirs: List[Path] = []
    for child in output_root.iterdir():
        if not child.is_dir():
            continue
        name = child.name.lower()
        if name in {"development", master_dir_name.lower()}:
            continue
        dirs.append(child)
    return sorted(dirs, key=lambda p: (priority.get(p.name, 100), p.name))


def _build_current_index(councillor_rows: Sequence[Dict[str, object]]) -> List[Tuple[str, Set[str]]]:
    index: List[Tuple[str, Set[str]]] = []
    for row in councillor_rows:
        name = str(row.get("councillor_name") or "").strip()
        if name:
            index.append((name, _token_set(name)))
    return index


def _resolve_name(
    raw_name: str,
    current_index: Sequence[Tuple[str, Set[str]]],
    fallback_map: Dict[Tuple[str, ...], str],
) -> str:
    cleaned = str(raw_name or "").strip()
    if not cleaned:
        return cleaned

    raw_tokens = _token_set(cleaned)
    if not raw_tokens:
        return cleaned

    best_name = ""
    best_score: Tuple[int, int] = (-1, -999)
    for current_name, current_tokens in current_index:
        overlap = len(raw_tokens & current_tokens)
        if overlap < 2:
            continue
        if raw_tokens == current_tokens:
            return current_name
        if raw_tokens.issubset(current_tokens) or current_tokens.issubset(raw_tokens):
            score = (overlap, -abs(len(raw_tokens) - len(current_tokens)))
            if score > best_score:
                best_score = score
                best_name = current_name

    if best_name:
        return best_name

    key = _tokens(cleaned)
    if key not in fallback_map:
        fallback_map[key] = cleaned
    return fallback_map[key]


def _canonicalize_row_name(
    row: Dict[str, object],
    current_index: Sequence[Tuple[str, Set[str]]],
    fallback_map: Dict[Tuple[str, ...], str],
) -> Tuple[str, str]:
    raw_name = str(row.get("person_name") or row.get("councillor_name") or "").strip()
    canonical_name = _resolve_name(raw_name, current_index, fallback_map)
    return canonical_name, _person_id(canonical_name)


def build_party_history_periods(election_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in election_rows:
        person_id = str(row.get("person_id") or "")
        if person_id:
            grouped[person_id].append(row)

    period_rows: List[Dict[str, object]] = []
    for person_id, rows in grouped.items():
        ordered = sorted(
            rows,
            key=lambda r: (
                _parse_date(str(r.get("election_date") or "")) or "9999-12-31",
                str(r.get("ward_name") or ""),
            ),
        )
        if not ordered:
            continue

        current_start = _parse_date(str(ordered[0].get("election_date") or "")) or str(ordered[0].get("election_date") or "")
        current_party = str(ordered[0].get("party_name") or "")
        current_name = str(ordered[0].get("person_name") or "")
        current_source = str(ordered[0].get("source_url") or "")

        for row in ordered[1:]:
            next_date = _parse_date(str(row.get("election_date") or "")) or str(row.get("election_date") or "")
            next_party = str(row.get("party_name") or "")
            if next_party != current_party:
                period_rows.append(
                    {
                        "person_id": person_id,
                        "person_name": current_name,
                        "party_name": current_party,
                        "effective_from": current_start,
                        "effective_to": _subtract_one_day(next_date) if next_date else "",
                        "is_current": False,
                        "source_url": current_source,
                    }
                )
                current_start = next_date
                current_party = next_party
                current_name = str(row.get("person_name") or current_name)
                current_source = str(row.get("source_url") or current_source)

        period_rows.append(
            {
                "person_id": person_id,
                "person_name": current_name,
                "party_name": current_party,
                "effective_from": current_start,
                "effective_to": "",
                "is_current": True,
                "source_url": current_source,
            }
        )

    return period_rows


def merge_all_outputs(output_root: Path, master_dir: Path) -> Dict[str, object]:
    output_root = Path(output_root)
    master_dir = Path(master_dir)
    master_dir.mkdir(parents=True, exist_ok=True)

    source_dirs = _load_output_dirs(output_root, master_dir.name)
    raw_people_rows: List[Dict[str, object]] = []
    raw_standing_rows: List[Dict[str, object]] = []
    raw_ward_rows: List[Dict[str, object]] = []
    councillor_rows: List[Dict[str, object]] = []
    raw_link_rows: List[Dict[str, object]] = []

    for child in source_dirs:
        raw_people_rows.extend(_load_csv(child / "people.csv"))
        raw_standing_rows.extend(_load_csv(child / "election_standings.csv"))
        raw_ward_rows.extend(_load_csv(child / "ward_summaries.csv"))
        councillor_rows.extend(_load_csv(child / "councillors.csv"))
        raw_link_rows.extend(_load_csv(child / "councillor_links.csv"))

    current_index = _build_current_index(councillor_rows)
    fallback_map: Dict[Tuple[str, ...], str] = {}

    canonical_people_map: Dict[str, Dict[str, object]] = {}
    for row in raw_people_rows:
        canonical_name, canonical_id = _canonicalize_row_name(row, current_index, fallback_map)
        if not canonical_id:
            continue
        merged = canonical_people_map.get(canonical_id, {})
        canonical_people_map[canonical_id] = {
            "person_id": canonical_id,
            "person_name": _prefer_name(merged.get("person_name", ""), canonical_name),
            "first_seen_ward": merged.get("first_seen_ward") or row.get("first_seen_ward") or "",
            "source_url": merged.get("source_url") or row.get("source_url") or "",
        }

    canonical_standing_rows: List[Dict[str, object]] = []
    seen_standing_keys: Set[Tuple[str, str, str]] = set()
    for row in raw_standing_rows:
        canonical_name, canonical_id = _canonicalize_row_name(row, current_index, fallback_map)
        if not canonical_id:
            continue
        canonical_row = {**row, "person_id": canonical_id, "person_name": canonical_name}
        standing_key = (
            canonical_id,
            str(canonical_row.get("ward_name") or ""),
            str(canonical_row.get("election_date") or ""),
        )
        if standing_key in seen_standing_keys:
            continue
        seen_standing_keys.add(standing_key)
        canonical_standing_rows.append(canonical_row)

    canonical_standing_rows = sorted(
        canonical_standing_rows,
        key=lambda r: (
            str(r.get("election_date") or ""),
            str(r.get("ward_name") or ""),
            str(r.get("person_name") or ""),
        ),
    )

    party_history_rows = build_party_history_periods(canonical_standing_rows)

    canonical_link_rows: List[Dict[str, object]] = []
    seen_link_keys: Set[Tuple[str, str, str]] = set()
    for row in raw_link_rows:
        canonical_name, canonical_id = _canonicalize_row_name(row, current_index, fallback_map)
        if not canonical_id:
            continue
        canonical_row = {**row, "person_id": canonical_id, "person_name": canonical_name}
        link_key = (
            canonical_id,
            str(canonical_row.get("councillor_url") or ""),
            str(canonical_row.get("status") or ""),
        )
        if link_key in seen_link_keys:
            continue
        seen_link_keys.add(link_key)
        canonical_link_rows.append(canonical_row)

    canonical_councillor_map: Dict[str, Dict[str, object]] = {}
    for row in councillor_rows:
        name = str(row.get("councillor_name") or "").strip()
        if not name:
            continue
        key = _person_id(name)
        merged = canonical_councillor_map.get(key, {})
        canonical_councillor_map[key] = {**row, "councillor_name": _prefer_name(merged.get("councillor_name", ""), name)}

    ward_map: Dict[Tuple[str, str], Dict[str, object]] = {}
    for row in raw_ward_rows:
        key = (str(row.get("ward_name") or ""), str(row.get("election_date") or ""))
        if key not in ward_map:
            ward_map[key] = row

    people_rows = sorted(
        canonical_people_map.values(),
        key=lambda r: (str(r.get("person_name") or ""), str(r.get("person_id") or "")),
    )

    _write_csv(master_dir / "people.csv", people_rows)
    _write_csv(master_dir / "party_history.csv", party_history_rows)
    _write_csv(master_dir / "election_standings.csv", canonical_standing_rows)
    _write_csv(master_dir / "ward_summaries.csv", list(ward_map.values()))
    if canonical_councillor_map:
        _write_csv(master_dir / "councillors.csv", list(canonical_councillor_map.values()))
    if canonical_link_rows:
        _write_csv(master_dir / "councillor_links.csv", canonical_link_rows)

    manifest = {
        "merged_from": [p.name for p in source_dirs],
        "people_count": len(people_rows),
        "party_history_count": len(party_history_rows),
        "election_standing_count": len(canonical_standing_rows),
        "ward_summary_count": len(ward_map),
        "councillor_count": len(canonical_councillor_map),
        "councillor_link_count": len(canonical_link_rows),
    }
    (master_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge run outputs into a canonical master directory")
    parser.add_argument("--output-root", default="output", help="Root folder containing run outputs")
    parser.add_argument("--master-dir", default="output/current", help="Directory to write merged outputs into")
    args = parser.parse_args()
    manifest = merge_all_outputs(Path(args.output_root), Path(args.master_dir))
    print(json.dumps(manifest, indent=2))
