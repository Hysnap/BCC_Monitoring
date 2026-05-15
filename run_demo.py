"""Demo runner: fetch sample data, normalize, and write a ward report.

This script is safe to run offline — it will catch network errors and exit gracefully.
"""
import os
import sys
from pprint import pprint

# Ensure local src is importable when running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from monitoring.clients import fetch_cmis, fetch_city_observatory
from monitoring.normalize import normalize_councillors, normalize_activity
from monitoring.report import ward_activity_report, to_csv


def safe_fetch(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"Fetch failed: {e}")
        return None


def main():
    os.makedirs("output", exist_ok=True)

    # Example endpoints (fill with concrete paths as needed)
    cmis_example = "https://birmingham.cmis.uk.com/rest/api/1/your-endpoint"
    cityobs_example = "https://www.cityobservatory.birmingham.gov.uk/api-console/explore/v2.1/your-endpoint"

    print("Fetching councillor data (CMIS)...")
    councillors_raw = safe_fetch(fetch_cmis, cmis_example)

    print("Fetching activity data (City Observatory)...")
    activity_raw = safe_fetch(fetch_city_observatory, cityobs_example)

    # Fallback: if raw is None, use empty lists so processing continues
    councillors_raw = councillors_raw or []
    activity_raw = activity_raw or []

    print("Normalizing...")
    councillors_df = normalize_councillors(councillors_raw)
    activity_df = normalize_activity(activity_raw)

    print("Building ward report...")
    ward_df = ward_activity_report(councillors_df, activity_df)

    out_path = os.path.join("output", "ward_report.csv")
    to_csv(ward_df, out_path)

    print(f"Wrote ward report to {out_path}")
    pprint(ward_df.head().to_dict(orient="records"))


if __name__ == "__main__":
    main()
