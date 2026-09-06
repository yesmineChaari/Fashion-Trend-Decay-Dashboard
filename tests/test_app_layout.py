import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from fashion_trends.app.layout import (
    provenance_chips,
    render_chart,
    render_header,
    render_missing_data_screen,
    render_page_heading,
    render_sidebar,
)
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


# Streamlit's st.* calls no-op outside a running script; these tests only
# guard against a code path that raises, e.g. a missing provenance column.


def test_render_header_reads_provenance_columns_without_raising():
    render_header(_metrics())


def test_render_header_handles_empty_metrics_without_raising():
    render_header(pd.DataFrame())


def test_render_missing_data_screen_mentions_refresh_data():
    render_missing_data_screen(ProcessedDataMissingError("missing: ['series.parquet']"))


def test_render_sidebar_handles_metrics_without_a_status_column():
    # The provenance-only frame above has no `status`; the glossary should
    # fall back to listing every label rather than raising a KeyError.
    render_sidebar(_metrics())


def test_render_sidebar_handles_empty_metrics_without_raising():
    render_sidebar(pd.DataFrame())


def test_render_page_heading_renders_with_and_without_a_note():
    render_page_heading("Overview")
    render_page_heading("Overview", "A note under the heading.")


# ---- provenance_chips ----------------------------------------------------


def test_provenance_chips_name_the_pull_date_timeframe_and_geo():
    markup = provenance_chips(_metrics())

    assert "2026-09-01" in markup
    assert "today 5-y" in markup
    assert "US" in markup


def test_provenance_chips_count_the_trends_in_the_frame():
    markup = provenance_chips(_metrics())

    assert ">1<" in markup


# ---- render_chart ----------------------------------------------------


def test_render_chart_closes_the_figure_it_renders():
    # Streamlit reruns the whole script on every interaction, so a figure the
    # dashboard forgets to close leaks once per rerun.
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [1, 4, 9])

    render_chart(fig)

    assert not plt.fignum_exists(fig.number)
