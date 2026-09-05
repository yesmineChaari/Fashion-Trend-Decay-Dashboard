#!/usr/bin/env python
"""Streamlit dashboard entry point.

    streamlit run app/streamlit_app.py

Renders the global header (data pull date, timeframe, geo) and hands off to
one of three pages via `st.navigation`: Overview, Trend detail, and Live
search (see `app/views/`), each of which loads its own data through
`fashion_trends.app.data.load_dashboard_data`. That loader is wrapped in
`st.cache_data`, so this script re-running on every page switch or widget
interaction — normal Streamlit behaviour — never re-reads either parquet
file from disk after the first read of a session.

Reads only `data/processed/*.parquet`, through that same loader, and makes
no network calls; refreshing data is `scripts/refresh_data.py`'s job, not
this app's. The app never writes to `data/processed/` — it is strictly a
reader, so a dashboard session can't corrupt the analysis artifacts.

Shows a friendly setup screen instead of the pages when `data/processed/` is
still empty on a first run.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.app.data import ProcessedDataMissingError, get_settings, load_dashboard_data
from fashion_trends.app.layout import render_header, render_missing_data_screen

st.set_page_config(page_title="Fashion Trends", layout="wide")

settings = get_settings()

try:
    _series, metrics = load_dashboard_data(settings)
except ProcessedDataMissingError as exc:
    render_missing_data_screen(exc)
    st.stop()

render_header(metrics)

# Named `views/`, not `pages/` -- Streamlit auto-detects a literal `pages/`
# directory next to the entry script for its older, implicit multipage
# convention, which collides with the explicit `st.Page`/`st.navigation` API
# used here (Streamlit warns "st.navigation was called in an app with a
# pages/ directory" and recommends this exact rename).
pages = [
    st.Page("views/overview.py", title="Overview", icon="📊", default=True),
    st.Page("views/trend_detail.py", title="Trend detail", icon="🔍"),
    st.Page("views/live_search.py", title="Live search", icon="🔎"),
]
st.navigation(pages).run()
