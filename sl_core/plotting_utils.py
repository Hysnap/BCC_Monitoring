"""Plotting helpers for Streamlit visuals."""
from typing import Any
import pandas as pd


def summarize_for_line_chart(
    frame: pd.DataFrame, x: str, y: str
) -> pd.DataFrame:
    """Return aggregated data suited for a simple line chart."""
    if x not in frame or y not in frame:
        return frame
    return frame[[x, y]].dropna()


def placeholder_plot(*_: Any, **__: Any) -> None:
    """Placeholder hook for chart creation; swap with Plotly/Altair code."""
    raise NotImplementedError("Add plotting implementation")
