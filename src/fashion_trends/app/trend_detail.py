"""Data shaping for the Trend detail page's metric cards and catalog metadata.

Kept separate from `app/views/trend_detail.py` so this logic is testable
without a running Streamlit script -- the same split `fashion_trends.app.overview`
already follows for the Overview page. `metric_cards` reuses that module's
per-metric formatting directly, so a reader sees the identical wording for
"still rising" or "never fell below 50%" on either page rather than two
subtly different phrasings of the same finding.
"""

from __future__ import annotations

import pandas as pd

from fashion_trends.app.overview import (
    NO_PEAK_DETECTED,
    format_decay_rate,
    format_flags,
    format_peak_date,
    format_pct_dropped,
    format_weeks_to_half,
)
from fashion_trends.keywords import load_trends
from fashion_trends.metrics.status import (
    STATUS_COLLAPSED,
    STATUS_DECLINING,
    STATUS_PRE_PEAK,
    STATUS_REVIVED,
    STATUS_STABILIZED,
    STATUS_UNKNOWN,
)

NO_NOTES = "No curation notes recorded."

# Plain-language expansion of each `fashion_trends.metrics.status` label --
# the short label alone doesn't say *why* a trend is revived or stabilized,
# and this is the one place in the dashboard with room to say so.
STATUS_LABELS = {
    STATUS_UNKNOWN: "Unknown — no usable peak detected",
    STATUS_PRE_PEAK: "Pre-peak — still climbing toward its peak",
    STATUS_REVIVED: "Revived — a second peak nearly as tall as the first",
    STATUS_COLLAPSED: "Collapsed",
    STATUS_STABILIZED: "Stabilized — holding flat post-peak",
    STATUS_DECLINING: "Declining",
}


def _format_peak_value(row: pd.Series) -> str:
    if pd.notna(row["peak_value"]):
        return f"{row['peak_value']:.0f}"
    return NO_PEAK_DETECTED


def metric_cards(row: pd.Series) -> dict[str, str]:
    """Peak value/date, % dropped, decay rate, weeks-to-50%, status, and flags for one metrics row.

    `row` is one row of `metrics.parquet`. Every value is display-ready: a
    formatted number where one exists, otherwise the plain-language reason
    it doesn't -- see `fashion_trends.app.overview`'s module docstring for
    why a null metric is a finding rather than a blank.
    """
    return {
        "peak_value": _format_peak_value(row),
        "peak_date": format_peak_date(row),
        "pct_dropped": format_pct_dropped(row),
        "decay_rate": format_decay_rate(row),
        "weeks_to_half": format_weeks_to_half(row),
        "status": STATUS_LABELS.get(row["status"], row["status"]),
        "flags": format_flags(row),
    }


def catalog_notes(trend_id: str) -> str:
    """Curation notes for `trend_id` from `config/trends.yaml`, or a placeholder if there are none.

    `metrics.parquet` doesn't carry the catalog's free-text `notes` field --
    see `fashion_trends.metrics.schema.IDENTITY_COLUMNS` -- since it
    describes the trend's curation, not anything measured about it, so it's
    read straight from the catalog here instead. Returns the placeholder
    rather than raising for a `trend_id` no longer in the catalog, since a
    metrics row computed from an older run can outlive a catalog edit.
    """
    for trend in load_trends():
        if trend.id == trend_id:
            return trend.notes
    return NO_NOTES
