"""Plain-language explanations for every chart and table in the dashboard.

Centralized here (rather than inline in `app/views/`) because the same chart
can appear on more than one page, and so `tests/test_app_explainers.py` can
assert every rendered chart has an explanation registered.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from fashion_trends.app.styles import render_note

__all__ = [
    "CHART_EXPLAINERS",
    "ChartExplainer",
    "get_explainer",
    "render_explainer",
]

MAX_READING_LINES = 3


@dataclass(frozen=True)
class ChartExplainer:
    """The explanatory copy that accompanies one chart or table.

    `summary` is the one-sentence takeaway shown under the figure; `reading`
    is the key to its visual elements, printed below that.
    """

    summary: str
    reading: tuple[str, ...]


CHART_EXPLAINERS: dict[str, ChartExplainer] = {
    "decay_curves": ChartExplainer(
        summary="Every trend's fall from its own peak, drawn on top of one another.",
        reading=(
            "Week 0 is each trend's own peak and 100% its own peak height, that is what makes them comparable.",
            "The dashed line at 50% is where a trend has given up half its peak.",
            "Bold lines are the fastest and slowest; faint grey lines are every other trend.",
        ),
    ),
    "drop_ranking": ChartExplainer(
        summary="How far each trend has fallen from its peak, biggest faller first.",
        reading=(
            "Bar length is the drop from the peak to where the trend sits now.",
            "Bar colour is the lifecycle label, keyed in the legend on the chart.",
            "Each name carries its peak month. An 85% drop off a 2021 peak is a different story from a 2025 one.",
        ),
    ),
    "time_to_decline": ChartExplainer(
        summary="How many weeks each trend took to lose half its peak, fastest at the top.",
        reading=(
            "Bar length is weeks from the peak until interest stayed below half of it.",
            "The hatched block at the top is trends that never fell that far.",
            "Short bars are flash fads; long bars held their audience for months.",
        ),
    ),
    "trend_series": ChartExplainer(
        summary="The full weekly history, with the moments every number above is measured from.",
        reading=(
            "Grey is the raw weekly interest; the coloured line is the smoothed version the analysis reads.",
            "The dashed vertical marks the peak week; the dotted horizontal sits at half the peak.",
            "An × marks the week it dropped below half for good. A triangle marks a revival.",
        ),
    ),
    "trend_vs_median": ChartExplainer(
        summary="Whether this trend died faster or slower than a typical trend here.",
        reading=(
            "Both lines start at their own peak: week 0, 100%.",
            "The grey line is the median of every other trend, this one left out of it.",
            "Below the grey line means it fell faster than the pack; above means it held on longer.",
        ),
    ),
    "overview_table": ChartExplainer(
        summary="Every trend behind the charts. Click a column header to sort by it.",
        reading=(
            "Hover a column header for what that metric means.",
            'Words in place of numbers are findings, not gaps: "still rising", "never fell below 50%", '
            '"no usable peak detected".',
            "Caveats flags the rows whose numbers deserve more scepticism.",
        ),
    ),
    "live_series": ChartExplainer(
        summary="The same analysis the curated catalog gets, run on the keyword you typed.",
        reading=(
            "Grey is the raw weekly interest; the coloured line is the smoothed version.",
            "The dashed vertical marks the peak week; the dotted horizontal sits at half the peak.",
            "A flat line with one spike usually means the keyword is too rare for Google Trends to resolve.",
        ),
    ),
}


def get_explainer(key: str) -> ChartExplainer:
    """The `ChartExplainer` registered under `key`, or a `KeyError` naming the available keys."""
    try:
        return CHART_EXPLAINERS[key]
    except KeyError:
        raise KeyError(f"No chart explainer registered for {key!r}. Registered: {sorted(CHART_EXPLAINERS)}") from None


def render_explainer(key: str) -> None:
    """Render one figure's summary line and its "how to read this" key, below the figure."""
    explainer = get_explainer(key)
    render_note(explainer.summary)

    st.markdown("**How to read this chart**")
    for line in explainer.reading:
        st.markdown(f"- {line}")
