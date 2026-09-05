"""Shared page chrome for the Streamlit dashboard.

One module so every page renders the same header and the same first-run
message, rather than each page under `app/views/` deciding independently how
to phrase either one.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from fashion_trends.viz.build import ProcessedDataMissingError


def render_header(metrics: pd.DataFrame) -> None:
    """Render the global header naming the loaded dataset's pull date, timeframe, and geo.

    Reads only `metrics`'s own provenance columns (see
    `fashion_trends.metrics.schema.PROVENANCE_COLUMNS`) — the same source
    every static figure's footer uses, via
    `fashion_trends.viz.theme.save_figure` — so the dashboard and the static
    charts can never disagree about which run's numbers are on screen.
    """
    if metrics.empty:
        st.caption("No trend data loaded.")
        return

    pull_date = metrics["data_pull_date"].iloc[0]
    pull_date_label = pull_date.date().isoformat() if hasattr(pull_date, "date") else str(pull_date)
    timeframe = metrics["timeframe"].iloc[0]
    geo = metrics["geo"].iloc[0]

    st.caption(f"Data pulled **{pull_date_label}**  ·  Window **{timeframe}**  ·  Geo **{geo}**")


def render_missing_data_screen(error: ProcessedDataMissingError) -> None:
    """Render the friendly first-run screen shown in place of the dashboard's pages.

    Used when `app.data.load_dashboard_data` raises `ProcessedDataMissingError`
    — i.e. `data/processed/` is still empty — so a first run tells the user
    to run `scripts/refresh_data.py` instead of surfacing a raw
    `FileNotFoundError` traceback.
    """
    st.title("Fashion Trends")
    st.warning("No processed data found yet.")
    st.markdown(
        "Run the ingestion pipeline once to populate `data/processed/`, "
        "then reload this page:\n\n```bash\npython scripts/refresh_data.py\n```"
    )
    st.caption(str(error))
