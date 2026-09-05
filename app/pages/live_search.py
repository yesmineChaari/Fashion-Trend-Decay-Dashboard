"""Live search: analyse any keyword on demand.

Placeholder — only confirms the cached data-access layer is wired up. Live
keyword lookups against Google Trends land in a future update.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.app.data import get_settings, load_dashboard_data

st.title("Live search")

load_dashboard_data(get_settings())
st.text_input("Keyword", disabled=True, placeholder="Live search lands in a future update.")
