"""Trend detail page.

Placeholder — only confirms the cached data-access layer is wired up. The
per-trend detail view lands in a future update.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.app.data import get_settings, load_dashboard_data

st.title("Trend detail")

series, _metrics = load_dashboard_data(get_settings())
st.write(f"{series['trend_id'].nunique()} trend(s) available.")
st.caption("Selecting and charting a single trend lands in a future update.")
