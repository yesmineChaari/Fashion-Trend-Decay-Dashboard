"""Cached data-access layer for the Streamlit dashboard.

Every page under `app/views/` reads `series.parquet`/`metrics.parquet` through
`load_dashboard_data` rather than touching either file directly, wrapping
`fashion_trends.viz.build.load_processed_data` with an `st.cache_data` layer
keyed on `settings`, so the files are read from disk once per process.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from fashion_trends.settings import Settings, load_settings
from fashion_trends.viz.build import ProcessedDataMissingError, load_processed_data

__all__ = ["ProcessedDataMissingError", "get_settings", "load_dashboard_data"]


def get_settings() -> Settings:
    """Resolve `Settings` from defaults and `FASHION_TRENDS_*` environment variables only.

    Passes an explicit empty `argv`, since under `streamlit run` `sys.argv` holds
    Streamlit's own CLI flags, not pipeline flags.
    """
    return load_settings(argv=[])


@st.cache_data(show_spinner="Loading trend data…")
def load_dashboard_data(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read and cache `series.parquet`/`metrics.parquet` for the dashboard.

    Raises `ProcessedDataMissingError` when `data/processed/` hasn't been
    populated yet; callers should catch it and show
    `app.layout.render_missing_data_screen`.
    """
    return load_processed_data(settings)
