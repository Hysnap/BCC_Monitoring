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

- Build the councillor directory and link table, then merge it into the unified dataset:

```powershell
python scripts/scrape_councillors_directory.py --output-dir output/councillors --election-output-dir output/current
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
