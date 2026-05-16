"""Reusable data filtering utilities."""
from typing import Any
import pandas as pd


def apply_filters(frame: pd.DataFrame, **filters: Any) -> pd.DataFrame:
    """Apply simple equality filters to a DataFrame."""
    result = frame.copy()
    for column, value in filters.items():
        if value is None:
            continue
        if column in result:
            result = result[result[column] == value]
    return result
