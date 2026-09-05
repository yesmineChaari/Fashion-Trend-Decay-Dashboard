"""Locate a trend's peak and flag the cases where a single peak is a lie.

Every decay metric downstream is measured *relative to the peak* — % dropped
since peak, % of peak lost per week, weeks until half the peak is gone — so a
peak in the wrong week doesn't produce a slightly wrong number, it produces a
confident wrong number for the whole trend. That makes the interesting part of
this module not the `idxmax` but the four shapes where the peak is real yet the
story around it isn't:

* **A false spike.** One week of unrelated news puts a trend at its all-time
  high. The peak is read off `interest_smooth` (see
  `fashion_trends.metrics.smoothing`), which cuts a lone spike down toward
  its neighbours — but does not remove it: against a flat baseline the
  averaged-down spike is still the tallest thing in the window, so the peak
  lands on (or beside) it anyway, several times higher than the level the
  trend actually held. `peak_is_spike` marks a peak whose height rests on a
  single week — the neighbourhood around it is mostly baseline — and
  `peak_value_raw` carries the unsmoothed value of the peak week so the gap
  between the two stays visible.
* **A revival.** A trend peaks, fades, and comes back. The global maximum is
  still the peak — but "dropped 60% since peak" describes neither hump when a
  second one nearly as tall sits at the other end of the window.
  `has_secondary_peak` marks it so the UI can say two peaks rather than
  quietly averaging them into one decay story.
* **A peak against the window edge.** If the tallest week is in the first or
  last few weeks observed, the real peak may well sit outside the window
  entirely — before the pull started, or after it ends. `peak_at_boundary`
  says the numbers describe a fragment, not a lifecycle.
* **A trend still on the way up.** If the peak *is* the most recent week and
  the series is still climbing into it, there is no decay to measure yet.
  `pre_peak` marks it; decay metrics for these trends belong as nulls, not as
  a zero drop.

None of these flags reject a trend. They travel with it as columns in
`metrics.parquet`, so the charts and the dashboard can present a fragment as a
fragment instead of ranking it against complete ones.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class PeakResult:
    """One trend's peak, plus the flags qualifying how much it can be trusted.

    Every value field is `None` for a series with no usable observations, so a
    caller never has to tell "no peak found" apart from "a peak of zero".
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
    """Positional `(start, end)` spans of each contiguous `True` run in `above`.

    `end` is exclusive. This is what splits a smoothed series into the separate
    episodes where it sits above the secondary-peak threshold: two humps are
    two runs precisely because the series came back *down* between them.
    """
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

    The test is the *median* of the raw weeks the smoothing window averaged
    into the peak. A median is what separates the two cases the mean cannot:
    a real hump has tall neighbours, so its median sits near the peak; a lone
    spike is surrounded by baseline, so the median stays down at the level the
    trend actually held while the mean is dragged up by the one outlier week.
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

    `processed` is the frame returned by
    `fashion_trends.metrics.smoothing.preprocess_series`: a complete weekly
    `DatetimeIndex` with `interest_raw` and `interest_smooth` columns. The peak
    is the maximum of the smoothed column; `peak_value_raw` is the unsmoothed
    value of that same week (`None` if that week was a gap in the pull).

    `smoothing_window` must be the window that frame was smoothed with — it is
    how wide a neighbourhood the spike check looks at. `secondary_peak_ratio`
    is the fraction of the peak another hump must reach to count as a second
    one, `spike_peak_ratio` the fraction of it the peak's own neighbourhood
    must hold to count as a hump rather than a spike, `boundary_weeks` how
    close to either end of the window still counts as the edge, and
    `rise_weeks` how far back to look to decide a trend is still climbing.
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
    # in between — otherwise it is a shoulder of the same peak, and calling it
    # a revival would put a two-peak warning on what is really one plateau.
    # Gap weeks count as below, which is the conservative reading: a hole in
    # the data is not evidence of a hump.
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

    # Still rising: the peak is the newest week we have *and* the smoothed
    # series climbed into it. The second half matters — a flat series also ends
    # on its maximum, and that is a trend going nowhere rather than one on the
    # way up.
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

# Explicit dtypes so a column that happens to be all-null in one run still
# round-trips through parquet as the type the rest of the pipeline expects.
# Public: `fashion_trends.metrics.schema` reuses this as the single source of
# truth for these columns' dtypes in the canonical metrics table.
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
    """Run `detect_peak` over every trend in a long-format series frame.

    `series` has `series.parquet`'s shape — one row per (trend, week), with
    `date`, `trend_id`, `interest_raw`, and `interest_smooth` columns. Returns
    one row per `trend_id` carrying `PEAK_COLUMNS`, ready to merge onto the
    metrics table.
    """
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
