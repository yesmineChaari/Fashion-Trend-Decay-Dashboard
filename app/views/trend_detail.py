"""Trend detail page: one trend's metric cards, weekly series, and decay against the median.

Shaping lives in `fashion_trends.app.trend_detail`, charts in
`fashion_trends.viz.trend_detail`, chart copy in `fashion_trends.app.explainers`.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.app.data import get_settings, load_dashboard_data
from fashion_trends.app.explainers import render_explainer
from fashion_trends.app.layout import render_interactive_chart, render_page_heading
from fashion_trends.app.styles import status_pill
from fashion_trends.app.trend_detail import metric_cards, status_explanation
from fashion_trends.viz.trend_detail import plot_trend_series, plot_trend_vs_median

series, metrics = load_dashboard_data(get_settings())

if metrics.empty:
    st.info("No trend data loaded.")
    st.stop()

# ---- pick a trend -----------------------------------------------------

trend_ids_by_name = dict(zip(metrics["display_name"], metrics["trend_id"], strict=True))
selector_column, _spacer = st.columns([1, 2])
selected_name = selector_column.selectbox("Trend", sorted(trend_ids_by_name))

trend_id = trend_ids_by_name[selected_name]
row = metrics.loc[metrics["trend_id"] == trend_id].iloc[0]
trend_series = series.loc[series["trend_id"] == trend_id]
cards = metric_cards(row)

# ---- headline ---------------------------------------------------------

render_page_heading(selected_name)

explanation = status_explanation(row["status"])
st.markdown(
    f"{status_pill(row['status'])}&nbsp;&nbsp;"
    f'<span style="font-size:0.85rem;">{explanation + " · " if explanation else ""}'
    f"searched as <strong>“{row['keyword']}”</strong> · category <strong>{row['category']}</strong></span>",
    unsafe_allow_html=True,
)

card_columns = st.columns(5)
card_columns[0].metric("Peak value", cards["peak_value"], help="Interest at the peak week, on this trend's own 0-100 scale.")
card_columns[1].metric("Peak date", cards["peak_date"], help="The week this trend's search interest was highest.")
card_columns[2].metric("% dropped", cards["pct_dropped"], help="How far it has fallen from that peak to where it sits now.")
card_columns[3].metric("Decay rate", cards["decay_rate"], help="Percentage points of the peak lost per week since peaking.")
card_columns[4].metric("Weeks to 50%", cards["weeks_to_half"], help="Weeks from the peak until it stayed below half of it.")

if cards["flags"]:
    st.warning(f"**Read with care:** {cards['flags']}.")

# ---- charts -----------------------------------------------------------

with st.container(border=True):
    render_interactive_chart(plot_trend_series(trend_series, row))
    render_explainer("trend_series")

with st.container(border=True):
    render_interactive_chart(plot_trend_vs_median(series, metrics, trend_id))
    render_explainer("trend_vs_median")
