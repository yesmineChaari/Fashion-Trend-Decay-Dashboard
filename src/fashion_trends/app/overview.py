"""Data shaping for the Overview page's ranked, filterable metrics table.

Kept separate from `app/views/overview.py` so this logic is testable without a
running Streamlit script.

A null metric is never the same as a blank cell: `pre_peak`, `unknown`, and
`still_above_half` are real findings, not missing data, so
`format_overview_table` renders each as a plain-language label instead of
leaving the cell blank.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from fashion_trends.metrics.decay import HALF_LIFE_CROSSED, HALF_LIFE_PRE_PEAK, HALF_LIFE_STILL_ABOVE
from fashion_trends.metrics.status import STATUS_REVIVED

# Sentinel filter values meaning "don't filter on this dimension".
ALL_CATEGORIES = "All categories"
ALL_STATUSES = "All statuses"

# Plain-language labels for a null metric, see the module docstring.
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

# Column-header help text, written for a reader: no module paths or function names.
OVERVIEW_COLUMN_HELP = {
    "display_name": "The name this trend is listed under.",
    "category": "What kind of trend it is: an aesthetic, a garment, an accessory, or a way of styling.",
    "status": "Where the trend sits in its life: still rising, declining, collapsed, stabilized, or revived.",
    "peak_date": "The week this trend's search interest was at its highest.",
    "pct_dropped": "How far it has fallen from that peak to where it sits now.",
    "decay_rate_linear": "Percentage points of its peak lost per week since it peaked.",
    "weeks_to_half": "Weeks from the peak until interest stayed below half of it.",
    "flags": "Reasons to read this row with more caution: thin data, a peak at the edge of the window, "
    "or a second peak the Status column doesn't already name.",
}


def filter_metrics(metrics: pd.DataFrame, category: str, status: str) -> pd.DataFrame:
    """`metrics` restricted to `category` and `status`, either of which may be "show all"."""
    filtered = metrics
    if category != ALL_CATEGORIES:
        filtered = filtered[filtered["category"] == category]
    if status != ALL_STATUSES:
        filtered = filtered[filtered["status"] == status]
    return filtered


def summary_tiles(metrics: pd.DataFrame) -> dict[str, Any]:
    """Headline numbers for the top of the Overview page.

    Medians are taken only over trends that have the metric; `None` when no
    row qualifies. `fastest_collapse` is the `(display_name, weeks)` of the
    quickest trend to lose half its peak, or `None` if none crossed.
    """
    pct_dropped = metrics["pct_dropped"].dropna()
    crossed = metrics.loc[metrics["time_to_half_status"] == HALF_LIFE_CROSSED].dropna(subset=["weeks_to_half"])
    fastest = crossed.nsmallest(1, "weeks_to_half")

    return {
        "median_pct_dropped": float(pct_dropped.median()) if not pct_dropped.empty else None,
        "median_weeks_to_half": float(crossed["weeks_to_half"].median()) if not crossed.empty else None,
        "fastest_collapse": None
        if fastest.empty
        else (str(fastest["display_name"].iloc[0]), int(fastest["weeks_to_half"].iloc[0])),
        "status_counts": metrics["status"].value_counts().to_dict(),
    }


def format_peak_date(row: pd.Series) -> str:
    """One metrics row's `peak_date`, display-ready. Public: reused by `fashion_trends.app.trend_detail`.

    Set even for a `pre_peak` trend; null here means no peak was found at all.
    """
    if pd.notna(row["peak_date"]):
        return row["peak_date"].date().isoformat()
    return NO_PEAK_DETECTED


def format_pct_dropped(row: pd.Series) -> str:
    """One metrics row's `pct_dropped`, display-ready. Public: reused by `fashion_trends.app.trend_detail`."""
    if pd.notna(row["pct_dropped"]):
        return f"{row['pct_dropped']:.0f}%"
    return STILL_RISING if row["pre_peak"] else NO_PEAK_DETECTED


def format_decay_rate(row: pd.Series) -> str:
    """One metrics row's `decay_rate_linear`, display-ready. Public: reused by `fashion_trends.app.trend_detail`."""
    if pd.notna(row["decay_rate_linear"]):
        return f"{row['decay_rate_linear']:.2f} pts/wk"
    if row["pre_peak"]:
        return STILL_RISING
    if pd.notna(row["weeks_since_peak"]) and row["weeks_since_peak"] == 0:
        return JUST_PEAKED
    return NO_PEAK_DETECTED


def format_weeks_to_half(row: pd.Series) -> str:
    """One metrics row's `weeks_to_half`, display-ready. Public: reused by `fashion_trends.app.trend_detail`."""
    status = row["time_to_half_status"]
    if status == HALF_LIFE_CROSSED:
        return f"{int(row['weeks_to_half'])} wk"
    if status == HALF_LIFE_PRE_PEAK:
        return STILL_RISING
    if status == HALF_LIFE_STILL_ABOVE:
        return NEVER_HALVED
    return NO_PEAK_DETECTED


def format_flags(row: pd.Series) -> str:
    """One metrics row's caveat flags, display-ready. Public: reused by `fashion_trends.app.trend_detail`.

    A second peak is omitted for a `revived` row, since the Status column
    already says why it's revived.
    """
    labels = []
    if row["low_resolution"]:
        labels.append("low-resolution data")
    if row["peak_at_boundary"]:
        labels.append("peak near window edge")
    if row["has_secondary_peak"] and row["status"] != STATUS_REVIVED:
        labels.append("secondary peak (revival)")
    return ", ".join(labels)


def format_overview_table(metrics: pd.DataFrame) -> pd.DataFrame:
    """`metrics` reshaped into the Overview table's display columns, in `OVERVIEW_COLUMNS` order.

    Empty input returns an empty frame with the same columns rather than raising.
    """
    if metrics.empty:
        return pd.DataFrame(columns=OVERVIEW_COLUMNS)

    table = pd.DataFrame(
        {
            "display_name": metrics["display_name"],
            "category": metrics["category"],
            "status": metrics["status"],
            "peak_date": metrics.apply(format_peak_date, axis=1),
            "pct_dropped": metrics.apply(format_pct_dropped, axis=1),
            "decay_rate_linear": metrics.apply(format_decay_rate, axis=1),
            "weeks_to_half": metrics.apply(format_weeks_to_half, axis=1),
            "flags": metrics.apply(format_flags, axis=1),
        },
        index=metrics.index,
    )
    return table[list(OVERVIEW_COLUMNS)]
