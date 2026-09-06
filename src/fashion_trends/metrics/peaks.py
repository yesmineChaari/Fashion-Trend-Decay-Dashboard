"""Locate a trend's peak and flag the cases where a single peak is a lie.

Every decay metric downstream is measured relative to the peak, so a peak
found in the wrong week produces a confidently wrong number for the whole
trend. Four flags qualify a real-but-misleading peak:

* `peak_is_spike`: the peak's height rests on a single outlier week rather
  than a real hump (`peak_value_raw` keeps the unsmoothed value for contrast).
* `has_secondary_peak`: a revival, a second hump nearly as tall as the peak.
* `peak_at_boundary`: the real peak may sit outside the pulled window.
* `pre_peak`: still climbing into what would be its peak; no decay yet.

None of these flags reject a trend. They travel with it as columns in
`metrics.parquet` so a fragment is presented as a fragment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class PeakResult:
    """One trend's peak, plus the flags qualifying how much it can be trusted.

    Every value field is `None` for a series with no usable observations.
    """

    peak_date: pd.Timestamp | None = None
    peak_value: float | None = None
    peak_value_raw: float | None = None
    weeks_since_peak: int | None = None
    peak_is_spike: bool = False
    has_secondary_peak: bool = False
    secondary_peak_date: pd.Timestamp | None = None
    secondary_peak_value: float | None = None
    peak_at_boundary: bool = False
    pre_peak: bool = False

    def to_row(self) -> dict[str, Any]:
        """A flat dict of this result, one key per `metrics.parquet` column."""
        return asdict(self)


def _threshold_runs(above: pd.Series) -> list[tuple[int, int]]:
    """Positional `(start, end)` spans of each contiguous `True` run in `above`. `end` is exclusive."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for position, flag in enumerate(above.to_numpy()):
        if flag and start is None:
            start = position
        elif not flag and start is not None:
            runs.append((start, position))
            start = None
    if start is not None:
        runs.append((start, len(above)))
    return runs


def _is_spike_driven(
    raw: pd.Series,
    peak_position: int,
    smoothing_window: int,
    peak_value: float,
    spike_peak_ratio: float,
) -> bool:
    """True if the peak's height rests on a single week rather than a hump.

    Tested via the median (not mean) of the raw weeks around the peak: a real
    hump's median sits near the peak, a lone spike's stays down at baseline.
    """
    half = max(1, smoothing_window // 2)
    lo = max(0, peak_position - half)
    hi = min(len(raw), peak_position + half + 1)
    neighbourhood = raw.iloc[lo:hi].dropna()
    if neighbourhood.empty:
        return False
    return bool(neighbourhood.median() < spike_peak_ratio * peak_value)


def detect_peak(
    processed: pd.DataFrame,
    smoothing_window: int,
    secondary_peak_ratio: float,
    spike_peak_ratio: float,
    boundary_weeks: int,
    rise_weeks: int,
) -> PeakResult:
    """Find the peak of one preprocessed trend series and qualify it.

    The peak is the maximum of `interest_smooth`; `peak_value_raw` is the
    unsmoothed value of that same week (`None` if it was a gap). Ratio/weeks
    parameters tune the spike, secondary-peak, boundary, and rising checks.
    """
    smooth = processed["interest_smooth"]
    if smooth.notna().sum() == 0:
        return PeakResult()

    peak_date = smooth.idxmax()
    peak_position = smooth.index.get_loc(peak_date)
    peak_value = float(smooth.loc[peak_date])
    last_position = len(smooth) - 1

    raw_at_peak = processed["interest_raw"].loc[peak_date]
    peak_value_raw = None if pd.isna(raw_at_peak) else float(raw_at_peak)

    is_spike = _is_spike_driven(processed["interest_raw"], peak_position, smoothing_window, peak_value, spike_peak_ratio)

    # A second hump only counts if the series dropped back below the threshold
    # in between, otherwise it's a shoulder of the same peak. Gap weeks count as below.
    above = (smooth >= secondary_peak_ratio * peak_value).fillna(False)
    other_runs = [(start, end) for start, end in _threshold_runs(above) if not start <= peak_position < end]
    secondary_date: pd.Timestamp | None = None
    secondary_value: float | None = None
    if other_runs:
        tallest = max(other_runs, key=lambda run: smooth.iloc[run[0] : run[1]].max())
        window = smooth.iloc[tallest[0] : tallest[1]]
        secondary_date = window.idxmax()
        secondary_value = float(window.max())

    at_boundary = peak_position < boundary_weeks or peak_position > last_position - boundary_weeks

    # Still rising: peak is the newest week AND the series climbed into it
    # (a flat series also ends on its maximum, but isn't rising).
    rising = False
    if peak_position == last_position and last_position > 0:
        earlier = smooth.iloc[max(0, last_position - rise_weeks)]
        rising = bool(pd.notna(earlier) and peak_value > earlier)

    return PeakResult(
        peak_date=peak_date,
        peak_value=peak_value,
        peak_value_raw=peak_value_raw,
        weeks_since_peak=int(last_position - peak_position),
        peak_is_spike=is_spike,
        has_secondary_peak=secondary_date is not None,
        secondary_peak_date=secondary_date,
        secondary_peak_value=secondary_value,
        peak_at_boundary=bool(at_boundary),
        pre_peak=rising,
    )


PEAK_COLUMNS = (
    "peak_date",
    "peak_value",
    "peak_value_raw",
    "weeks_since_peak",
    "peak_is_spike",
    "has_secondary_peak",
    "secondary_peak_date",
    "secondary_peak_value",
    "peak_at_boundary",
    "pre_peak",
)

# Explicit dtypes so an all-null column still round-trips through parquet correctly.
# Public: reused by `fashion_trends.metrics.schema`.
PEAK_DTYPES = {
    "peak_date": "datetime64[ns]",
    "peak_value": "float64",
    "peak_value_raw": "float64",
    "weeks_since_peak": "Int64",
    "peak_is_spike": "bool",
    "has_secondary_peak": "bool",
    "secondary_peak_date": "datetime64[ns]",
    "secondary_peak_value": "float64",
    "peak_at_boundary": "bool",
    "pre_peak": "bool",
}


def detect_peaks_by_trend(
    series: pd.DataFrame,
    smoothing_window: int,
    secondary_peak_ratio: float,
    spike_peak_ratio: float,
    boundary_weeks: int,
    rise_weeks: int,
) -> pd.DataFrame:
    """Run `detect_peak` over every trend, returning one row per `trend_id` carrying `PEAK_COLUMNS`."""
    rows = []
    for trend_id, group in series.groupby("trend_id", sort=False):
        processed = group.set_index("date")[["interest_raw", "interest_smooth"]].sort_index()
        result = detect_peak(
            processed,
            smoothing_window,
            secondary_peak_ratio,
            spike_peak_ratio,
            boundary_weeks,
            rise_weeks,
        )
        rows.append({"trend_id": trend_id, **result.to_row()})

    frame = pd.DataFrame(rows, columns=["trend_id", *PEAK_COLUMNS])
    return frame.astype(PEAK_DTYPES)
