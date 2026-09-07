"""The signature figure: every trend's post-peak trajectory on one axis.

Aligning each trend's own peak to week 0 and its own peak value to 100% is
what makes a niche trend and a mainstream one comparable on the same plot.

`pre_peak` and `peak_at_boundary` trends (see `fashion_trends.metrics.peaks`)
are left out of the overlay, with the saved figure's caption naming them
rather than silently dropping them.

With around two dozen eligible trends the full overlay is unreadable as
spaghetti, so only the fastest collapses and slowest fades (picked by
`select_highlighted_trends`) are drawn bold and labelled, each in its own
colour from `HIGHLIGHT_COLORS` rather than its category's (only four
category colours exist, too few to keep several highlighted trends apart).

`plot_decay_curves` (matplotlib, static) is what `save_decay_curves_figure`
and `scripts/build_charts.py` write to `outputs/figures/`.
`plot_decay_curves_interactive` (Plotly) is the dashboard Overview page's
copy of the same overlay, sharing every helper above with it so the two
never drift apart; it's the one with pan/zoom/hover.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go

from fashion_trends.metrics.decay import HALF_LIFE_CROSSED, HALF_LIFE_STILL_ABOVE
from fashion_trends.settings import Settings
from fashion_trends.viz.theme import (
    DASH_BY_LINESTYLE,
    apply_theme,
    category_style,
    line_chart_grid,
    plotly_caption_annotation,
    plotly_layout_defaults,
    save_figure,
)

if TYPE_CHECKING:
    from matplotlib.figure import Figure

# Weeks of lead-in drawn before the peak (x=0).
LEAD_IN_WEEKS = 4

# How many of the fastest-collapsing/slowest-fading eligible trends get a bold, labelled line.
HIGHLIGHT_FASTEST = 3
HIGHLIGHT_SLOWEST = 3

FAINT_COLOR = "#B0B0B0"
FAINT_ALPHA = 0.5
FAINT_LINEWIDTH = 1.0
HIGHLIGHT_LINEWIDTH = 2.2

# A highlighted line's colour comes from this rotation rather than its
# category, since `category_style` only has four colours.
HIGHLIGHT_COLORS = [
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#009E73",  # bluish green
    "#E69F00",  # orange
    "#CC79A7",  # reddish purple
    "#56B4E9",  # sky blue
    "#F0E442",  # yellow
    "#000000",  # black
]

HALF_LIFE_REFERENCE_PCT = 50.0

DEFAULT_FILENAME = "decay_curves.png"


def _eligible_trends(metrics: pd.DataFrame) -> pd.DataFrame:
    """Metrics rows with a post-peak segment worth overlaying, excluding `pre_peak` and `peak_at_boundary` trends."""
    return metrics[~metrics["pre_peak"] & ~metrics["peak_at_boundary"]]


def select_highlighted_trends(
    metrics: pd.DataFrame,
    n_fast: int = HIGHLIGHT_FASTEST,
    n_slow: int = HIGHLIGHT_SLOWEST,
) -> set[str]:
    """`trend_id`s to draw bold: the fastest collapses and the slowest fades."""
    eligible = _eligible_trends(metrics)

    fastest = eligible[eligible["time_to_half_status"] == HALF_LIFE_CROSSED].nsmallest(n_fast, "weeks_to_half")["trend_id"]
    slowest = eligible[eligible["time_to_half_status"] == HALF_LIFE_STILL_ABOVE].nlargest(n_slow, "weeks_since_peak")["trend_id"]

    return set(fastest) | set(slowest)


def _highlight_color_map(highlighted: set[str]) -> dict[str, str]:
    """One colour per highlighted `trend_id`, sorted for a stable assignment run to run."""
    return dict(zip(sorted(highlighted), itertools.cycle(HIGHLIGHT_COLORS)))


def build_decay_curve_frame(series: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """One row per (eligible trend, week): weeks since peak and % of that trend's own peak.

    `weeks_since_peak` is negative for the `LEAD_IN_WEEKS` before a trend's
    own peak and 0 at the peak itself; `pct_of_peak` is `interest_smooth` as
    a percentage of that trend's own `peak_value`. Rows with no smoothed
    observation (a gap week) are dropped rather than plotted as 0.
    """
    eligible_peaks = _eligible_trends(metrics)[["trend_id", "peak_date", "peak_value"]]
    merged = series.merge(eligible_peaks, on="trend_id", how="inner")

    weeks_since_peak = (merged["date"] - merged["peak_date"]).dt.days // 7
    merged = merged.assign(
        weeks_since_peak=weeks_since_peak,
        pct_of_peak=merged["interest_smooth"] / merged["peak_value"] * 100,
    )
    merged = merged[merged["weeks_since_peak"] >= -LEAD_IN_WEEKS]
    merged = merged.dropna(subset=["pct_of_peak"])

    return merged[["trend_id", "display_name", "category", "weeks_since_peak", "pct_of_peak"]]


def _excluded_caption(metrics: pd.DataFrame) -> str:
    """Caption naming the trends left out of the overlay, or `""` if none were."""
    excluded = metrics[metrics["pre_peak"] | metrics["peak_at_boundary"]]
    if excluded.empty:
        return ""
    names = ", ".join(sorted(excluded["display_name"]))
    return f"Excluded (still rising, or peak at the edge of the pulled window): {names}"


def plot_decay_curves(series: pd.DataFrame, metrics: pd.DataFrame) -> Figure:
    """Build the peak-aligned decay curve overlay. See the module docstring."""
    apply_theme()
    frame = build_decay_curve_frame(series, metrics)
    highlighted = select_highlighted_trends(metrics)
    highlight_colors = _highlight_color_map(highlighted)

    fig, ax = plt.subplots()
    line_chart_grid(ax)

    for trend_id, group in frame.groupby("trend_id", sort=False):
        group = group.sort_values("weeks_since_peak")
        if trend_id in highlighted:
            style = category_style(group["category"].iloc[0])
            ax.plot(
                group["weeks_since_peak"],
                group["pct_of_peak"],
                label=group["display_name"].iloc[0],
                color=highlight_colors[trend_id],
                linestyle=style["linestyle"],
                linewidth=HIGHLIGHT_LINEWIDTH,
                zorder=3,
            )
        else:
            ax.plot(
                group["weeks_since_peak"],
                group["pct_of_peak"],
                color=FAINT_COLOR,
                alpha=FAINT_ALPHA,
                linewidth=FAINT_LINEWIDTH,
                zorder=1,
            )

    ax.axhline(HALF_LIFE_REFERENCE_PCT, color="#333333", linestyle="--", linewidth=1.0, zorder=2)
    ax.axvline(0, color="#999999", linewidth=0.8, zorder=0)

    ax.set_xlabel("Weeks since peak")
    ax.set_ylabel("% of trend's own peak")
    ax.set_title("Peak-aligned decay curves")
    if highlighted:
        ax.legend(loc="upper right", fontsize=8, title="Fastest & slowest")

    caption = _excluded_caption(metrics)
    if caption:
        fig.text(0.01, 0.04, caption, ha="left", va="bottom", fontsize=7, color="#6B645C", style="italic")

    return fig


def plot_decay_curves_interactive(series: pd.DataFrame, metrics: pd.DataFrame) -> go.Figure:
    """`plot_decay_curves`, as an interactive Plotly figure for the dashboard. See the module docstring."""
    frame = build_decay_curve_frame(series, metrics)
    highlighted = select_highlighted_trends(metrics)
    highlight_colors = _highlight_color_map(highlighted)

    fig = go.Figure()

    for trend_id, group in frame.groupby("trend_id", sort=False):
        group = group.sort_values("weeks_since_peak")
        display_name = group["display_name"].iloc[0]
        if trend_id in highlighted:
            style = category_style(group["category"].iloc[0])
            fig.add_trace(
                go.Scatter(
                    x=group["weeks_since_peak"],
                    y=group["pct_of_peak"],
                    mode="lines",
                    name=display_name,
                    line={
                        "color": highlight_colors[trend_id],
                        "width": HIGHLIGHT_LINEWIDTH,
                        "dash": DASH_BY_LINESTYLE.get(style["linestyle"], "solid"),
                    },
                )
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=group["weeks_since_peak"],
                    y=group["pct_of_peak"],
                    mode="lines",
                    name=display_name,
                    line={"color": FAINT_COLOR, "width": FAINT_LINEWIDTH},
                    opacity=FAINT_ALPHA,
                    showlegend=False,
                )
            )

    fig.add_hline(y=HALF_LIFE_REFERENCE_PCT, line={"color": "#333333", "width": 1, "dash": "dash"})
    fig.add_vline(x=0, line={"color": "#999999", "width": 0.8})

    fig.update_layout(**plotly_layout_defaults())
    fig.update_layout(
        hovermode="closest",  # "x unified" over ~20 overlapping lines is unreadable
        xaxis_title="Weeks since peak",
        yaxis_title="% of trend's own peak",
        title={"text": "Peak-aligned decay curves", "x": 0, "xanchor": "left"},
        legend={"orientation": "v", "x": 1, "xanchor": "right", "y": 1, "yanchor": "top", "title": "Fastest & slowest"},
    )

    caption = _excluded_caption(metrics)
    if caption:
        fig.add_annotation(plotly_caption_annotation(caption))

    return fig


def save_decay_curves_figure(
    series: pd.DataFrame,
    metrics: pd.DataFrame,
    settings: Settings | None = None,
) -> Path:
    """Build and save the decay curve chart to `outputs/figures/decay_curves.png`."""
    settings = settings or Settings()
    fig = plot_decay_curves(series, metrics)
    pull_date = metrics["data_pull_date"].iloc[0]
    timeframe = metrics["timeframe"].iloc[0]
    return save_figure(fig, settings.figures_dir / DEFAULT_FILENAME, pull_date=pull_date, timeframe=timeframe)
