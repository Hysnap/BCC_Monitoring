"""Simple API clients for Birmingham CMIS and City Observatory."""
from typing import Any, Dict, Optional
import requests


def fetch_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 10) -> Any:
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise


def fetch_cmis(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Fetch data from Birmingham CMIS. Provide the full URL to the endpoint.

    Example: fetch_cmis('https://birmingham.cmis.uk.com/...')
    """
    return fetch_json(endpoint, params=params)


def fetch_city_observatory(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Fetch data from City Observatory API (v2.1).

    Example endpoint: https://www.cityobservatory.birmingham.gov.uk/api-console/explore/v2.1/<path>
    """
    return fetch_json(endpoint, params=params)
