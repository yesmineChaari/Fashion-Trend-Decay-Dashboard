"""Live search page: analyse any keyword on demand.

Type a keyword that isn't in `config/trends.yaml` and get the same analysis
the curated set gets — the same fetch path, the same metrics engine, the same
cards and chart as the Trend detail page. This page is the only one in the
dashboard that reaches the network; everything it does with what comes back
lives in `fashion_trends.app.live_search`, so this file stays widgets and
nothing else.
"""

from __future__ import annotations

import time
from dataclasses import replace

import streamlit as st

from fashion_trends.app.data import get_settings
from fashion_trends.app.live_search import (
    AD_HOC_NOTICE,
    MIN_SECONDS_BETWEEN_LOOKUPS,
    SPARSE_MESSAGE,
    describe_failure,
    lookup_keyword,
    normalize_keyword,
    seconds_until_next_lookup,
)
from fashion_trends.app.trend_detail import metric_cards
from fashion_trends.ingest.pytrends_client import TrendsClientError
from fashion_trends.viz.trend_detail import plot_trend_series

LAST_LOOKUP_KEY = "live_search_last_lookup_at"

st.title("Live search")
st.caption(
    "Analyse any fashion keyword, not just the curated catalog. Results are "
    "pulled from Google Trends when you submit."
)

settings = get_settings()

# A form rather than a bare text input: `st.text_input` reruns the script on
# every keystroke, which against a rate-limited unofficial endpoint would
# mean a request per character. A form submits once, on the button.
with st.form("live_search"):
    keyword_input = st.text_input("Keyword", placeholder="e.g. barrel jeans")
    timeframe_column, geo_column = st.columns(2)
    timeframe = timeframe_column.text_input(
        "Timeframe",
        value=settings.timeframe,
        help="Google Trends timeframe string. 'today 5-y' is the longest window still returning weekly data.",
    )
    geo = geo_column.text_input(
        "Geo", value=settings.geo, help="Two-letter country code, or blank for worldwide."
    )
    submitted = st.form_submit_button("Analyse")

keyword = normalize_keyword(keyword_input)

if not submitted:
    st.stop()

if not keyword:
    st.warning("Enter a keyword to analyse.")
    st.stop()

wait_seconds = seconds_until_next_lookup(st.session_state.get(LAST_LOOKUP_KEY), time.monotonic())
if wait_seconds > 0:
    st.warning(
        f"Slow down a moment — one lookup every {MIN_SECONDS_BETWEEN_LOOKUPS:.0f}s. "
        f"Try again in {wait_seconds:.0f}s."
    )
    st.stop()
st.session_state[LAST_LOOKUP_KEY] = time.monotonic()

# `lookup_keyword` is cached per (keyword, settings), and the timeframe and
# geo overrides live in `settings` — so re-submitting a keyword already
# looked at this session re-renders it without spending another request.
try:
    result = lookup_keyword(keyword, replace(settings, timeframe=timeframe, geo=geo))
except TrendsClientError as error:
    st.error(describe_failure(error))
    st.stop()

st.subheader(result.keyword)
st.caption(f"Window **{result.timeframe}**  ·  Geo **{result.geo}**")
st.info(AD_HOC_NOTICE)

if result.sparse:
    # Metrics were computed — the chart's peak and half-life annotations read
    # off them — but they are not shown as findings. See `LiveResult.sparse`.
    st.warning(SPARSE_MESSAGE)
else:
    cards = metric_cards(result.metrics_row)
    card_columns = st.columns(5)
    card_columns[0].metric("Peak value", cards["peak_value"])
    card_columns[1].metric("Peak date", cards["peak_date"])
    card_columns[2].metric("% dropped", cards["pct_dropped"])
    card_columns[3].metric("Decay rate", cards["decay_rate"])
    card_columns[4].metric("Weeks to 50%", cards["weeks_to_half"])

    st.caption(f"Status: **{cards['status']}**")
    if cards["flags"]:
        st.caption(f"Caveats: {cards['flags']}")

st.pyplot(plot_trend_series(result.series, result.metrics_row))
