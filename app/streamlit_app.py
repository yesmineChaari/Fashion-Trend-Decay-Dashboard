#!/usr/bin/env python
"""Streamlit dashboard entry point.

    streamlit run app/streamlit_app.py

Renders the shared chrome, then hands off to one of three pages via
`st.navigation`: Overview, Trend detail, and Live search (see `app/views/`).
Reads the curated set only from `data/processed/*.parquet`; refreshing that
data is `scripts/refresh_data.py`'s job, not this app's. Live search is the
one page that reaches the network.

Shows a friendly setup screen instead of the pages when `data/processed/` is
still empty on a first run.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.app.data import ProcessedDataMissingError, get_settings, load_dashboard_data
from fashion_trends.app.layout import render_header, render_missing_data_screen, render_sidebar

st.set_page_config(
    page_title="Fashion Trends, the half-life of a micro-trend",
    page_icon="📉",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"about": "Measuring how fast fashion micro-trends rise and fall, from Google Trends search interest."},
)

settings = get_settings()

try:
    _series, metrics = load_dashboard_data(settings)
except ProcessedDataMissingError as exc:
    render_missing_data_screen(exc)
    st.stop()

render_header(metrics)

# Named `views/`, not `pages/`, to avoid colliding with Streamlit's legacy
# implicit multipage convention.
pages = [
    st.Page("views/overview.py", title="Overview", default=True),
    st.Page("views/trend_detail.py", title="Trend detail"),
    st.Page("views/live_search.py", title="Live search"),
]
navigation = st.navigation(pages)

render_sidebar(metrics)

navigation.run()
