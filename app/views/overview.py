"""Overview page: filter row, four headline tiles, then the catalog-wide charts and table, one per tab.

Shaping logic lives in `fashion_trends.app.overview`; chart copy in
`fashion_trends.app.explainers`. This page only wires widgets to them.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.app.data import get_settings, load_dashboard_data
from fashion_trends.app.explainers import render_explainer
from fashion_trends.app.layout import render_chart, render_interactive_chart
from fashion_trends.app.overview import (
    ALL_CATEGORIES,
    ALL_STATUSES,
    OVERVIEW_COLUMN_HELP,
    OVERVIEW_COLUMN_LABELS,
    filter_metrics,
    format_overview_table,
    summary_tiles,
)
from fashion_trends.app.styles import render_metric_card, status_pill_row
from fashion_trends.viz.decay_curves import plot_decay_curves_interactive
from fashion_trends.viz.rankings import plot_drop_ranking, plot_time_to_decline

series, metrics = load_dashboard_data(get_settings())

if metrics.empty:
    st.info("No trend data loaded.")
    st.stop()

# ---- filters ----------------------------------------------------------

category_options = [ALL_CATEGORIES, *sorted(metrics["category"].dropna().unique())]
status_options = [ALL_STATUSES, *sorted(metrics["status"].dropna().unique())]

filter_col1, filter_col2, _spacer = st.columns([1, 1, 2])
category = filter_col1.selectbox("Category", category_options)
status = filter_col2.selectbox("Lifecycle status", status_options)

filtered = filter_metrics(metrics, category, status)

if filtered.empty:
    st.warning("No trends match those filters. Widen one of them to see results.")
    st.stop()

# ---- headline numbers -------------------------------------------------

tiles = summary_tiles(filtered)
fastest = tiles["fastest_collapse"]

tile_col1, tile_col2, tile_col3, tile_col4 = st.columns(4)
tile_col1.metric("Trends shown", len(filtered), help="How many of the catalog's trends pass the filters above.")
tile_col2.metric(
    "Median % dropped",
    f"{tiles['median_pct_dropped']:.0f}%" if tiles["median_pct_dropped"] is not None else "n/a",
    help="The middle trend's fall from its own peak. Half the set has dropped more than this, half less.",
)
tile_col3.metric(
    "Median weeks to 50%",
    f"{tiles['median_weeks_to_half']:.0f}" if tiles["median_weeks_to_half"] is not None else "n/a",
    help="Weeks the middle trend took to lose half its peak. Counts only trends that have crossed that line.",
)
with tile_col4:
    render_metric_card(
        "Fastest collapse",
        f"{fastest[1]} wk" if fastest else "n/a",
        note=fastest[0] if fastest else None,
    )

st.markdown(status_pill_row(tiles["status_counts"]), unsafe_allow_html=True)

# ---- the charts and the table, one per tab ----------------------------

curves_tab, drop_tab, time_tab, table_tab = st.tabs(
    ["Decay curves", "Drop from peak", "Time to 50%", "Full table"],
)

with curves_tab, st.container(border=True):
    render_interactive_chart(plot_decay_curves_interactive(series, filtered))
    render_explainer("decay_curves")

with drop_tab, st.container(border=True):
    render_chart(plot_drop_ranking(filtered))
    render_explainer("drop_ranking")

with time_tab, st.container(border=True):
    render_chart(plot_time_to_decline(filtered))
    render_explainer("time_to_decline")

with table_tab, st.container(border=True):
    st.dataframe(
        format_overview_table(filtered),
        hide_index=True,
        use_container_width=True,
        column_config={
            column: st.column_config.Column(OVERVIEW_COLUMN_LABELS[column], help=OVERVIEW_COLUMN_HELP[column])
            for column in OVERVIEW_COLUMN_HELP
        },
    )
    render_explainer("overview_table")
