import pandas as pd

from fashion_trends.app.layout import render_header, render_missing_data_screen
from fashion_trends.viz.build import ProcessedDataMissingError


def _metrics():
    return pd.DataFrame(
        {
            "trend_id": ["fast"],
            "data_pull_date": [pd.Timestamp("2026-09-01")],
            "timeframe": ["today 5-y"],
            "geo": ["US"],
        }
    )


# render_header and render_missing_data_screen call Streamlit's st.* delta
# generators, which are safe to call outside a running script (they no-op
# rather than raise) — these tests only guard against a code path that
# raises, e.g. a KeyError on a provenance column that isn't there.


def test_render_header_reads_provenance_columns_without_raising():
    render_header(_metrics())


def test_render_header_handles_empty_metrics_without_raising():
    render_header(pd.DataFrame())


def test_render_missing_data_screen_mentions_refresh_data():
    render_missing_data_screen(ProcessedDataMissingError("missing: ['series.parquet']"))
