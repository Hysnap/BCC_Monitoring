# Birmingham CMIS Extraction

This repository is now scoped to careful CMIS rendered-page extraction. The goal is to crawl and scrape at a pace that looks like normal user traffic, while keeping the implementation simple, observable, and easy to pause if the service team asks for changes.

Start here

- Read [docs/next-steps.md](docs/next-steps.md) for the recommended implementation path.
- Read [docs/relational-schema.md](docs/relational-schema.md) for the canonical database structure and diagram.
- Review `scripts/scrape_election_results_2026.py` for the reusable extractor.
- Review `scripts/run_election_results_2026_all_wards.py` for the browser-driven all-wards runner.
- Review `run_demo.py` if you want a starting point for a separate demo workflow.

Scope

- Low-rate crawling and scraping of CMIS rendered pages
- Retry, backoff, and cache behaviour that reduces repeated requests
- Parsing and storage of extracted records
- Basic operational logging so crawl pace is visible and auditable

Starting point

- Use the Birmingham 2026 election results by ward pages as the first crawl target.
- Capture candidate names, associated party, votes cast, and elected status for each ward.

Publishing

- GitHub Pages remains the output-sharing layer for the collated data products.
- The publishing step should consume prepared outputs rather than drive extraction itself.

