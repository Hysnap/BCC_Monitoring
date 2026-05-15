"""Normalization helpers to convert raw API JSON into pandas DataFrames."""
from typing import Any, List
import pandas as pd


def normalize_councillors(raw: List[dict]) -> pd.DataFrame:
    """Take a list of councillor records (dict) and return a DataFrame.

    This is intentionally permissive — adapt field mapping to the actual API.
    """
    if not raw:
        return pd.DataFrame()
    df = pd.json_normalize(raw)
    # Ensure common columns exist
    for col in ["name", "ward", "party", "email"]:
        if col not in df.columns:
            df[col] = None
    return df[[c for c in df.columns if True]]


def normalize_activity(raw: List[dict]) -> pd.DataFrame:
    """Normalize activity or meeting records to a DataFrame."""
    if not raw:
        return pd.DataFrame()
    df = pd.json_normalize(raw)
    return df
