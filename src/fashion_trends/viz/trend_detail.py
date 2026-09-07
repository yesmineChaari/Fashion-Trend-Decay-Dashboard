"""Per-trend detail charts: the full weekly series, and this trend against the pack.

`plot_trend_series` draws one trend's raw and smoothed weekly interest with
its peak, 50%-of-peak threshold, and (if any) crossing week marked.
`plot_trend_vs_median` reuses `fashion_trends.viz.decay_curves`'s
peak-alignment to compare this trend's decay against the median of every
other eligible trend.

Both are interactive Plotly figures (pan/zoom/hover), unlike the static
matplotlib charts in `decay_curves.py`/`rankings.py` -- these are the ones
users explore a single trend's timeline in, so panning into a stretch of
weeks is worth the interactivity; the catalog-wide summary charts stay
static. Both charts skip an annotation rather than guess when the metric
behind it is null (pre-peak, no usable peak, never crossed half its peak).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from fashion_trends.metrics.decay import HALF_LIFE_CROSSED, HALF_LIFE_STILL_ABOVE
from fashion_trends.viz.decay_curves import HALF_LIFE_REFERENCE_PCT, build_decay_curve_frame
from fashion_trends.viz.theme import DASH_BY_LINESTYLE, category_style, plotly_caption_annotation, plotly_layout_defaults

RAW_COLOR = "#B0B0B0"
RAW_OPACITY = 0.6
RAW_LINEWIDTH = 1.0
SMOOTH_LINEWIDTH = 2.5

PEAK_MARKER_COLOR = "#333333"
SECONDARY_PEAK_MARKER_COLOR = "#E69F00"
HALF_LIFE_MARKER_COLOR = "#D55E00"
THRESHOLD_LINE_COLOR = "#999999"

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


def plot_trend_series(series: pd.DataFrame, metrics_row: pd.Series) -> go.Figure:
    """Raw & smoothed weekly interest for one trend, peak and half-life annotated.

    The peak marker is skipped when no peak was found; the secondary peak
    marker only when `has_secondary_peak`; the 50% threshold line is skipped
    pre-peak; the crossing marker only when `time_to_half_status` is
    `HALF_LIFE_CROSSED`. `_series_caption` names whichever is missing and why.
    """
    trend = series.sort_values("date")
    style = category_style(metrics_row["category"])
    dash = DASH_BY_LINESTYLE.get(style["linestyle"], "solid")

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=trend["date"],
            y=trend["interest_raw"],
            mode="lines",
            line={"color": RAW_COLOR, "width": RAW_LINEWIDTH},
            opacity=RAW_OPACITY,
            name="Raw interest",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=trend["date"],
            y=trend["interest_smooth"],
            mode="lines",
            line={"color": style["color"], "width": SMOOTH_LINEWIDTH, "dash": dash},
            name="Smoothed",
        )
    )

    if pd.notna(metrics_row["peak_date"]):
        fig.add_vline(x=metrics_row["peak_date"], line={"color": PEAK_MARKER_COLOR, "width": 1, "dash": "dash"})
        fig.add_trace(
            go.Scatter(
                x=[metrics_row["peak_date"]],
                y=[metrics_row["peak_value"]],
                mode="markers",
                marker={"color": PEAK_MARKER_COLOR, "symbol": "circle", "size": 9},
                name="Peak",
            )
        )

    if metrics_row["has_secondary_peak"] and pd.notna(metrics_row["secondary_peak_date"]):
        fig.add_trace(
            go.Scatter(
                x=[metrics_row["secondary_peak_date"]],
                y=[metrics_row["secondary_peak_value"]],
                mode="markers",
                marker={"color": SECONDARY_PEAK_MARKER_COLOR, "symbol": "triangle-up", "size": 11},
                name="Secondary peak (revival)",
            )
        )

    if pd.notna(metrics_row["peak_value"]) and not metrics_row["pre_peak"]:
        half_life_value = 0.5 * metrics_row["peak_value"]
        fig.add_hline(y=half_life_value, line={"color": THRESHOLD_LINE_COLOR, "width": 1, "dash": "dot"})

        if metrics_row["time_to_half_status"] == HALF_LIFE_CROSSED and pd.notna(metrics_row["half_life_date"]):
            fig.add_trace(
                go.Scatter(
                    x=[metrics_row["half_life_date"]],
                    y=[half_life_value],
                    mode="markers",
                    marker={"color": HALF_LIFE_MARKER_COLOR, "symbol": "x", "size": 10},
                    name="Half-life crossing",
                )
            )

    fig.update_layout(**plotly_layout_defaults())
    fig.update_layout(
        xaxis_title="Week",
        yaxis_title="Interest (0-100, own scale)",
        title={"text": f"{metrics_row['display_name']}, weekly interest", "x": 0, "xanchor": "left"},
        legend={"orientation": "v", "x": 1, "xanchor": "right", "y": 1, "yanchor": "top"},
    )

    caption = _series_caption(metrics_row)
    if caption:
        fig.add_annotation(plotly_caption_annotation(caption))

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


def plot_trend_vs_median(series: pd.DataFrame, metrics: pd.DataFrame, trend_id: str) -> go.Figure:
    """This trend's peak-aligned decay curve against the median of every other eligible trend.

    When `trend_id` has no post-peak curve of its own, only the median line
    is drawn, with a caption explaining why.
    """
    own, median = build_trend_vs_median_frame(series, metrics, trend_id)
    row = metrics.loc[metrics["trend_id"] == trend_id].iloc[0]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=median["weeks_since_peak"],
            y=median["pct_of_peak"],
            mode="lines",
            line={"color": MEDIAN_LINE_COLOR, "width": 1.5, "dash": "dash"},
            name="Median of all other trends",
        )
    )

    if not own.empty:
        style = category_style(row["category"])
        dash = DASH_BY_LINESTYLE.get(style["linestyle"], "solid")
        fig.add_trace(
            go.Scatter(
                x=own["weeks_since_peak"],
                y=own["pct_of_peak"],
                mode="lines",
                line={"color": style["color"], "width": SMOOTH_LINEWIDTH, "dash": dash},
                name=row["display_name"],
            )
        )
    else:
        fig.add_annotation(
            plotly_caption_annotation(
                f"{row['display_name']} has no post-peak curve to compare yet "
                "(still rising, or its peak sits at the edge of the pulled window)."
            )
        )

    fig.add_hline(y=HALF_LIFE_REFERENCE_PCT, line={"color": PEAK_MARKER_COLOR, "width": 1, "dash": "dot"})
    fig.add_vline(x=0, line={"color": "#CCCCCC", "width": 0.8})

    fig.update_layout(**plotly_layout_defaults())
    fig.update_layout(
        xaxis_title="Weeks since peak",
        yaxis_title="% of trend's own peak",
        title={"text": "This trend vs. the median decay curve", "x": 0, "xanchor": "left"},
        legend={"orientation": "v", "x": 1, "xanchor": "right", "y": 1, "yanchor": "top"},
    )

    return fig
