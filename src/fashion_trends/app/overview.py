"""Data shaping for the Overview page's ranked, filterable metrics table.

Kept separate from `app/pages/overview.py` so this logic is testable without a
running Streamlit script — the same split `fashion_trends.app.data` and
`fashion_trends.app.layout` already follow.

A null metric here is never the same thing as a blank cell: `pre_peak`,
`unknown`, and `still_above_half` are all real findings about a trend, not
missing data, and `format_overview_table` renders each as the plain-language
label a reader needs to tell those cases apart (see
`fashion_trends.metrics.decay` and `fashion_trends.metrics.status` for why
each one nulls what it nulls). That label is text sharing a column with
formatted numbers, which does cost that column a fully numeric sort for the
handful of rows carrying a label instead of a value — accepted deliberately,
since a blank or a zero in a null metric's cell is the more misleading
outcome of the two.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from fashion_trends.metrics.decay import HALF_LIFE_CROSSED, HALF_LIFE_PRE_PEAK, HALF_LIFE_STILL_ABOVE

# Sentinel filter values meaning "don't filter on this dimension" — kept
# distinct from any real category or status string so a widget's default
# selection can never collide with actual data.
ALL_CATEGORIES = "All categories"
ALL_STATUSES = "All statuses"

# Plain-language labels for a null metric — see the module docstring for why
# these stand in for the cell rather than leaving it blank.
STILL_RISING = "still rising"
NEVER_HALVED = "never fell below 50%"
JUST_PEAKED = "just peaked"
NO_PEAK_DETECTED = "no usable peak detected"

OVERVIEW_COLUMNS = (
    "display_name",
    "category",
    "status",
    "peak_date",
    "pct_dropped",
    "decay_rate_linear",
    "weeks_to_half",
    "flags",
)

OVERVIEW_COLUMN_LABELS = {
    "display_name": "Trend",
    "category": "Category",
    "status": "Status",
    "peak_date": "Peak date",
    "pct_dropped": "% dropped",
    "decay_rate_linear": "Decay rate",
    "weeks_to_half": "Weeks to 50%",
    "flags": "Caveats",
}

# Column-header help text: the inline affordance tracing each displayed
# metric back to the function that defines it.
OVERVIEW_COLUMN_HELP = {
    "display_name": "The catalog's display name for this trend (config/trends.yaml).",
    "category": "One of aesthetic, garment, accessory, styling (fashion_trends.keywords.VALID_CATEGORIES).",
    "status": "Lifecycle label assigned by fashion_trends.metrics.status.classify_status.",
    "peak_date": "Week the smoothed series reached its maximum (fashion_trends.metrics.peaks.detect_peak).",
    "pct_dropped": (
        "% dropped from peak to the current smoothing-window average, clamped to 0-100 "
        "(fashion_trends.metrics.decay.compute_pct_dropped)."
    ),
    "decay_rate_linear": (
        "Percentage points of the peak lost per week since peak "
        "(fashion_trends.metrics.decay.compute_decay_rate)."
    ),
    "weeks_to_half": (
        "Weeks from peak until the series held below half its peak for a sustained run "
        "(fashion_trends.metrics.decay.compute_time_to_half)."
    ),
    "flags": (
        "Caveats affecting how far this trend's metrics can be trusted: low-resolution data "
        "(fashion_trends.settings.Settings.low_resolution_threshold), a peak sitting at the edge of "
        "the pulled window, or a secondary peak splitting the decay story "
        "(fashion_trends.metrics.peaks)."
    ),
}


def filter_metrics(metrics: pd.DataFrame, category: str, status: str) -> pd.DataFrame:
    """`metrics` restricted to `category` and `status`, either of which may be "show all".

    `category` and `status` are compared against `ALL_CATEGORIES`/`ALL_STATUSES`
    respectively — passing either sentinel skips filtering on that dimension.
    """
    filtered = metrics
    if category != ALL_CATEGORIES:
        filtered = filtered[filtered["category"] == category]
    if status != ALL_STATUSES:
        filtered = filtered[filtered["status"] == status]
    return filtered


def summary_tiles(metrics: pd.DataFrame) -> dict[str, Any]:
    """Median % dropped, median weeks-to-half, and a count of trends by status.

    Both medians are taken over the trends that actually have the metric —
    `pct_dropped` excludes pre-peak/no-peak trends by being null for them
    already, and `weeks_to_half` is further restricted to `HALF_LIFE_CROSSED`
    rows so a `still_above_half` trend's lack of a crossing doesn't get
    averaged in as if it were a fast one. Either median is `None` when no row
    qualifies, distinguishing "nothing to average" from "averages to zero".
    """
    pct_dropped = metrics["pct_dropped"].dropna()
    crossed_weeks = metrics.loc[metrics["time_to_half_status"] == HALF_LIFE_CROSSED, "weeks_to_half"].dropna()

    return {
        "median_pct_dropped": float(pct_dropped.median()) if not pct_dropped.empty else None,
        "median_weeks_to_half": float(crossed_weeks.median()) if not crossed_weeks.empty else None,
        "status_counts": metrics["status"].value_counts().to_dict(),
    }


def _format_peak_date(row: pd.Series) -> str:
    # Unlike the decay metrics below, `peak_date` is set even for a `pre_peak`
    # trend — the peak is real, only the decay measured *from* it doesn't
    # exist yet (see `fashion_trends.metrics.peaks`) — so a null here only
    # ever means no peak was found at all.
    if pd.notna(row["peak_date"]):
        return row["peak_date"].date().isoformat()
    return NO_PEAK_DETECTED


def _format_pct_dropped(row: pd.Series) -> str:
    if pd.notna(row["pct_dropped"]):
        return f"{row['pct_dropped']:.0f}%"
    return STILL_RISING if row["pre_peak"] else NO_PEAK_DETECTED


def _format_decay_rate(row: pd.Series) -> str:
    if pd.notna(row["decay_rate_linear"]):
        return f"{row['decay_rate_linear']:.2f} pts/wk"
    if row["pre_peak"]:
        return STILL_RISING
    if pd.notna(row["weeks_since_peak"]) and row["weeks_since_peak"] == 0:
        return JUST_PEAKED
    return NO_PEAK_DETECTED


def _format_weeks_to_half(row: pd.Series) -> str:
    status = row["time_to_half_status"]
    if status == HALF_LIFE_CROSSED:
        return f"{int(row['weeks_to_half'])} wk"
    if status == HALF_LIFE_PRE_PEAK:
        return STILL_RISING
    if status == HALF_LIFE_STILL_ABOVE:
        return NEVER_HALVED
    return NO_PEAK_DETECTED


def _format_flags(row: pd.Series) -> str:
    labels = []
    if row["low_resolution"]:
        labels.append("low-resolution data")
    if row["peak_at_boundary"]:
        labels.append("peak near window edge")
    if row["has_secondary_peak"]:
        labels.append("secondary peak (revival)")
    return ", ".join(labels)


def format_overview_table(metrics: pd.DataFrame) -> pd.DataFrame:
    """`metrics` reshaped into the Overview table's display columns.

    Every metric cell is a display-ready string: a formatted value where one
    exists, otherwise the plain-language reason it doesn't (see the module
    docstring). Returns `OVERVIEW_COLUMNS` in that order; empty input returns
    an empty frame with the same columns rather than raising, so a caller
    filtering down to nothing can render it directly.
    """
    if metrics.empty:
        return pd.DataFrame(columns=OVERVIEW_COLUMNS)

    table = pd.DataFrame(
        {
            "display_name": metrics["display_name"],
            "category": metrics["category"],
            "status": metrics["status"],
            "peak_date": metrics.apply(_format_peak_date, axis=1),
            "pct_dropped": metrics.apply(_format_pct_dropped, axis=1),
            "decay_rate_linear": metrics.apply(_format_decay_rate, axis=1),
            "weeks_to_half": metrics.apply(_format_weeks_to_half, axis=1),
            "flags": metrics.apply(_format_flags, axis=1),
        },
        index=metrics.index,
    )
    return table[list(OVERVIEW_COLUMNS)]
