"""Compute how far a trend has fallen from its own peak.

This is the project's headline number, so it has to survive the two ways a
peak-relative percentage lies:

* **A noisy trailing week.** Reading "current" off the single most recent
  week can swing the figure by double digits on its own. `current_value` is
  instead the mean of the last `smoothing_window` *complete* weeks of raw
  interest — wide enough to absorb one noisy week, but still recent enough
  to describe where the trend stands now rather than where it was months
  ago.
* **A misdetected peak.** If the current level reads *above* the peak, the
  peak was found in the wrong place (see `fashion_trends.metrics.peaks`),
  not evidence the trend rose again. Reporting that as a negative drop would
  put a nonsense number in front of a reader with no reason to distrust it,
  so it is clamped to 0 and carried instead as `current_above_peak`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class PctDroppedResult:
    """% dropped since peak for one trend, plus the numbers behind it.

    Every field is `None` when there is nothing to report yet — the trend is
    still pre-peak, or there is no peak or no raw observation to measure
    against — so a caller never has to tell "not decaying" apart from
    "decaying by 0%".
    """

    pct_dropped: float | None = None
    current_value: float | None = None
    current_window_end: pd.Timestamp | None = None
    # True when the raw (unclamped) drop was negative — the current level
    # reads above the peak, which means the peak itself was misdetected.
    current_above_peak: bool = False

    def to_row(self) -> dict[str, Any]:
        """A flat dict of this result, one key per `metrics.parquet` column."""
        return asdict(self)


def compute_pct_dropped(
    processed: pd.DataFrame,
    peak_value: float | None,
    pre_peak: bool,
    smoothing_window: int,
) -> PctDroppedResult:
    """% dropped from `peak_value` to a trend's current level.

    `processed` is a frame indexed by date with an `interest_raw` column —
    the shape `fashion_trends.metrics.smoothing.preprocess_series` returns.
    `peak_value` and `pre_peak` come from that trend's
    `fashion_trends.metrics.peaks.PeakResult`.

    `current_value` is the mean of the last `smoothing_window` complete
    weeks of `interest_raw`, skipping gap weeks rather than counting them as
    zero; if fewer than `smoothing_window` weeks are available, whatever
    there is gets averaged. `pct_dropped` is that drop from `peak_value` as
    a percentage, clamped to `[0, 100]` — see the module docstring for why a
    below-zero reading is clamped rather than reported.

    Returns an all-`None` result when `pre_peak` (no decay to measure yet),
    when `peak_value` is `None` (no peak was found), or when `processed` has
    no raw observations to average.
    """
    if pre_peak or peak_value is None:
        return PctDroppedResult()

    raw = processed["interest_raw"].dropna()
    if raw.empty:
        return PctDroppedResult()

    window = raw.tail(smoothing_window)
    current_value = float(window.mean())
    current_window_end = window.index[-1]

    if peak_value == 0:
        # No measurable interest was ever recorded — there is no drop to
        # express as a percentage of it.
        return PctDroppedResult(current_value=current_value, current_window_end=current_window_end)

    raw_pct_dropped = (peak_value - current_value) / peak_value * 100
    current_above_peak = raw_pct_dropped < 0
    pct_dropped = min(100.0, max(0.0, raw_pct_dropped))

    return PctDroppedResult(
        pct_dropped=pct_dropped,
        current_value=current_value,
        current_window_end=current_window_end,
        current_above_peak=current_above_peak,
    )


PCT_DROPPED_COLUMNS = (
    "pct_dropped",
    "current_value",
    "current_window_end",
    "current_above_peak",
)

# Explicit dtypes so a column that happens to be all-null in one run still
# round-trips through parquet as the type the rest of the pipeline expects.
_PCT_DROPPED_DTYPES = {
    "pct_dropped": "float64",
    "current_value": "float64",
    "current_window_end": "datetime64[ns]",
    "current_above_peak": "bool",
}


def compute_pct_dropped_by_trend(
    series: pd.DataFrame,
    peaks: pd.DataFrame,
    smoothing_window: int,
) -> pd.DataFrame:
    """Run `compute_pct_dropped` over every trend in a long-format series frame.

    `series` has `series.parquet`'s shape — one row per (trend, week), with
    `date`, `trend_id`, and `interest_raw` columns. `peaks` is the frame
    returned by `fashion_trends.metrics.peaks.detect_peaks_by_trend` (one row
    per `trend_id`, carrying `peak_value` and `pre_peak` among
    `PEAK_COLUMNS`). Returns one row per `trend_id` carrying
    `PCT_DROPPED_COLUMNS`, ready to merge onto the metrics table.
    """
    peaks_by_id = peaks.set_index("trend_id")

    rows = []
    for trend_id, group in series.groupby("trend_id", sort=False):
        processed = group.set_index("date")[["interest_raw"]].sort_index()
        peak_row = peaks_by_id.loc[trend_id]
        peak_value = None if pd.isna(peak_row["peak_value"]) else float(peak_row["peak_value"])
        result = compute_pct_dropped(processed, peak_value, bool(peak_row["pre_peak"]), smoothing_window)
        rows.append({"trend_id": trend_id, **result.to_row()})

    frame = pd.DataFrame(rows, columns=["trend_id", *PCT_DROPPED_COLUMNS])
    return frame.astype(_PCT_DROPPED_DTYPES)
