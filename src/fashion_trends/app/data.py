"""Cached data-access layer for the Streamlit dashboard.

Every page under `app/views/` reads `series.parquet`/`metrics.parquet`
through `load_dashboard_data` instead of touching either file directly, so
there is exactly one place that decides how the parquet files are read and
how a missing-data run is reported. It wraps
`fashion_trends.viz.build.load_processed_data` — the same loader
`scripts/build_charts.py` uses — and adds nothing to its behaviour except the
`st.cache_data` layer: `load_processed_data` still raises
`ProcessedDataMissingError` naming `scripts/refresh_data.py` when
`data/processed/` is empty, re-exported here so a page never needs to import
`fashion_trends.viz.build` itself just to catch it.

Caching is keyed on `settings` (a frozen, hashable dataclass), so the parquet
files are read from disk once per process no matter how many pages or widget
interactions call this in the same session — see `app/streamlit_app.py`'s
module docstring for why that matters.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from fashion_trends.settings import Settings, load_settings
from fashion_trends.viz.build import ProcessedDataMissingError, load_processed_data

__all__ = ["ProcessedDataMissingError", "get_settings", "load_dashboard_data"]


def get_settings() -> Settings:
    """Resolve `Settings` from defaults and `FASHION_TRENDS_*` environment variables only.

    The dashboard is a read-only viewer, not a pipeline entry point, so
    `sys.argv` — under `streamlit run app/streamlit_app.py` this holds
    Streamlit's own CLI flags, not the app's — is never parsed as pipeline
    flags: an explicit empty `argv` is passed to `load_settings` rather than
    letting it default to `sys.argv[1:]`. A deployment that needs a
    non-default `timeframe`, `geo`, or `data_processed_dir` sets the matching
    `FASHION_TRENDS_*` environment variable instead.
    """
    return load_settings(argv=[])


@st.cache_data(show_spinner="Loading trend data…")
def load_dashboard_data(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read and cache `series.parquet`/`metrics.parquet` for the dashboard.

    Raises `ProcessedDataMissingError` when `data/processed/` hasn't been
    populated yet — callers should catch it and show
    `app.layout.render_missing_data_screen` rather than let Streamlit render
    the raw traceback.
    """
    return load_processed_data(settings)
