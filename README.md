Birmingham councillor activity monitoring — scaffold

Minimal Python workspace to ingest data from Birmingham CMIS and City Observatory, normalize councillor and activity data by ward, and produce ward-level reports.

Quick start

1. Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Run the demo (safe fallback if APIs are unreachable):

```powershell
python run_demo.py
```

Files of interest

- `src/monitoring/clients.py` — API clients for CMIS and City Observatory
- `src/monitoring/normalize.py` — normalization helpers (to DataFrame)
- `src/monitoring/report.py` — ward-level reporting utilities
- `run_demo.py` — runnable demo that fetches data and writes `output/ward_report.csv`

Next steps

- Wire in exact CMIS endpoints and API keys (if required)
- Add ward geometry joins (GeoJSON) for spatial reports
- Add scheduling and alerting for monitoring
