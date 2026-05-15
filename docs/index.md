# Birmingham Councillor Activity Monitoring

This repository provides a scaffold to ingest councillor and activity data from Birmingham CMIS and City Observatory, normalize records by ward, and produce ward-level reports.

Quick links

- Demo runner: `run_demo.py`
- Client helpers: `src/monitoring/clients.py`
- Normalization: `src/monitoring/normalize.py`
- Reporting: `src/monitoring/report.py`

How to publish

This repository includes a GitHub Actions workflow that deploys the site to GitHub Pages whenever `main` is updated. The site content is taken from the `docs/` folder (this file).

Next steps

- Update `docs/` with more usage docs, examples, and output screenshots.
- Optionally add a `CNAME` file if you want a custom domain.
