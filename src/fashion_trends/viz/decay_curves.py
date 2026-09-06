"""The signature figure: every trend's post-peak trajectory on one axis.

Every trend peaks at a different week and a different height, so plotting
raw `interest_smooth` against calendar date can't compare their shapes at
all. Aligning each trend's own peak to week 0 and its own peak value to
100% is what makes a niche trend and a mainstream one comparable on the same
plot — the question this chart answers is "how fast did it fall", not "how
popular was it".

`pre_peak` and `peak_at_boundary` trends (see `fashion_trends.metrics.peaks`)
are left out of the overlay entirely: a trend still climbing into its peak,
or one whose peak sits at the edge of the pulled window, has no post-peak
segment worth calling a decay curve, and the caption on the saved figure
says so rather than silently dropping them.

With around two dozen eligible trends the full overlay is unreadable as
spaghetti, so only a handful of lines are drawn bold and labelled — the
fastest collapses and the slowest fades, picked by `select_highlighted_trends`
— while every other eligible trend still draws, just faint and grey. That
contrast is what lets a reader tell a fast-collapse trend from a slow-fade
one without reading the legend.

Each highlighted line also gets its own colour, from `HIGHLIGHT_COLORS`
rather than from its category: category has only four colours, so two
highlighted trends sharing one would otherwise draw identically and be
impossible to tell apart on the plot despite the legend naming them
separately.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd

from fashion_trends.metrics.decay import HALF_LIFE_CROSSED, HALF_LIFE_STILL_ABOVE
from fashion_trends.settings import Settings
from fashion_trends.viz.theme import apply_theme, category_style, line_chart_grid, save_figure

if TYPE_CHECKING:
    from matplotlib.figure import Figure

# Weeks of lead-in drawn before the peak (x=0), so a highlighted line shows
# how a trend approached its peak rather than starting the plot cold at the
# top.
LEAD_IN_WEEKS = 4

# How many of the fastest-collapsing and slowest-fading eligible trends get a
# bold, legend-labelled line. Everything else eligible still draws, just
# faint -- see the module docstring for why.
HIGHLIGHT_FASTEST = 3
HIGHLIGHT_SLOWEST = 3

FAINT_COLOR = "#B0B0B0"
FAINT_ALPHA = 0.5
FAINT_LINEWIDTH = 1.0
HIGHLIGHT_LINEWIDTH = 2.2

# A highlighted line's colour comes from this rotation, one per line, rather
# than from its category: `category_style` only has four colours, so two
# highlighted trends sharing a category would draw identically otherwise --
# indistinguishable from each other despite the legend naming them
# separately. The full eight-colour Okabe-Ito palette covers every
# highlighted line even at the default 3 fastest + 3 slowest, with room to
# spare if either count grows; `itertools.cycle` only repeats a colour if it
# ever doesn't.
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
    """Metrics rows with a post-peak segment worth overlaying.

    Excludes `pre_peak` (still climbing into its peak -- nothing to decay
    from yet) and `peak_at_boundary` (the real peak may sit outside the
    pulled window, so its "decay" would describe a fragment rather than a
    lifecycle) trends. See the module docstring.
    """
    return metrics[~metrics["pre_peak"] & ~metrics["peak_at_boundary"]]


def select_highlighted_trends(
    metrics: pd.DataFrame,
    n_fast: int = HIGHLIGHT_FASTEST,
    n_slow: int = HIGHLIGHT_SLOWEST,
) -> set[str]:
    """`trend_id`s to draw bold: the fastest collapses and the slowest fades.

    Picking the extremes on both ends of `weeks_to_half` -- the smallest
    among trends that crossed the half-life threshold, and the largest
    `weeks_since_peak` among trends that never have -- is what puts the
    fast-collapse/slow-fade contrast directly in front of the reader instead
    of leaving it to be inferred from ~25 unlabelled lines.
    """
    eligible = _eligible_trends(metrics)

    fastest = eligible[eligible["time_to_half_status"] == HALF_LIFE_CROSSED].nsmallest(n_fast, "weeks_to_half")["trend_id"]
    slowest = eligible[eligible["time_to_half_status"] == HALF_LIFE_STILL_ABOVE].nlargest(n_slow, "weeks_since_peak")["trend_id"]

    return set(fastest) | set(slowest)


def _highlight_color_map(highlighted: set[str]) -> dict[str, str]:
    """One colour per highlighted `trend_id`, sorted for a stable assignment run to run."""
    return dict(zip(sorted(highlighted), itertools.cycle(HIGHLIGHT_COLORS)))


def build_decay_curve_frame(series: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """One row per (eligible trend, week): weeks since peak and % of that trend's own peak.

    `series` has `series.parquet`'s shape -- one row per (trend, week) with
    `date`, `trend_id`, and `interest_smooth` columns. `metrics` has
    `metrics.parquet`'s shape, supplying each trend's `peak_date`,
    `peak_value`, `display_name`, and `category`, plus the `pre_peak`/
    `peak_at_boundary` flags `_eligible_trends` filters on.

    `weeks_since_peak` is negative for the `LEAD_IN_WEEKS` before a trend's
    own peak and 0 at the peak itself; `pct_of_peak` is `interest_smooth` as
    a percentage of that trend's own `peak_value`, so every trend's peak
    week reads as 100 regardless of how popular it ever was. Rows with no
    smoothed observation (a gap week) are dropped rather than plotted as 0.

    `display_name` and `category` are read from `series`, not `metrics` --
    both frames carry them, and merging in `metrics`'s copy alongside would
    only create columns to immediately disambiguate.
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


def save_decay_curves_figure(
    series: pd.DataFrame,
    metrics: pd.DataFrame,
    settings: Settings | None = None,
) -> Path:
    """Build and save the decay curve chart to `outputs/figures/decay_curves.png`.

    `pull_date` and `timeframe` for `save_figure`'s footer come from
    `metrics`'s own provenance columns rather than a separate argument --
    every row of one run's `metrics.parquet` already carries the same
    `data_pull_date`/`timeframe` (see `fashion_trends.metrics.compute_all`),
    so there is nothing here for a caller to supply that isn't already in
    the frame it's handing in.
    """
    settings = settings or Settings()
    fig = plot_decay_curves(series, metrics)
    pull_date = metrics["data_pull_date"].iloc[0]
    timeframe = metrics["timeframe"].iloc[0]
    return save_figure(fig, settings.figures_dir / DEFAULT_FILENAME, pull_date=pull_date, timeframe=timeframe)
