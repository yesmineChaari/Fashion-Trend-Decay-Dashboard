#!/usr/bin/env python
"""Streamlit dashboard entry point.

    streamlit run app/streamlit_app.py

Renders the shared chrome — the masthead (headline, standfirst, and the
pull date/timeframe/geo chips) and the sidebar glossary — then hands off to
one of three pages via `st.navigation`: Overview, Trend detail, and Live
search (see `app/views/`), each of which loads its own data through
`fashion_trends.app.data.load_dashboard_data`. That loader is wrapped in
`st.cache_data`, so this script re-running on every page switch or widget
interaction — normal Streamlit behaviour — never re-reads either parquet
file from disk after the first read of a session.

Reads the curated set only from `data/processed/*.parquet`, through that same
loader; refreshing that data is `scripts/refresh_data.py`'s job, not this
app's. The app never writes to `data/processed/` — it is strictly a reader
there, so a dashboard session can't corrupt the analysis artifacts. The one
place it reaches the network is Live search, which fetches a single ad-hoc
keyword on demand through the ordinary ingest path (see
`fashion_trends.app.live_search`) and leaves the curated artifacts alone.

Shows a friendly setup screen instead of the pages when `data/processed/` is
still empty on a first run.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.app.data import ProcessedDataMissingError, get_settings, load_dashboard_data
from fashion_trends.app.layout import render_header, render_missing_data_screen, render_sidebar

st.set_page_config(
    page_title="Fashion Trends — the half-life of a micro-trend",
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

# Named `views/`, not `pages/` -- Streamlit auto-detects a literal `pages/`
# directory next to the entry script for its older, implicit multipage
# convention, which collides with the explicit `st.Page`/`st.navigation` API
# used here (Streamlit warns "st.navigation was called in an app with a
# pages/ directory" and recommends this exact rename).
pages = [
    st.Page("views/overview.py", title="Overview", default=True),
    st.Page("views/trend_detail.py", title="Trend detail"),
    st.Page("views/live_search.py", title="Live search"),
]
navigation = st.navigation(pages)

# After `st.navigation` so the glossary sits below the page links rather than
# above them, and before `.run()` so it is on screen while a page is still
# rendering its charts.
render_sidebar(metrics)

navigation.run()
