"""Reporting utilities: ward-level aggregation and simple exports."""
from typing import Optional
import pandas as pd


def ward_activity_report(councillors_df: pd.DataFrame, activity_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Produce a ward-level summary DataFrame.

    - councillors_df: DataFrame with at least a `ward` column
    - activity_df: optional DataFrame with an activity record containing `ward` or `councillor_id`
    """
    if councillors_df is None or councillors_df.empty:
        return pd.DataFrame()

    # councillors per ward
    by_ward = councillors_df.groupby("ward").size().rename("councillor_count").to_frame()

    # attach activity counts if provided
    if activity_df is not None and not activity_df.empty:
        if "ward" in activity_df.columns:
            act = activity_df.groupby("ward").size().rename("activity_count")
            by_ward = by_ward.join(act, how="left").fillna(0)
        else:
            by_ward["activity_count"] = 0
    else:
        by_ward["activity_count"] = 0

    by_ward = by_ward.reset_index().rename(columns={"index": "ward"})
    return by_ward


def to_csv(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False)
