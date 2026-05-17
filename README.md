# Birmingham CMIS Extraction

This repository performs polite, low-rate extraction of Birmingham City Council (CMIS) rendered pages — primarily used to collect the 2026 ward election results, normalize candidate/party/election records, and produce CSV/manifest outputs for later publishing.

Status

- Implemented: a reusable single-page scraper and a Playwright-driven runner with checkpointing and freshness checks.
- Outputs: normalized CSVs (people, party history, election standings, ward summaries), a JSON manifest, and raw HTML snapshots.

Quick start

1. Create a virtual environment and install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. If you plan to run the browser runner, install Playwright browsers:

```powershell
python -m playwright install chromium
```

3. Review the extraction plan in [docs/next-steps.md](docs/next-steps.md).

Key files

- scripts/scrape_election_results_2026.py — non-browser (requests + requests-cache + BeautifulSoup) reusable scraper for single ward pages or index-driven crawls.
- scripts/run_election_results_2026_all_wards.py — Playwright-driven runner that navigates all wards, respects polite delays, and compiles outputs with checkpoint/resume support.
- src/monitoring/clients.py, src/monitoring/normalize.py, src/monitoring/report.py — request helpers, parsing/normalization, and reporting utilities.

Usage examples

- Run a single-ward scrape (fast, non-browser):

```powershell
python scripts/scrape_election_results_2026.py --single-url "https://www.birmingham.gov.uk/info/50385/election_2026_candidates/3196/acocks_green_ward_election_2026" --output-dir output/trial_acocks_green --delay 0
```

- Run the Playwright all-wards runner (recommended for rendered pages):

```powershell
python scripts/run_election_results_2026_all_wards.py --output-dir output/election_2026_all_wards
```

- Build the councillor directory and link table, then merge it into the unified dataset (canonical `output/current`):

```powershell
python scripts/scrape_councillors_directory.py --election-output-dir output/current
python scripts/compile_unified_dataset.py --output-root output --master-dir output/current
```

- Inspect CMIS committee source links and keep the data privacy-safe:

```powershell
python scripts/scrape_cmis_committees.py --output-dir output/cmis_committees
```

Runner flags (common)

- `--headed` : run with visible browser window (useful for debugging).
- `--force-refresh` : ignore stored page-last-updated values and reprocess all wards.
- `--delay-min` / `--delay-max` : control randomized polite delays between page visits.
- `--max-wards` : limit number of wards to process for quick trials.

Outputs and checkpointing

- The runner writes CSV outputs and a `checkpoint.json` in the chosen output folder. By default the project uses `output/election_2026_all_wards` (configurable via CLI).
- Raw HTML snapshots are stored alongside compiled CSV outputs so results can be re-parsed or audited later.
- On subsequent runs the runner compares each ward's `page_last_updated` value and will skip unchanged wards unless `--force-refresh` is used.
- The unified dataset lives in `output/current/` and now includes the councillor directory plus the election/person link table.
- CMIS committee work should stay source-link-first: keep committee names, committee URLs, public webcast/video links, and source links, and only go deeper where the record is clearly a public office reference.

CMIS access note

- Users who need to browse deeper CMIS meeting data should register for CMIS access first. Keep that requirement visible in any downstream docs or pages that point to committee history, attendance, or related files.

Dependencies and environment

- Core Python packages are listed in `requirements.txt` (requests, requests-cache, beautifulsoup4, lxml, pandas, tenacity, playwright, python-dateutil, etc.).
- Running the Playwright runner requires installing the browser binary (`python -m playwright install chromium`).

Operational guidance and ethics

- Respect `robots.txt` and any stated rate limits or acceptable-use guidance from the host.
- Use low concurrency, randomized short delays, and caching to reduce load.
- Log activity and back off on repeated failures.

Next steps

- If you want outputs persisted to a database (SQLite) or published automatically to GitHub Pages, I can add a small publishing workflow or a conversion step from CSV → SQLite.

See also

- Extraction plan: [docs/next-steps.md](docs/next-steps.md)
- Single-run scraper: [scripts/scrape_election_results_2026.py](scripts/scrape_election_results_2026.py)
- All-wards runner: [scripts/run_election_results_2026_all_wards.py](scripts/run_election_results_2026_all_wards.py)

**Data Architecture**

- **`output/current`**: Canonical single source-of-truth for merged outputs (people, party_history, election_standings, ward_summaries, councillors, councillor_links, manifest). Use `scripts/compile_unified_dataset_local.py` to rebuild this from available run outputs.
- **Run outputs**: Individual scrapers write to their own subfolders under `output/` (for example `output/election_2022_may`, `output/election_2026_all_wards`). These are considered ephemeral run outputs and should not be treated as the canonical data store.
- **Avoid duplicates**: Historical or duplicate run outputs that contain `councillors.csv` (for example `output/councillors`) should be relocated to `output/development/archived/` to avoid confusion. A helper script is provided to automate this:

```powershell
python -m scripts.move_duplicate_outputs_to_development
```

- **How updates flow**: scrapers and runners emit per-run CSVs into `output/<run-name>/`. When ready, run `scripts/compile_unified_dataset_local.py` (or the CI task) to merge and canonicalize named entities into `output/current`.

- **Developer notes**: The `scrape_councillors_directory.py` scraper now targets `output/current` by default (so it does not create a separate `output/councillors` folder). If you need to perform a trial run, pass `--output-dir` explicitly.

**Core Data Files and Schema**

The canonical dataset in `output/current/` currently holds data for **69 wards** and up to **101 currently active councillors** (after each election, all 101 councillor seats should be populated). The following files form the backbone of the project:

| File | Records | Purpose | Schema |
|------|---------|---------|--------|
| **councillors.csv** | 101 | Current councillor roster with profile and contact data. One record per councillor seat (always 101 after elections, fewer during by-elections/vacancies). | `councillor_name`, `ward_name`, `party_name`, `councillor_url`, `councillor_id`, `page_last_updated`, `joined_council`, `office_expires`, `council_service`, `telephone`, `email`, `has_surgery`, `surgery_summary`, `register_of_interests_url` |
| **people.csv** | 1,084 | Canonical person registry. Every candidate who has stood in any election (2018, 2022, 2026) has one record. Used for deduplication and identity matching. | `person_id`, `person_name`, `first_seen_ward`, `source_url` |
| **election_standings.csv** | 1,371 | Complete election results history across all elections (2018, 2022, 2026). Each row is one candidate in one election in one ward. | `person_id`, `person_name`, `election_date`, `ward_name`, `votes_received`, `is_elected`, `party_name`, `source_url` |
| **party_history.csv** | 1,197 | Party affiliation timeline for each person. Tracks party changes across electoral cycles. | `person_id`, `person_name`, `party_name`, `effective_from`, `effective_to`, `is_current`, `source_url` |
| **ward_summaries.csv** | 207 | High-level summaries of each ward in each election (3 elections * 69 wards). | `election_date`, `ward_name`, `number_of_candidates`, `total_votes_cast`, `total_potential_voters`, `turnout_percent`, `number_of_councillors_elected`, `source_url` |
| **councillor_links.csv** | 700 | Mapping between candidates/people (from `election_standings.csv`) and current councillors (from `councillors.csv`). Enables joining historical election data to current profiles. | `person_id`, `person_name`, `ward_name`, `status`, `councillor_url`, `councillor_id`, `council_service`, `page_last_updated`, `source` |
| **manifest.json** | 1 | Metadata. Records merge source, record counts, and generated timestamp. | `merged_from`, `people_count`, `party_history_count`, `election_standing_count`, `ward_summary_count`, `councillor_count`, `councillor_link_count` |

**How Core Data Is Updated**

1. **Councillors** (`councillors.csv`):
   - Source: `scripts/scrape_councillors_directory.py`
   - Fetches current councillor profiles from the Birmingham City Council directory
   - Writes directly to `output/current/councillors.csv` (by default)
   - Contains live profile data, contact info, and manually-entered `joined_council` dates (e.g., "5 May 2022")
   - `office_expires` should default to `2030.0` for active councillors; use election date for those who lost office

2. **Election Results** (2018, 2022, 2026):
   - Source: `scrape_election_results_2018.py`, `scrape_election_results_2022.py`, `scrape_election_results_2026.py`
   - Writes to individual run folders: `output/election_2018_may/`, `output/election_2022_may/`, `output/election_2026_all_wards/`
   - Each produces: `people.csv`, `election_standings.csv`, `party_history.csv`, `ward_summaries.csv`

3. **Canonical Merge** (`output/current/`):
   - Source: `scripts/compile_unified_dataset_local.py`
   - Merges all per-run outputs into the canonical dataset
   - Performs name canonicalization using token-based matching to deduplicate person records across elections
   - Outputs to `output/current/`: merged `people.csv`, `election_standings.csv`, `party_history.csv`, `ward_summaries.csv`, and metadata
   - **Note**: `councillors.csv` is NOT auto-generated; it must be maintained separately via the councillor directory scraper

**Constraints and Maintenance Notes**

- **One councillor per ward seat**: The project manages **69 wards**, each electing **1-3 councillors** (typically 1 in this dataset). Total active = up to 101 councillors after a full election.
- **No duplicate person records**: After merge, each person should appear once in `people.csv` identified by a canonical `person_id`.
- **Historical elections must align**: When updating with a new election (e.g., 2026 results), ensure all three CSVs (people, election_standings, party_history, ward_summaries) are produced to maintain referential integrity.
- **Councillor-person linking**: The `councillor_links.csv` helps join current councillor profiles to historical election participation. Use `person_name` and `ward_name` as primary matching keys when linking tables.

**Relational Database (SQLAlchemy + SQLite)**

The canonical database structure is defined in [docs/relational-schema.md](docs/relational-schema.md).

Implementation files:

- [src/monitoring/database.py](src/monitoring/database.py): SQLAlchemy models and schema helpers
- [scripts/init_database.py](scripts/init_database.py): initializes schema and seeds baseline reference data

Initialize the database:

```powershell
python scripts/init_database.py
```

Default SQLite path:

- `output/data/monitoring.sqlite`

The schema is multi-council ready, keeps core entities normalized, uses hierarchical labels for flexible analysis, and includes validity windows plus a change log for historic reporting.
