"""Data shaping for the Trend detail page's metric cards and catalog metadata.

Kept separate from `app/views/trend_detail.py` so this logic is testable
without a running Streamlit script. `metric_cards` reuses
`fashion_trends.app.overview`'s per-metric formatting directly, so both pages
show identical wording for the same finding.
"""

from __future__ import annotations

import pandas as pd

from fashion_trends.app.overview import (
    NO_PEAK_DETECTED,
    format_decay_rate,
    format_flags,
    format_pct_dropped,
    format_peak_date,
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

# Plain-language expansion of each `fashion_trends.metrics.status` label.
STATUS_LABELS = {
    STATUS_UNKNOWN: "Unknown: no usable peak detected",
    STATUS_PRE_PEAK: "Pre-peak: still climbing toward its peak",
    STATUS_REVIVED: "Revived: a second peak nearly as tall as the first",
    STATUS_COLLAPSED: "Collapsed",
    STATUS_STABILIZED: "Stabilized: holding flat post-peak",
    STATUS_DECLINING: "Declining",
}


def status_explanation(status: str) -> str:
    """The plain-language half of a lifecycle label (the part of `STATUS_LABELS` after the colon), or `""`."""
    label = STATUS_LABELS.get(status, status)
    _, separator, explanation = label.partition(":")
    return explanation.strip() if separator else ""


def _format_peak_value(row: pd.Series) -> str:
    if pd.notna(row["peak_value"]):
        return f"{row['peak_value']:.0f}"
    return NO_PEAK_DETECTED


def metric_cards(row: pd.Series) -> dict[str, str]:
    """Peak value/date, % dropped, decay rate, weeks-to-50%, status, and flags for one metrics row, display-ready."""
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
    """Curation notes for `trend_id` from `config/trends.yaml`, or `NO_NOTES` if there are none or it's gone."""
    for trend in load_trends():
        if trend.id == trend_id:
            return trend.notes
    return NO_NOTES
