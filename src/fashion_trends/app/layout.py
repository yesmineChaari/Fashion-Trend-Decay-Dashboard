"""Shared page chrome for the Streamlit dashboard.

One module so every page renders the same masthead, the same sidebar, and
the same first-run message, rather than each page under `app/views/`
deciding independently how to phrase any of them. The look itself is
`fashion_trends.app.styles`; this module decides what goes where, and calls
`inject_styles` once at the top of every page so no page has to remember to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from fashion_trends.app.styles import PALETTE, inject_styles, render_kicker, render_note
from fashion_trends.viz.build import ProcessedDataMissingError

if TYPE_CHECKING:
    from matplotlib.figure import Figure

WORDMARK = "Fashion Trends"
STANDFIRST = (
    "A record of how quickly fashion micro-trends lose their audience. For any trend here you can check "
    "when it peaked, how far it has fallen since, how fast it fell, and how long it took to lose half its "
    "peak — measured identically for all of them, so they can be compared against each other, or against "
    "any keyword you search yourself. It exists because a look is usually declared over on instinct, and "
    "search interest is one part of that claim you can actually measure."
)


def _format_pull_date(pull_date: object) -> str:
    return pull_date.date().isoformat() if hasattr(pull_date, "date") else str(pull_date)


def _chip(label: str, value: str) -> str:
    return f'<span class="ft-chip"><span class="ft-chip-label">{label}</span><span class="ft-chip-value">{value}</span></span>'


def provenance_chips(metrics: pd.DataFrame) -> str:
    """The dataset's pull date, window, geo, and size, as a row of chip markup.

    Reads only `metrics`'s own provenance columns (see
    `fashion_trends.metrics.schema.PROVENANCE_COLUMNS`) — the same source
    every static figure's footer uses, via
    `fashion_trends.viz.theme.save_figure` — so the dashboard and the
    exported charts can never disagree about which run's numbers are on
    screen. Returns markup rather than rendering, so the chips land in a
    single `st.markdown` call and lay out as one row.
    """
    chips = [
        _chip("Trends", str(len(metrics))),
        _chip("Pulled", _format_pull_date(metrics["data_pull_date"].iloc[0])),
        _chip("Window", str(metrics["timeframe"].iloc[0])),
        _chip("Geo", str(metrics["geo"].iloc[0]) or "Worldwide"),
        _chip("Source", "Google Trends"),
    ]
    return f'<div class="ft-chips">{"".join(chips)}</div>'


def render_header(metrics: pd.DataFrame) -> None:
    """Render the masthead: wordmark, headline, standfirst, and provenance chips.

    An analysis of how far things have fallen "since peak" is misleading the
    moment it is a week old and undated, which is why the pull date is part
    of the masthead rather than a footnote — same reasoning as
    `fashion_trends.viz.theme.save_figure`'s mandatory footer.
    """
    inject_styles()

    if metrics.empty:
        st.markdown(
            f'<div class="ft-masthead"><div class="ft-wordmark">{WORDMARK}</div>'
            '<div class="ft-masthead-title">No trend data loaded</div></div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div class="ft-masthead">'
        f'<div class="ft-wordmark">{WORDMARK}</div>'
        f'<h1 class="ft-masthead-title">The half-life of a micro-trend</h1>'
        f'<p class="ft-standfirst">{STANDFIRST}</p>'
        f"{provenance_chips(metrics)}"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_page_heading(title: str, note: str = "") -> None:
    """Render one page's own heading under the shared masthead.

    The masthead carries the project; this carries the page. Kept to `h2` so
    there is exactly one `h1` on screen and the two never compete.
    """
    st.markdown(f"## {title}")
    if note:
        render_note(note)


def render_chart(fig: Figure) -> None:
    """Render a matplotlib figure and release it.

    Streamlit re-runs the whole script on every widget interaction, and
    `st.pyplot` does not close what it draws — so without this a session
    filing through the trend selector leaks a figure per rerun and matplotlib
    eventually starts warning about it on the console. Closing immediately
    after rendering is safe: `st.pyplot` has already rasterised the figure by
    the time this returns.
    """
    st.pyplot(fig)
    plt.close(fig)


def render_sidebar(metrics: pd.DataFrame) -> None:
    """Render the one standing caveat, below Streamlit's page navigation.

    Deliberately almost empty. An earlier version also carried a glossary of
    the six lifecycle labels, which every page then repeated in its own
    pills, chart legends, and Status column — the sidebar and the page were
    saying the same thing twice, on every page. The labels are explained
    where they are used; what is left here is the one thing no chart can
    show, which is what the underlying 0-100 numbers are.

    `metrics` is unused today and kept in the signature because this is the
    dashboard's one dataset-scoped sidebar hook: anything added here later
    describes the loaded set, and every caller already has it to hand.
    """
    with st.sidebar:
        render_kicker("Reading the numbers")
        st.markdown(
            f'<div style="font-size:0.8rem;line-height:1.55;color:{PALETTE["ink_muted"]};">'
            "Every score here runs 0 to 100, where 100 is just a trend's single busiest week — not an "
            "actual count of searches. Scoring each trend against its own busiest week is what lets you "
            "compare a niche look and a mainstream one side by side."
            "</div>",
            unsafe_allow_html=True,
        )


def render_missing_data_screen(error: ProcessedDataMissingError) -> None:
    """Render the friendly first-run screen shown in place of the dashboard's pages.

    Used when `app.data.load_dashboard_data` raises `ProcessedDataMissingError`
    — i.e. `data/processed/` is still empty — so a first run tells the user
    to run `scripts/refresh_data.py` instead of surfacing a raw
    `FileNotFoundError` traceback.
    """
    inject_styles()
    st.markdown(
        f'<div class="ft-masthead"><div class="ft-wordmark">{WORDMARK}</div>'
        '<h1 class="ft-masthead-title">Nothing measured yet</h1>'
        '<p class="ft-standfirst">The dashboard reads processed parquet files rather than fetching '
        "anything itself, and those files have not been built yet.</p></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "Run the ingestion pipeline once to populate `data/processed/`, then reload this page:\n\n"
        "```bash\npython scripts/refresh_data.py\n```\n\n"
        "Add `--offline` to build it from the committed fixture snapshot instead of calling Google Trends."
    )
    st.caption(str(error))
