"""Measure how far a trend has fallen from its own peak, and how fast.

`compute_pct_dropped` says how far it fell; `compute_decay_rate` says how
fast; `compute_time_to_half` says how long it took to lose half its peak.

`current_value` is averaged over the last `smoothing_window` complete weeks
rather than the single most recent one, to absorb a noisy trailing week. A
current level reading above the peak means the peak was misdetected, so
`pct_dropped` is clamped to 0 and flagged as `current_above_peak` instead of
reported as a negative drop.

The rate is reported two ways: linearly, and as a log-linear exponential fit
with its R² (since real decay curves flatten rather than fall in a straight
line, and the R² lets a reader judge whether a single decay number is even
trustworthy for that trend).

A half-life crossing only counts once the series stays below the threshold
for `sustained_weeks`, so one noisy dip isn't mistaken for the crossing. A
trend that never crosses is reported as its own status, not a null.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PctDroppedResult:
    """% dropped since peak for one trend, plus the numbers behind it.

    Every field is `None` when there is nothing to report yet, so a caller
    never has to tell "not decaying" apart from "decaying by 0%".
    """

    pct_dropped: float | None = None
    current_value: float | None = None
    current_window_end: pd.Timestamp | None = None
    # True when the raw (unclamped) drop was negative, i.e. the peak was misdetected.
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

    `current_value` is the mean of the last `smoothing_window` complete
    weeks of `interest_raw`, skipping gap weeks. `pct_dropped` is clamped to
    `[0, 100]`. Returns an all-`None` result when `pre_peak`, when
    `peak_value` is `None`, or when `processed` has no raw observations.
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
        # No measurable interest was ever recorded, so no drop to express as a percentage.
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

# Explicit dtypes so an all-null column still round-trips through parquet correctly.
# Public: reused by `fashion_trends.metrics.schema`.
PCT_DROPPED_DTYPES = {
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

    Returns one row per `trend_id` carrying `PCT_DROPPED_COLUMNS`, ready to
    merge onto the metrics table.
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
    return frame.astype(PCT_DROPPED_DTYPES)


@dataclass(frozen=True)
class DecayRateResult:
    """How fast one trend lost its peak, both ways of measuring it.

    `decay_rate_linear` is percentage points of the peak lost per week.
    `decay_rate_exp` is the weekly decay constant `k` of a log-linear fit
    (`peak * exp(-k * weeks)`), with `decay_fit_r2` and `decay_fit_weeks`
    describing how well and over how many weeks it fit. Every field is
    `None` when it can't honestly be produced.
    """

    decay_rate_linear: float | None = None
    decay_rate_exp: float | None = None
    decay_fit_r2: float | None = None
    decay_fit_weeks: int | None = None

    def to_row(self) -> dict[str, Any]:
        """A flat dict of this result, one key per `metrics.parquet` column."""
        return asdict(self)


def _fit_exponential_decay(
    segment: pd.Series,
    min_fit_weeks: int,
) -> tuple[float, float, int] | None:
    """Fit `log(interest)` against weeks since peak over one post-peak segment.

    Returns `(decay_constant, r2, weeks_fitted)`, or `None` when the segment
    is too short to fit. Zero/negative weeks are dropped rather than floored,
    since `log(0)` is undefined.
    """
    values = segment.to_numpy(dtype=float)
    weeks = np.arange(len(values), dtype=float)

    fittable = np.isfinite(values) & (values > 0)
    weeks, values = weeks[fittable], values[fittable]
    if len(values) < min_fit_weeks:
        return None

    log_values = np.log(values)
    slope, intercept = np.polyfit(weeks, log_values, 1)

    residual_ss = float(((log_values - (slope * weeks + intercept)) ** 2).sum())
    total_ss = float(((log_values - log_values.mean()) ** 2).sum())
    # A perfectly flat segment has no variance to explain; r2 = 1, not 0/0.
    r2 = 1.0 if total_ss == 0 else 1.0 - residual_ss / total_ss

    return float(-slope), r2, int(len(values))


def compute_decay_rate(
    processed: pd.DataFrame,
    peak_date: pd.Timestamp | None,
    weeks_since_peak: int | None,
    pct_dropped: float | None,
    pre_peak: bool,
    min_fit_weeks: int,
) -> DecayRateResult:
    """How fast one trend lost its peak, linearly and as an exponential fit.

    `decay_rate_linear` is `pct_dropped / weeks_since_peak`. The exponential
    fit runs over the smoothed series from the peak week to the end of the
    window. Returns an all-`None` result when `pre_peak`; `decay_rate_linear`
    alone is `None` when `pct_dropped` is, or `weeks_since_peak` is 0; the fit
    fields alone are `None` when fewer than `min_fit_weeks` positive weeks
    are available.
    """
    if pre_peak:
        return DecayRateResult()

    decay_rate_linear = None
    if pct_dropped is not None and weeks_since_peak:
        decay_rate_linear = pct_dropped / weeks_since_peak

    if peak_date is None or peak_date not in processed.index:
        return DecayRateResult(decay_rate_linear=decay_rate_linear)

    fit = _fit_exponential_decay(processed["interest_smooth"].loc[peak_date:], min_fit_weeks)
    if fit is None:
        return DecayRateResult(decay_rate_linear=decay_rate_linear)

    decay_rate_exp, r2, weeks_fitted = fit
    return DecayRateResult(
        decay_rate_linear=decay_rate_linear,
        decay_rate_exp=decay_rate_exp,
        decay_fit_r2=r2,
        decay_fit_weeks=weeks_fitted,
    )


DECAY_RATE_COLUMNS = (
    "decay_rate_linear",
    "decay_rate_exp",
    "decay_fit_r2",
    "decay_fit_weeks",
)

# Explicit dtypes so an all-null column still round-trips through parquet correctly.
# Public: reused by `fashion_trends.metrics.schema`.
DECAY_RATE_DTYPES = {
    "decay_rate_linear": "float64",
    "decay_rate_exp": "float64",
    "decay_fit_r2": "float64",
    "decay_fit_weeks": "Int64",
}


def compute_decay_rate_by_trend(
    series: pd.DataFrame,
    peaks: pd.DataFrame,
    pct_dropped: pd.DataFrame,
    min_fit_weeks: int,
) -> pd.DataFrame:
    """Run `compute_decay_rate` over every trend, returning one row per `trend_id` carrying `DECAY_RATE_COLUMNS`."""
    peaks_by_id = peaks.set_index("trend_id")
    pct_dropped_by_id = pct_dropped.set_index("trend_id")

    rows = []
    for trend_id, group in series.groupby("trend_id", sort=False):
        processed = group.set_index("date")[["interest_smooth"]].sort_index()
        peak_row = peaks_by_id.loc[trend_id]
        drop = pct_dropped_by_id.loc[trend_id, "pct_dropped"]
        result = compute_decay_rate(
            processed,
            None if pd.isna(peak_row["peak_date"]) else peak_row["peak_date"],
            None if pd.isna(peak_row["weeks_since_peak"]) else int(peak_row["weeks_since_peak"]),
            None if pd.isna(drop) else float(drop),
            bool(peak_row["pre_peak"]),
            min_fit_weeks,
        )
        rows.append({"trend_id": trend_id, **result.to_row()})

    frame = pd.DataFrame(rows, columns=["trend_id", *DECAY_RATE_COLUMNS])
    return frame.astype(DECAY_RATE_DTYPES)


# Values `time_to_half_status` takes.
HALF_LIFE_CROSSED = "crossed"
HALF_LIFE_STILL_ABOVE = "still_above_half"
HALF_LIFE_PRE_PEAK = "pre_peak"
HALF_LIFE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class TimeToHalfResult:
    """How long one trend took to lose half its peak, and whether it ever did.

    `weeks_to_half` is `None` in three cases, distinguished by
    `time_to_half_status`: never dropped below half (`still_above_half`), no
    decay to measure yet (`pre_peak`), or the metric couldn't be computed at
    all (`unknown`).
    """

    weeks_to_half: int | None = None
    half_life_date: pd.Timestamp | None = None
    time_to_half_status: str = HALF_LIFE_UNKNOWN

    def to_row(self) -> dict[str, Any]:
        """A flat dict of this result, one key per `metrics.parquet` column."""
        return asdict(self)


def _first_sustained_crossing(below: pd.Series, min_weeks: int) -> int | None:
    """Position in `below` where a run of at least `min_weeks` `True` starts.

    Gap weeks arrive as `False` and break a run, the conservative reading.
    """
    run_start: int | None = None
    for position, flag in enumerate(below.to_numpy()):
        if not flag:
            run_start = None
            continue
        if run_start is None:
            run_start = position
        if position - run_start + 1 >= min_weeks:
            return run_start
    return None


def compute_time_to_half(
    processed: pd.DataFrame,
    peak_date: pd.Timestamp | None,
    peak_value: float | None,
    pre_peak: bool,
    sustained_weeks: int,
) -> TimeToHalfResult:
    """Weeks from one trend's peak until it had lost half of it.

    The crossing is the first week after the peak where the smoothed series
    drops below `0.5 * peak_value` and stays there for `sustained_weeks`
    consecutive weeks. `time_to_half_status` distinguishes the three ways
    `weeks_to_half` can be `None`, see `TimeToHalfResult`.
    """
    if pre_peak:
        return TimeToHalfResult(time_to_half_status=HALF_LIFE_PRE_PEAK)
    if peak_date is None or not peak_value or peak_date not in processed.index:
        return TimeToHalfResult(time_to_half_status=HALF_LIFE_UNKNOWN)

    # From the peak week onward, so position is weeks since peak.
    segment = processed["interest_smooth"].loc[peak_date:]
    below = (segment < 0.5 * peak_value).fillna(False)

    crossing = _first_sustained_crossing(below, sustained_weeks)
    if crossing is None:
        return TimeToHalfResult(time_to_half_status=HALF_LIFE_STILL_ABOVE)

    return TimeToHalfResult(
        weeks_to_half=int(crossing),
        half_life_date=segment.index[crossing],
        time_to_half_status=HALF_LIFE_CROSSED,
    )


TIME_TO_HALF_COLUMNS = (
    "weeks_to_half",
    "half_life_date",
    "time_to_half_status",
)

# Explicit dtypes so an all-null column still round-trips through parquet correctly.
# Public: reused by `fashion_trends.metrics.schema`.
TIME_TO_HALF_DTYPES = {
    "weeks_to_half": "Int64",
    "half_life_date": "datetime64[ns]",
    "time_to_half_status": "string",
}


def compute_time_to_half_by_trend(
    series: pd.DataFrame,
    peaks: pd.DataFrame,
    sustained_weeks: int,
) -> pd.DataFrame:
    """Run `compute_time_to_half` over every trend, returning one row per `trend_id` carrying `TIME_TO_HALF_COLUMNS`."""
    peaks_by_id = peaks.set_index("trend_id")

    rows = []
    for trend_id, group in series.groupby("trend_id", sort=False):
        processed = group.set_index("date")[["interest_smooth"]].sort_index()
        peak_row = peaks_by_id.loc[trend_id]
        result = compute_time_to_half(
            processed,
            None if pd.isna(peak_row["peak_date"]) else peak_row["peak_date"],
            None if pd.isna(peak_row["peak_value"]) else float(peak_row["peak_value"]),
            bool(peak_row["pre_peak"]),
            sustained_weeks,
        )
        rows.append({"trend_id": trend_id, **result.to_row()})

    frame = pd.DataFrame(rows, columns=["trend_id", *TIME_TO_HALF_COLUMNS])
    return frame.astype(TIME_TO_HALF_DTYPES)
