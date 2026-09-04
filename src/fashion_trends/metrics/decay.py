"""Measure how far a trend has fallen from its own peak, and how fast.

Two metrics live here, and they answer different questions about the same
descent. `compute_pct_dropped` says *how far* a trend has fallen;
`compute_decay_rate` says *how quickly* it got there — a trend that
collapsed in eight weeks and one that faded gently over two years can show
the same "% dropped", which is exactly why the second metric exists.

The headline percentage has to survive the two ways a peak-relative
percentage lies:

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

The rate is reported two ways, because the obvious one is not the honest
one. Dividing the drop by the weeks since the peak assumes the decline was
a straight line, and real decay curves are closer to exponential — steep
at first, then flattening. So a log-linear fit over the post-peak segment
is reported alongside it, together with its R². That R² is the point: a
trend that fell off a cliff and then plateaued fits an exponential badly,
and a reader deciding whether to trust a single decay number for that trend
should be able to see so rather than having to infer it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
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


@dataclass(frozen=True)
class DecayRateResult:
    """How fast one trend lost its peak, both ways of measuring it.

    `decay_rate_linear` is percentage points of the peak lost per week —
    directly comparable to `pct_dropped`, and the number to quote when a
    reader asks how fast a trend fell. `decay_rate_exp` is the weekly decay
    constant `k` of a log-linear fit, so the fitted curve is
    `peak * exp(-k * weeks)`; a `k` of 0.05 means the trend loses about 4.9%
    (`1 - exp(-0.05)`) of *whatever is left* each week rather than 5% of its
    original peak. `decay_fit_r2` says how well that single constant
    describes the trend at all, and `decay_fit_weeks` how many post-peak
    weeks went into the fit.

    Every field is `None` when the corresponding number cannot honestly be
    produced — see `compute_decay_rate` for which case nulls which field.
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
    is too short to fit. `segment` starts at the peak week, so position is
    weeks since peak — the series is on a complete weekly index (see
    `fashion_trends.metrics.smoothing.normalize_weekly_index`), which is what
    lets a gap week be dropped from the fit without shifting the weeks of
    everything after it.

    Only positive weeks can be fitted: `log(0)` is undefined, and a trend
    that has decayed all the way to zero has no exponential left to measure
    there. Those weeks are dropped rather than floored to some small
    constant, which would invent a decay slope out of the choice of floor.
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
    # A perfectly flat post-peak segment has no variance for the fit to
    # explain, and the fit reproduces it exactly: a decay constant of 0
    # describing that trend perfectly, which is r2 = 1 rather than 0/0.
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

    `processed` is a frame indexed by date with an `interest_smooth` column —
    the shape `fashion_trends.metrics.smoothing.preprocess_series` returns.
    `peak_date`, `weeks_since_peak`, and `pre_peak` come from that trend's
    `fashion_trends.metrics.peaks.PeakResult`, and `pct_dropped` from its
    `PctDroppedResult`.

    `decay_rate_linear` is `pct_dropped / weeks_since_peak`. The exponential
    fit runs over the smoothed series from the peak week to the end of the
    window; smoothing is safe here because a centred rolling mean scales an
    exponential by a constant factor rather than bending it, so it leaves the
    fitted decay constant alone while keeping a noisy week from tilting it.

    Returns an all-`None` result when `pre_peak` — there is no decay to
    measure yet. `decay_rate_linear` alone is `None` when `pct_dropped` is
    (no peak, or a zero peak) or when `weeks_since_peak` is 0, since the peak
    is the most recent week and no time has passed to spread the drop over.
    The fit fields alone are `None` when fewer than `min_fit_weeks` positive
    weeks sit in the post-peak segment: too short a segment fits a decay
    constant that extrapolates wildly, and a null is the more honest answer.
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

# Explicit dtypes so a column that happens to be all-null in one run still
# round-trips through parquet as the type the rest of the pipeline expects.
_DECAY_RATE_DTYPES = {
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
    """Run `compute_decay_rate` over every trend in a long-format series frame.

    `series` has `series.parquet`'s shape — one row per (trend, week), with
    `date`, `trend_id`, and `interest_smooth` columns. `peaks` is the frame
    returned by `fashion_trends.metrics.peaks.detect_peaks_by_trend` and
    `pct_dropped` the one returned by `compute_pct_dropped_by_trend`, both
    keyed by `trend_id`. Returns one row per `trend_id` carrying
    `DECAY_RATE_COLUMNS`, ready to merge onto the metrics table.
    """
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
    return frame.astype(_DECAY_RATE_DTYPES)
