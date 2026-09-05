"""Overview page: ranked metrics table with filters.

The landing view: every trend, its headline metrics, sortable by column and
filterable by category and lifecycle status, with summary tiles and the
ranked drop-from-peak chart following whatever filters are active. All the
shaping logic lives in `fashion_trends.app.overview` so it can be unit tested
without a running Streamlit script; this page only wires widgets to it.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.app.data import get_settings, load_dashboard_data
from fashion_trends.app.overview import (
    ALL_CATEGORIES,
    ALL_STATUSES,
    OVERVIEW_COLUMN_HELP,
    OVERVIEW_COLUMN_LABELS,
    filter_metrics,
    format_overview_table,
    summary_tiles,
)
from fashion_trends.viz.rankings import plot_drop_ranking

st.title("Overview")

_series, metrics = load_dashboard_data(get_settings())

if metrics.empty:
    st.info("No trend data loaded.")
    st.stop()

category_options = [ALL_CATEGORIES, *sorted(metrics["category"].dropna().unique())]
status_options = [ALL_STATUSES, *sorted(metrics["status"].dropna().unique())]

filter_col1, filter_col2 = st.columns(2)
category = filter_col1.selectbox("Category", category_options)
status = filter_col2.selectbox("Lifecycle status", status_options)

filtered = filter_metrics(metrics, category, status)

if filtered.empty:
    st.warning("No trends match the selected filters.")
    st.stop()

tiles = summary_tiles(filtered)
tile_col1, tile_col2, tile_col3 = st.columns(3)
tile_col1.metric(
    "Median % dropped",
    f"{tiles['median_pct_dropped']:.0f}%" if tiles["median_pct_dropped"] is not None else "n/a",
)
tile_col2.metric(
    "Median weeks to 50%",
    f"{tiles['median_weeks_to_half']:.0f}" if tiles["median_weeks_to_half"] is not None else "n/a",
)
tile_col3.metric("Trends shown", len(filtered))
st.caption(" · ".join(f"{status_name}: {count}" for status_name, count in sorted(tiles["status_counts"].items())))

st.dataframe(
    format_overview_table(filtered),
    hide_index=True,
    column_config={
        column: st.column_config.Column(OVERVIEW_COLUMN_LABELS[column], help=OVERVIEW_COLUMN_HELP[column])
        for column in OVERVIEW_COLUMN_HELP
    },
)

st.pyplot(plot_drop_ranking(filtered))
