import streamlit as st
import pandas as pd

def display_thresholds_table():
    """Creates and displays a table showing the threshold logic."""
    # Convert the dictionary into a DataFrame
    thresholds = st.session_state.get("thresholds", {})
    thresholds_df = pd.DataFrame(
        list(thresholds.items()),
        columns=["Donation Event Threshold", "Entity Category"],
    )

    st.write("### Threshold Logic Table")
    st.table(thresholds_df)
    return thresholds_df

