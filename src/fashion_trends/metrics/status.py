"""Assign each trend a plain-language lifecycle label.

This is descriptive labelling of a trend's *observed* history, not a
fad-vs-lasting classifier or a forecast — every rule below reads only
already-computed metrics (peak flags, `pct_dropped`, the smoothed series
itself) and there is no fitting, training, or prediction involved. A trend
can plausibly match more than one label at once (a collapsed trend can also
be flat, a revived trend can also be down 70% from its all-time peak), so
`classify_status` resolves that with a fixed, documented precedence rather
than picking whichever rule happens to run last:

1. **`unknown`** — no peak could be found at all (an empty or all-gap
   series). This is not one of the five lifecycle labels the rest of this
   module exists to assign; it is the same "no data, not a computed result"
   escape hatch every other metric in this package uses (compare
   `fashion_trends.metrics.decay.HALF_LIFE_UNKNOWN`), checked first so a
   trend with nothing to measure never falls through to a label that implies
   something was.
2. **`pre_peak`** — the peak is the most recent week and the series is still
   climbing into it. Checked first among the real labels because every other
   one presumes a peak to measure decay *from*; there is nothing yet to call
   a decline, a collapse, or a plateau.
3. **`revived`** — peak detection flagged a secondary hump nearly as tall as
   the main peak. This takes precedence over `collapsed`/`stabilized` because
   it is the more informative story: a trend that came back is worth calling
   out even when its current level also happens to be deeply down from its
   peak or sitting flat.
4. **`collapsed`** — dropped at least `collapsed_pct_dropped_threshold`
   percent from peak. Checked before `stabilized` so a trend that faded
   almost to nothing and then went flat at that residual floor is reported
   as collapsed, not as a plateau worth calling a wardrobe staple.
5. **`stabilized`** — post-peak, but flat over the trailing
   `stabilized_window_weeks` weeks (the window's range stays within
   `stabilized_flat_tolerance` of its mean) while having retained at least
   `stabilized_min_retained_pct` percent of its peak. This is the label the
   ticket cares most about getting right: it is the only thing in this
   engine that distinguishes a trend that became a wardrobe staple from one
   that quietly vanished, and both require deliberately looking past the
   noisy last few weeks to a full plateau. Requiring a minimum weeks-since-peak
   equal to the window keeps a trend that only just peaked from reading its
   own peak plateau as stability.
6. **`declining`** — clearly post-peak and still falling. This is the
   default for every post-peak trend that matched none of the above, not a
   rule with its own predicate — a trend that is post-peak, not revived, not
   yet down 70%, and not flat is, definitionally, still on its way down.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

# Values `status` takes, named so callers (charts, dashboard filters) match on
# a name rather than a bare string literal.
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

    Requires a full `window_weeks` of *actual* observations — a window
    shortened by trailing gaps is missing data, not evidence of a plateau, so
    it reads as not-flat rather than guessing from whatever remains. Flatness
    itself is the window's range as a fraction of its own mean: a fixed
    absolute range would call a small residual trend "volatile" for movements
    that are proportionally tiny.
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
    """Assign one trend's lifecycle label. See the module docstring for the order.

    `processed` is a frame indexed by date with an `interest_smooth` column —
    the shape `fashion_trends.metrics.smoothing.preprocess_series` returns.
    `pre_peak`, `has_secondary_peak`, and `weeks_since_peak` come from that
    trend's `fashion_trends.metrics.peaks.PeakResult`, and `pct_dropped` from
    its `fashion_trends.metrics.decay.PctDroppedResult`.
    """
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

# Explicit dtype so this column round-trips through parquet as the type the
# rest of the pipeline expects, matching `time_to_half_status`'s treatment in
# `fashion_trends.metrics.decay`.
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
    """Run `classify_status` over every trend in a long-format series frame.

    `series` has `series.parquet`'s shape — one row per (trend, week), with
    `date`, `trend_id`, and `interest_smooth` columns. `peaks` is the frame
    returned by `fashion_trends.metrics.peaks.detect_peaks_by_trend` and
    `pct_dropped` the one returned by
    `fashion_trends.metrics.decay.compute_pct_dropped_by_trend`, both keyed by
    `trend_id`. Returns one row per `trend_id` carrying `STATUS_COLUMNS`,
    ready to merge onto the metrics table.
    """
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
