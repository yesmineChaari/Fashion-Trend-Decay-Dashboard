"""Per-trend detail charts: the full weekly series, and this trend against the pack.

`plot_trend_series` draws one trend's raw and smoothed weekly interest with
its peak, 50%-of-peak threshold, and (if any) crossing week marked.
`plot_trend_vs_median` reuses `fashion_trends.viz.decay_curves`'s
peak-alignment to compare this trend's decay against the median of every
other eligible trend.

Both charts skip an annotation rather than guess when the metric behind it
is null (pre-peak, no usable peak, never crossed half its peak).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd

from fashion_trends.metrics.decay import HALF_LIFE_CROSSED, HALF_LIFE_STILL_ABOVE
from fashion_trends.viz.decay_curves import HALF_LIFE_REFERENCE_PCT, build_decay_curve_frame
from fashion_trends.viz.theme import apply_theme, category_style, line_chart_grid

if TYPE_CHECKING:
    from matplotlib.figure import Figure

RAW_COLOR = "#B0B0B0"
RAW_ALPHA = 0.6
RAW_LINEWIDTH = 1.0
SMOOTH_LINEWIDTH = 2.2

PEAK_MARKER_COLOR = "#333333"
SECONDARY_PEAK_MARKER_COLOR = "#E69F00"
HALF_LIFE_MARKER_COLOR = "#D55E00"
THRESHOLD_LINE_COLOR = "#999999"

CAPTION_FONTSIZE = 7
CAPTION_COLOR = "#6B645C"

MEDIAN_LINE_COLOR = "#999999"


# ---- full weekly series ----------------------------------------------------


def _series_caption(metrics_row: pd.Series) -> str:
    """Caption explaining a missing peak/half-life annotation, or `""` if there's nothing to explain."""
    if pd.isna(metrics_row["peak_date"]):
        return "No usable peak was detected for this trend."
    if metrics_row["pre_peak"]:
        return "Still climbing toward its peak, no post-peak decay to annotate yet."
    if metrics_row["time_to_half_status"] == HALF_LIFE_STILL_ABOVE:
        return "Never fell below half its peak (as of the pull date)."
    return ""


def plot_trend_series(series: pd.DataFrame, metrics_row: pd.Series) -> Figure:
    """Raw & smoothed weekly interest for one trend, peak and half-life annotated.

    The peak marker is skipped when no peak was found; the secondary peak
    marker only when `has_secondary_peak`; the 50% threshold line is skipped
    pre-peak; the crossing marker only when `time_to_half_status` is
    `HALF_LIFE_CROSSED`. `_series_caption` names whichever is missing and why.
    """
    apply_theme()
    trend = series.sort_values("date")
    style = category_style(metrics_row["category"])

    fig, ax = plt.subplots()
    line_chart_grid(ax)

    ax.plot(
        trend["date"],
        trend["interest_raw"],
        color=RAW_COLOR,
        alpha=RAW_ALPHA,
        linewidth=RAW_LINEWIDTH,
        label="Raw interest",
        zorder=1,
    )
    ax.plot(
        trend["date"],
        trend["interest_smooth"],
        color=style["color"],
        linestyle=style["linestyle"],
        linewidth=SMOOTH_LINEWIDTH,
        label="Smoothed",
        zorder=2,
    )

    if pd.notna(metrics_row["peak_date"]):
        ax.axvline(metrics_row["peak_date"], color=PEAK_MARKER_COLOR, linestyle="--", linewidth=1.0, zorder=0)
        ax.scatter(
            [metrics_row["peak_date"]],
            [metrics_row["peak_value"]],
            color=PEAK_MARKER_COLOR,
            zorder=3,
            label="Peak",
            marker="o",
        )

    if metrics_row["has_secondary_peak"] and pd.notna(metrics_row["secondary_peak_date"]):
        ax.scatter(
            [metrics_row["secondary_peak_date"]],
            [metrics_row["secondary_peak_value"]],
            color=SECONDARY_PEAK_MARKER_COLOR,
            zorder=3,
            label="Secondary peak (revival)",
            marker="^",
        )

    if pd.notna(metrics_row["peak_value"]) and not metrics_row["pre_peak"]:
        half_life_value = 0.5 * metrics_row["peak_value"]
        ax.axhline(half_life_value, color=THRESHOLD_LINE_COLOR, linestyle=":", linewidth=1.0, zorder=0)

        if metrics_row["time_to_half_status"] == HALF_LIFE_CROSSED and pd.notna(metrics_row["half_life_date"]):
            ax.scatter(
                [metrics_row["half_life_date"]],
                [half_life_value],
                color=HALF_LIFE_MARKER_COLOR,
                zorder=3,
                label="Half-life crossing",
                marker="x",
            )

    ax.set_xlabel("Week")
    ax.set_ylabel("Interest (0-100, own scale)")
    ax.set_title(f"{metrics_row['display_name']}, weekly interest")
    ax.legend(loc="upper right", fontsize=8)

    caption = _series_caption(metrics_row)
    if caption:
        fig.text(0.01, 0.01, caption, ha="left", va="bottom", fontsize=CAPTION_FONTSIZE, color=CAPTION_COLOR, style="italic")

    return fig


# ---- vs. the median ----------------------------------------------------


def build_trend_vs_median_frame(series: pd.DataFrame, metrics: pd.DataFrame, trend_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`(own, median)` peak-aligned curves: `trend_id`'s own, and every other eligible trend's median.

    `own` is empty when `trend_id` isn't eligible (`pre_peak`/`peak_at_boundary`).
    `median` excludes `trend_id` itself.
    """
    frame = build_decay_curve_frame(series, metrics)
    own = frame[frame["trend_id"] == trend_id].sort_values("weeks_since_peak")
    others = frame[frame["trend_id"] != trend_id]
    median = others.groupby("weeks_since_peak", as_index=False)["pct_of_peak"].median()
    return own, median


def plot_trend_vs_median(series: pd.DataFrame, metrics: pd.DataFrame, trend_id: str) -> Figure:
    """This trend's peak-aligned decay curve against the median of every other eligible trend.

    When `trend_id` has no post-peak curve of its own, only the median line
    is drawn, with a caption explaining why.
    """
    apply_theme()
    own, median = build_trend_vs_median_frame(series, metrics, trend_id)
    row = metrics.loc[metrics["trend_id"] == trend_id].iloc[0]

    fig, ax = plt.subplots()
    line_chart_grid(ax)

    ax.plot(
        median["weeks_since_peak"],
        median["pct_of_peak"],
        color=MEDIAN_LINE_COLOR,
        linestyle="--",
        linewidth=1.5,
        label="Median of all other trends",
        zorder=1,
    )

    if not own.empty:
        style = category_style(row["category"])
        ax.plot(
            own["weeks_since_peak"],
            own["pct_of_peak"],
            color=style["color"],
            linestyle=style["linestyle"],
            linewidth=SMOOTH_LINEWIDTH,
            label=row["display_name"],
            zorder=2,
        )
    else:
        fig.text(
            0.01,
            0.01,
            f"{row['display_name']} has no post-peak curve to compare yet "
            "(still rising, or its peak sits at the edge of the pulled window).",
            ha="left",
            va="bottom",
            fontsize=CAPTION_FONTSIZE,
            color=CAPTION_COLOR,
            style="italic",
        )

    ax.axhline(HALF_LIFE_REFERENCE_PCT, color=PEAK_MARKER_COLOR, linestyle=":", linewidth=1.0, zorder=0)
    ax.axvline(0, color="#CCCCCC", linewidth=0.8, zorder=0)

    ax.set_xlabel("Weeks since peak")
    ax.set_ylabel("% of trend's own peak")
    ax.set_title("This trend vs. the median decay curve")
    ax.legend(loc="upper right", fontsize=8)

    return fig
