"""Assign each trend a plain-language lifecycle label.

Descriptive labelling of a trend's observed history, not a classifier or
forecast: every rule reads only already-computed metrics. A trend can match
more than one label at once, so `classify_status` resolves that with a fixed
precedence:

1. `unknown`: no peak could be found at all. Checked first.
2. `pre_peak`: still climbing into its peak; nothing to call decay yet.
3. `revived`: a secondary hump nearly as tall as the peak. Takes precedence
   over `collapsed`/`stabilized` as the more informative story.
4. `collapsed`: dropped at least `collapsed_pct_dropped_threshold` percent.
   Checked before `stabilized` so a faded-then-flat trend reads as collapsed.
5. `stabilized`: post-peak but flat over `stabilized_window_weeks` (within
   `stabilized_flat_tolerance` of its mean) while retaining at least
   `stabilized_min_retained_pct` percent of peak.
6. `declining`: the default for any post-peak trend matching none of the above.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

# Values `status` takes.
STATUS_UNKNOWN = "unknown"
STATUS_PRE_PEAK = "pre_peak"
STATUS_REVIVED = "revived"
STATUS_COLLAPSED = "collapsed"
STATUS_STABILIZED = "stabilized"
STATUS_DECLINING = "declining"


@dataclass(frozen=True)
class StatusResult:
    """One trend's lifecycle label. See the module docstring for the rules."""

    status: str = STATUS_UNKNOWN

    def to_row(self) -> dict[str, Any]:
        """A flat dict of this result, one key per `metrics.parquet` column."""
        return asdict(self)


def _is_flat(smooth: pd.Series, window_weeks: int, flat_tolerance: float) -> bool:
    """True if the trailing `window_weeks` of `smooth` barely moved.

    Requires a full `window_weeks` of actual observations; a window shortened
    by trailing gaps reads as not-flat. Flatness is the window's range as a
    fraction of its own mean, not a fixed absolute range.
    """
    window = smooth.tail(window_weeks).dropna()
    if len(window) < window_weeks:
        return False

    mean = window.mean()
    if not mean:
        return False

    return bool((window.max() - window.min()) / mean <= flat_tolerance)


def classify_status(
    processed: pd.DataFrame,
    pre_peak: bool,
    has_secondary_peak: bool,
    weeks_since_peak: int | None,
    pct_dropped: float | None,
    collapsed_pct_dropped_threshold: float,
    stabilized_window_weeks: int,
    stabilized_flat_tolerance: float,
    stabilized_min_retained_pct: float,
) -> StatusResult:
    """Assign one trend's lifecycle label. See the module docstring for the precedence order."""
    if weeks_since_peak is None:
        return StatusResult(STATUS_UNKNOWN)
    if pre_peak:
        return StatusResult(STATUS_PRE_PEAK)
    if has_secondary_peak:
        return StatusResult(STATUS_REVIVED)
    if pct_dropped is not None and pct_dropped >= collapsed_pct_dropped_threshold:
        return StatusResult(STATUS_COLLAPSED)

    retained_enough = pct_dropped is not None and (100.0 - pct_dropped) >= stabilized_min_retained_pct
    if (
        retained_enough
        and weeks_since_peak >= stabilized_window_weeks
        and _is_flat(processed["interest_smooth"], stabilized_window_weeks, stabilized_flat_tolerance)
    ):
        return StatusResult(STATUS_STABILIZED)

    return StatusResult(STATUS_DECLINING)


STATUS_COLUMNS = ("status",)

# Explicit dtype so this column round-trips through parquet correctly.
STATUS_DTYPES = {"status": "string"}


def compute_status_by_trend(
    series: pd.DataFrame,
    peaks: pd.DataFrame,
    pct_dropped: pd.DataFrame,
    collapsed_pct_dropped_threshold: float,
    stabilized_window_weeks: int,
    stabilized_flat_tolerance: float,
    stabilized_min_retained_pct: float,
) -> pd.DataFrame:
    """Run `classify_status` over every trend, returning one row per `trend_id` carrying `STATUS_COLUMNS`."""
    peaks_by_id = peaks.set_index("trend_id")
    pct_dropped_by_id = pct_dropped.set_index("trend_id")

    rows = []
    for trend_id, group in series.groupby("trend_id", sort=False):
        processed = group.set_index("date")[["interest_smooth"]].sort_index()
        peak_row = peaks_by_id.loc[trend_id]
        drop = pct_dropped_by_id.loc[trend_id, "pct_dropped"]
        result = classify_status(
            processed,
            bool(peak_row["pre_peak"]),
            bool(peak_row["has_secondary_peak"]),
            None if pd.isna(peak_row["weeks_since_peak"]) else int(peak_row["weeks_since_peak"]),
            None if pd.isna(drop) else float(drop),
            collapsed_pct_dropped_threshold,
            stabilized_window_weeks,
            stabilized_flat_tolerance,
            stabilized_min_retained_pct,
        )
        rows.append({"trend_id": trend_id, **result.to_row()})

    frame = pd.DataFrame(rows, columns=["trend_id", *STATUS_COLUMNS])
    return frame.astype(STATUS_DTYPES)
