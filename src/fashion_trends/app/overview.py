"""Data shaping for the Overview page's ranked, filterable metrics table.

Kept separate from `app/views/overview.py` so this logic is testable without a
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
from fashion_trends.metrics.status import STATUS_REVIVED

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

# Column-header help text: the inline affordance saying what each displayed
# metric actually measures. Written for a reader, not a maintainer -- no
# module paths, no function names, no parenthetical asides. Whoever wants the
# formal definition of a column goes to `docs/methodology.md`, which names the
# function behind every one of them.
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
    """Headline numbers for the top of the Overview page.

    Both medians are taken over the trends that actually have the metric —
    `pct_dropped` excludes pre-peak/no-peak trends by being null for them
    already, and `weeks_to_half` is further restricted to `HALF_LIFE_CROSSED`
    rows so a `still_above_half` trend's lack of a crossing doesn't get
    averaged in as if it were a fast one. Either median is `None` when no row
    qualifies, distinguishing "nothing to average" from "averages to zero".

    `fastest_collapse` is the `(display_name, weeks)` of the quickest trend to
    lose half its peak, or `None` when no trend in `metrics` crossed at all.
    A median alone says how the set behaves without ever naming a trend, and
    the single fastest death is the finding a reader actually repeats — the
    same reason `fashion_trends.viz.decay_curves` draws the extremes bold
    rather than only the middle of the distribution.
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

    Unlike the decay metrics below, `peak_date` is set even for a `pre_peak`
    trend — the peak is real, only the decay measured *from* it doesn't
    exist yet (see `fashion_trends.metrics.peaks`) — so a null here only
    ever means no peak was found at all.
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

    A second peak is left out of the list for a `revived` row, which is every
    row carrying one but a single shape: `fashion_trends.metrics.status`
    assigns that label *because* a second peak was found, so listing it here
    prints the Status column's own reason back at the reader as if it were an
    extra caveat -- the repetition `status_explanation` avoids on the other
    side of the same pairing. The one shape it still says something for is a
    trend climbing past an earlier hump, labelled `pre_peak`, where nothing
    else on the row mentions the hump at all.
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
            "peak_date": metrics.apply(format_peak_date, axis=1),
            "pct_dropped": metrics.apply(format_pct_dropped, axis=1),
            "decay_rate_linear": metrics.apply(format_decay_rate, axis=1),
            "weeks_to_half": metrics.apply(format_weeks_to_half, axis=1),
            "flags": metrics.apply(format_flags, axis=1),
        },
        index=metrics.index,
    )
    return table[list(OVERVIEW_COLUMNS)]
