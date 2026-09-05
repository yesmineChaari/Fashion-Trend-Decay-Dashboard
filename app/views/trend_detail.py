"""Trend detail page.

Single-trend deep dive, picked from the selector below: the full weekly
series with its peak and half-life annotated, headline metric cards, its
decay curve against the median of the set, and its catalog metadata. All the
shaping and chart-building logic lives in `fashion_trends.app.trend_detail`
and `fashion_trends.viz.trend_detail` so it can be unit tested without a
running Streamlit script; this page only wires widgets to it.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.app.data import get_settings, load_dashboard_data
from fashion_trends.app.trend_detail import catalog_notes, metric_cards
from fashion_trends.viz.trend_detail import plot_trend_series, plot_trend_vs_median

st.title("Trend detail")

series, metrics = load_dashboard_data(get_settings())

if metrics.empty:
    st.info("No trend data loaded.")
    st.stop()

trend_ids_by_name = dict(zip(metrics["display_name"], metrics["trend_id"]))
selected_name = st.selectbox("Trend", sorted(trend_ids_by_name))
trend_id = trend_ids_by_name[selected_name]

row = metrics.loc[metrics["trend_id"] == trend_id].iloc[0]
trend_series = series.loc[series["trend_id"] == trend_id]

# The exact keyword queried is always visible, regardless of which metrics
# below turn out to be null -- the keyword choice shapes every number on
# this page, so it can't be something a reader has to go dig for.
st.caption(f"Keyword queried: **{row['keyword']}**  ·  Category: **{row['category']}**")

cards = metric_cards(row)
card_columns = st.columns(5)
card_columns[0].metric("Peak value", cards["peak_value"])
card_columns[1].metric("Peak date", cards["peak_date"])
card_columns[2].metric("% dropped", cards["pct_dropped"])
card_columns[3].metric("Decay rate", cards["decay_rate"])
card_columns[4].metric("Weeks to 50%", cards["weeks_to_half"])

st.caption(f"Status: **{cards['status']}**")
if cards["flags"]:
    st.caption(f"Caveats: {cards['flags']}")

st.pyplot(plot_trend_series(trend_series, row))
st.pyplot(plot_trend_vs_median(series, metrics, trend_id))

st.subheader("Curation notes")
st.write(catalog_notes(trend_id))
