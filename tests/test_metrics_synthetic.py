"""The metrics engine against synthetic series with hand-computed answers.

Real Google Trends data can't serve as a fixed oracle since it's sampled, so
the series here are constructed from closed forms whose every expected
metric can be derived on paper, and expectations are written as those
derivations rather than numbers copied from a passing run.

Two facts about the smoothing underpin every derivation, both verified by
their own tests at the top of this file:

* With `window=4, center=True`, `smooth[t] = mean(raw[t-2], raw[t-1], raw[t], raw[t+1])`.
* Consequently `smooth[t+1] - smooth[t] = (raw[t+2] - raw[t-2]) / 4`, which
  is why every rise-then-fall fixture here rises more gently than it falls
  (otherwise the detected peak week would shift).

Null-returning cases are asserted to be null rather than zero, since each
null means something distinct ("no peak found yet", "fit too short to
trust", "never crossed half its peak").
"""

import math

import numpy as np
import pandas as pd
import pytest

from fashion_trends.metrics import compute_all
from fashion_trends.metrics.decay import (
    HALF_LIFE_CROSSED,
    HALF_LIFE_PRE_PEAK,
    HALF_LIFE_STILL_ABOVE,
    HALF_LIFE_UNKNOWN,
)
from fashion_trends.metrics.smoothing import preprocess_series
from fashion_trends.metrics.status import (
    STATUS_COLLAPSED,
    STATUS_DECLINING,
    STATUS_PRE_PEAK,
    STATUS_REVIVED,
    STATUS_STABILIZED,
    STATUS_UNKNOWN,
)
from fashion_trends.settings import Settings

SETTINGS = Settings()
WINDOW = SETTINGS.smoothing_window  # 4
START = pd.Timestamp("2023-01-01")


def week(position: int) -> pd.Timestamp:
    """The date at `position` weeks into every fixture's shared weekly index."""
    return START + pd.Timedelta(weeks=position)


def smoothed_at(values, position: int) -> float:
    """`smooth[position]` derived directly from the centred-window definition, independent of the code under test."""
    lo = max(0, position - WINDOW // 2)
    hi = position + WINDOW // 2
    return float(np.mean(np.asarray(values, dtype=float)[lo:hi]))


def metrics_for(values, low_resolution: bool = False) -> pd.Series:
    """Run `compute_all` over one synthetic series and return its single row.

    Builds the same `series.parquet`-shaped input the real pipeline builds,
    so the whole engine is under test end to end.
    """
    raw = pd.Series(
        np.asarray(values, dtype=float),
        index=pd.date_range(START, periods=len(values), freq="W-SUN"),
    )
    processed = preprocess_series(raw, WINDOW)

    series = pd.DataFrame(
        {
            "date": processed.index,
            "trend_id": "synthetic",
            "keyword": "synthetic",
            "display_name": "Synthetic",
            "category": "garment",
            "interest_raw": processed["interest_raw"].to_numpy(),
            "interest_smooth": processed["interest_smooth"].to_numpy(),
            "low_resolution": low_resolution,
        }
    )

    frame = compute_all(series, SETTINGS)
    assert len(frame) == 1
    return frame.iloc[0]


def ramp(start: float, stop: float, weeks: int) -> np.ndarray:
    """`weeks` evenly spaced values walking from just after `start` to `stop`.

    `start` is excluded, so ramps concatenate without repeating their join
    point: `[a] + ramp(a, b, n) + ramp(b, c, m)` is one continuous shape.
    """
    return np.linspace(start, stop, weeks + 1)[1:]


# ---- the smoothing convention the derivations below rest on ----------------


def test_centred_window_covers_two_weeks_back_and_one_forward():
    smooth = pd.Series(np.arange(10, dtype=float)).rolling(WINDOW, center=True, min_periods=1).mean()

    # position 4's window is raw[2..5] -> mean 3.5, not raw[3..6] (4.5).
    assert smooth.iloc[4] == pytest.approx(3.5)
    assert smooth.iloc[4] == pytest.approx(smoothed_at(np.arange(10), 4))


def test_smoothed_step_between_weeks_is_the_four_week_span_difference():
    # smooth[t+1] - smooth[t] == (raw[t+2] - raw[t-2]) / 4 -- the identity that
    # fixes where each fixture's detected peak lands.
    raw = np.array([3.0, 9.0, 4.0, 1.0, 7.0, 2.0, 8.0, 5.0, 6.0, 0.0])
    smooth = pd.Series(raw).rolling(WINDOW, center=True, min_periods=1).mean()

    for t in range(2, len(raw) - 2):
        assert smooth.iloc[t + 1] - smooth.iloc[t] == pytest.approx((raw[t + 2] - raw[t - 2]) / 4)


# ---- clean exponential decay, known constant and known half-life ----------

EXP_PEAK_POSITION = 30
EXP_WEEKS = 140
EXP_RISE_K = 0.02
EXP_DECAY_K = 0.04


def exponential_decay_shape() -> np.ndarray:
    """Rises at `e^0.02/wk` to 100, then decays at exactly `e^-0.04/wk`.

    The rise is gentler than the decay, which by the module docstring's step
    identity puts the smoothed maximum on the raw apex at
    `EXP_PEAK_POSITION` rather than a week after it.
    """
    return np.array(
        [
            100 * math.exp(-EXP_RISE_K * (EXP_PEAK_POSITION - t))
            if t <= EXP_PEAK_POSITION
            else 100 * math.exp(-EXP_DECAY_K * (t - EXP_PEAK_POSITION))
            for t in range(EXP_WEEKS)
        ]
    )


def test_exponential_decay_peak_is_the_four_week_mean_at_the_apex():
    values = exponential_decay_shape()

    row = metrics_for(values)

    assert row["peak_date"] == week(EXP_PEAK_POSITION)
    # 25 * (e^-0.04 + e^-0.02 + 1 + e^-0.04): the two rise weeks before the
    # apex, the apex at 100, and the first decay week after it.
    assert row["peak_value"] == pytest.approx(
        25 * (math.exp(-2 * EXP_RISE_K) + math.exp(-EXP_RISE_K) + 1 + math.exp(-EXP_DECAY_K))
    )
    assert row["peak_value_raw"] == pytest.approx(100.0)
    assert row["weeks_since_peak"] == EXP_WEEKS - 1 - EXP_PEAK_POSITION


def test_exponential_decay_recovers_its_own_decay_constant():
    values = exponential_decay_shape()

    row = metrics_for(values)

    # A centred mean scales an exponential by a constant factor rather than
    # bending it, so the fitted constant is the constructed one -- to within
    # the partial windows at the two ends of the fitted segment.
    assert row["decay_rate_exp"] == pytest.approx(EXP_DECAY_K, rel=0.01)
    assert row["decay_fit_r2"] > 0.999
    assert row["decay_fit_weeks"] == EXP_WEEKS - EXP_PEAK_POSITION


def test_exponential_decay_pct_dropped_and_linear_rate_follow_from_the_peak():
    values = exponential_decay_shape()
    peak_value = 25 * (math.exp(-2 * EXP_RISE_K) + math.exp(-EXP_RISE_K) + 1 + math.exp(-EXP_DECAY_K))
    current_value = float(values[-WINDOW:].mean())
    pct_dropped = (peak_value - current_value) / peak_value * 100

    row = metrics_for(values)

    assert row["current_value"] == pytest.approx(current_value)
    assert row["pct_dropped"] == pytest.approx(pct_dropped)
    assert row["decay_rate_linear"] == pytest.approx(pct_dropped / (EXP_WEEKS - 1 - EXP_PEAK_POSITION))
    assert bool(row["current_above_peak"]) is False


def test_exponential_decay_crosses_half_its_peak_on_the_derived_week():
    values = exponential_decay_shape()
    peak_value = 25 * (math.exp(-2 * EXP_RISE_K) + math.exp(-EXP_RISE_K) + 1 + math.exp(-EXP_DECAY_K))
    # Well clear of the peak the smoothed segment is 100 * factor * e^-kj,
    # where factor is the centred mean of e^{2k}, e^{k}, 1, e^{-k}. Solving
    # 100 * factor * e^-kj < peak_value / 2 gives j > 18.48, so week 19 is the
    # first below the threshold -- and it stays below, so that is the crossing.
    factor = (math.exp(2 * EXP_DECAY_K) + math.exp(EXP_DECAY_K) + 1 + math.exp(-EXP_DECAY_K)) / 4
    expected_weeks = math.ceil(math.log(100 * factor / (0.5 * peak_value)) / EXP_DECAY_K)
    assert expected_weeks == 19

    row = metrics_for(values)

    assert row["weeks_to_half"] == expected_weeks
    assert row["half_life_date"] == week(EXP_PEAK_POSITION + expected_weeks)
    assert row["time_to_half_status"] == HALF_LIFE_CROSSED
    assert row["status"] == STATUS_COLLAPSED


# ---- linear decay ----------------------------------------------------

LIN_PEAK_POSITION = 30
LIN_RISE_PER_WEEK = 0.5
LIN_FALL_PER_WEEK = 1.0
LIN_TAIL_WEEKS = 90


def linear_decay_shape() -> np.ndarray:
    """Climbs 0.5/wk to 100, then loses exactly 1.0/wk for 90 weeks."""
    return np.concatenate(
        [
            np.array([100 - LIN_RISE_PER_WEEK * LIN_PEAK_POSITION]),
            ramp(
                100 - LIN_RISE_PER_WEEK * LIN_PEAK_POSITION,
                100,
                LIN_PEAK_POSITION,
            ),
            ramp(100, 100 - LIN_FALL_PER_WEEK * LIN_TAIL_WEEKS, LIN_TAIL_WEEKS),
        ]
    )


def test_linear_decay_peak_and_drop_are_exact():
    values = linear_decay_shape()

    row = metrics_for(values)

    assert row["peak_date"] == week(LIN_PEAK_POSITION)
    # (99 + 99.5 + 100 + 99) / 4 -- two rise weeks, the apex, one fall week.
    assert row["peak_value"] == pytest.approx(99.375)
    assert row["peak_value_raw"] == pytest.approx(100.0)
    assert row["weeks_since_peak"] == LIN_TAIL_WEEKS
    # The last four raw weeks are 13, 12, 11, 10.
    assert row["current_value"] == pytest.approx(11.5)
    assert row["pct_dropped"] == pytest.approx((99.375 - 11.5) / 99.375 * 100)
    assert row["decay_rate_linear"] == pytest.approx((99.375 - 11.5) / 99.375 * 100 / LIN_TAIL_WEEKS)


def test_linear_decay_crosses_half_its_peak_on_the_derived_week():
    values = linear_decay_shape()
    # Smoothing a ramp shifts it half a week: smooth[peak + j] = 100 - (j - 0.5)
    # once clear of the apex. That falls below 99.375 / 2 at j > 50.81, so the
    # crossing is week 51.
    expected_weeks = math.ceil((100 - 0.5 * 99.375) / LIN_FALL_PER_WEEK + 0.5)
    assert expected_weeks == 51

    row = metrics_for(values)

    assert row["weeks_to_half"] == expected_weeks
    assert row["half_life_date"] == week(LIN_PEAK_POSITION + expected_weeks)
    assert row["time_to_half_status"] == HALF_LIFE_CROSSED


def test_linear_decay_fits_an_exponential_visibly_worse_than_an_exponential_does():
    # The whole reason `decay_fit_r2` is reported: one decay constant does
    # describe this trend, but not nearly as well as it describes a genuine
    # exponential, and a reader deciding whether to quote that constant needs
    # to be able to see the difference.
    linear_r2 = metrics_for(linear_decay_shape())["decay_fit_r2"]
    exponential_r2 = metrics_for(exponential_decay_shape())["decay_fit_r2"]

    assert linear_r2 < 0.95
    assert linear_r2 < exponential_r2


# ---- sharp spike then fast collapse (the fast-fad shape) -------------------

FAD_PEAK_POSITION = 8
FAD_COLLAPSE_K = 0.35
FAD_FLOOR = 1.0


def fast_fad_shape() -> np.ndarray:
    """Eight weeks up to 100, a two-month collapse, then a long residual floor."""
    return np.concatenate(
        [
            ramp(2 - (100 - 2) / FAD_PEAK_POSITION, 100, FAD_PEAK_POSITION + 1),
            100 * np.exp(-FAD_COLLAPSE_K * np.arange(1, 13)),
            np.full(90, FAD_FLOOR),
        ]
    )


def test_fast_fad_halves_within_a_month_of_its_peak():
    row = metrics_for(fast_fad_shape())

    assert row["peak_date"] == week(FAD_PEAK_POSITION)
    assert row["weeks_to_half"] == 4
    assert row["time_to_half_status"] == HALF_LIFE_CROSSED
    assert row["status"] == STATUS_COLLAPSED
    assert row["pct_dropped"] > 95.0


def test_fast_fad_smoothed_peak_sits_well_below_its_raw_peak():
    values = fast_fad_shape()

    row = metrics_for(values)

    # A steep, narrow peak is exactly what a centred mean cuts down, so the
    # two values must be reported side by side rather than one standing in
    # for the other.
    assert row["peak_value_raw"] == pytest.approx(100.0)
    assert row["peak_value"] == pytest.approx(smoothed_at(values, FAD_PEAK_POSITION))
    assert row["peak_value"] < 0.9 * row["peak_value_raw"]


def test_fast_fad_collapse_then_plateau_fits_one_constant_badly():
    # Collapse-then-floor is two regimes; a single decay constant describes
    # neither, and the low r2 is the engine saying so.
    assert metrics_for(fast_fad_shape())["decay_fit_r2"] < 0.5


# ---- slow fade that never reaches 50% of peak ------------------------------

FADE_PEAK_POSITION = 20
FADE_PLATEAU = 62.0


def slow_fade_shape() -> np.ndarray:
    """Climbs 0.5/wk to 100, fades 0.95/wk to 62, then holds flat for 60 weeks."""
    return np.concatenate(
        [
            np.array([90.0]),
            ramp(90, 100, FADE_PEAK_POSITION),
            ramp(100, FADE_PLATEAU, 40),
            np.full(60, FADE_PLATEAU),
        ]
    )


def test_slow_fade_never_halves_and_says_so_rather_than_nulling():
    values = slow_fade_shape()

    row = metrics_for(values)

    assert row["peak_date"] == week(FADE_PEAK_POSITION)
    # (99 + 99.5 + 100 + 99.05) / 4
    assert row["peak_value"] == pytest.approx(99.3875)
    # Never below half the peak, so there is no crossing week -- but that is a
    # finding about a trend with staying power, not missing data, and the
    # status column is what distinguishes the two.
    assert pd.isna(row["weeks_to_half"])
    assert pd.isna(row["half_life_date"])
    assert row["time_to_half_status"] == HALF_LIFE_STILL_ABOVE


def test_slow_fade_into_a_plateau_is_stabilized_not_declining():
    row = metrics_for(slow_fade_shape())

    assert row["current_value"] == pytest.approx(FADE_PLATEAU)
    assert row["pct_dropped"] == pytest.approx((99.3875 - FADE_PLATEAU) / 99.3875 * 100)
    assert row["pct_dropped"] < SETTINGS.collapsed_pct_dropped_threshold
    assert row["status"] == STATUS_STABILIZED


# ---- still rising (pre-peak) ----------------------------------------------


def still_rising_shape() -> np.ndarray:
    """Climbs steadily for 80 weeks and is still climbing at the last one."""
    return np.linspace(10, 100, 80)


def test_still_rising_has_a_peak_but_no_decay_to_measure_from_it():
    row = metrics_for(still_rising_shape())

    assert bool(row["pre_peak"]) is True
    assert row["peak_date"] == week(79)
    assert row["weeks_since_peak"] == 0
    # The peak is the newest week we have, so it is also against the window's
    # edge -- the real peak may well sit beyond the pull.
    assert bool(row["peak_at_boundary"]) is True
    assert row["status"] == STATUS_PRE_PEAK


def test_still_rising_nulls_every_decay_metric_rather_than_zeroing_it():
    # The headline null-vs-zero case: "has not fallen at all yet" and "fell by
    # 0%" are opposite claims, and the second would rank this trend alongside
    # the flattest in the set.
    row = metrics_for(still_rising_shape())

    assert pd.isna(row["pct_dropped"])
    assert pd.isna(row["current_value"])
    assert pd.isna(row["decay_rate_linear"])
    assert pd.isna(row["decay_rate_exp"])
    assert pd.isna(row["decay_fit_r2"])
    assert pd.isna(row["decay_fit_weeks"])
    assert pd.isna(row["weeks_to_half"])
    assert row["time_to_half_status"] == HALF_LIFE_PRE_PEAK


# ---- double peak / revival ------------------------------------------------

REVIVAL_PEAK_POSITION = 40


def revival_shape() -> np.ndarray:
    """Peaks at 100, falls to 20, holds, then comes back to 95 and fades again."""
    return np.concatenate(
        [
            np.array([5.0]),
            ramp(5, 100, REVIVAL_PEAK_POSITION),
            ramp(100, 20, 30),
            np.full(20, 20.0),
            ramp(20, 95, 25),
            ramp(95, 40, 25),
        ]
    )


def test_revival_flags_the_second_hump_and_labels_the_trend_revived():
    values = revival_shape()

    row = metrics_for(values)

    assert row["peak_date"] == week(REVIVAL_PEAK_POSITION)
    assert bool(row["has_secondary_peak"]) is True
    assert row["secondary_peak_value"] >= SETTINGS.secondary_peak_ratio * row["peak_value"]
    assert row["secondary_peak_date"] > row["peak_date"]
    assert row["status"] == STATUS_REVIVED


def test_revival_does_not_pretend_one_decay_constant_describes_it():
    # A series that fell and climbed back has no single decay constant; the
    # fit is near-flat with essentially no explanatory power, and `revived` is
    # the label telling a reader not to quote the number.
    row = metrics_for(revival_shape())

    assert row["decay_fit_r2"] < 0.1
    assert abs(row["decay_rate_exp"]) < 0.01


# ---- a one-week outlier that must not become the peak ----------------------

HUMP_APEX_POSITION = 59
OUTLIER_POSITION = 130
OUTLIER_VALUE = 100.0


def outlier_beside_a_hump_shape() -> np.ndarray:
    """A broad hump topping out at 80, plus one unrelated 100 week far away.

    The outlier is the tallest single raw week in the series, and the peak
    must still land on the hump: this is what smoothing is for.
    """
    values = np.full(160, 10.0)
    hump = np.concatenate([ramp(10, 80, 25), ramp(80, 10, 20)])
    values[35 : 35 + len(hump)] = hump
    values[OUTLIER_POSITION] = OUTLIER_VALUE
    return values


def test_a_lone_outlier_week_does_not_win_the_peak_from_a_real_hump():
    values = outlier_beside_a_hump_shape()
    assert values.max() == OUTLIER_VALUE  # the outlier is the tallest raw week

    row = metrics_for(values)

    assert row["peak_date"] == week(HUMP_APEX_POSITION)
    assert row["peak_value_raw"] == pytest.approx(80.0)
    assert row["peak_value"] == pytest.approx(smoothed_at(values, HUMP_APEX_POSITION))
    # A genuine hump has tall neighbours, so it is not flagged as spike-driven.
    assert bool(row["peak_is_spike"]) is False


# ---- a lone spike on a flat baseline --------------------------------------

SPIKE_POSITION = 80
SPIKE_VALUE = 130.0
SPIKE_BASELINE = 10.0


def lone_spike_shape() -> np.ndarray:
    """A flat baseline of 10 with a single 130 week and nothing else."""
    values = np.full(160, SPIKE_BASELINE)
    values[SPIKE_POSITION] = SPIKE_VALUE
    return values


def test_a_lone_spike_becomes_the_peak_but_is_flagged_as_one():
    values = lone_spike_shape()

    row = metrics_for(values)

    # Against a flat baseline the averaged-down spike is still the tallest
    # thing in the window, so it does take the peak -- the flag is what keeps
    # that from being read as a level the trend ever held.
    assert bool(row["peak_is_spike"]) is True
    assert row["peak_value"] == pytest.approx((3 * SPIKE_BASELINE + SPIKE_VALUE) / 4)
    assert row["peak_value"] == pytest.approx(40.0)
    assert row["peak_value"] > 3 * SPIKE_BASELINE


def test_a_lone_spikes_peak_week_sits_within_the_smoothing_window_of_it():
    # Every week whose window contains the spike gets the same smoothed value
    # on a flat baseline, so which of them wins the tie is arbitrary -- which
    # is precisely why `peak_is_spike` exists and the peak date does not carry
    # the story on its own here.
    row = metrics_for(lone_spike_shape())

    offset_weeks = (row["peak_date"] - week(SPIKE_POSITION)) / pd.Timedelta(weeks=1)
    assert abs(offset_weeks) <= WINDOW // 2


def test_a_lone_spike_reports_the_drop_back_to_baseline_against_the_spike():
    row = metrics_for(lone_spike_shape())

    assert row["current_value"] == pytest.approx(SPIKE_BASELINE)
    # (40 - 10) / 40 -- measured against a peak the trend never really held.
    assert row["pct_dropped"] == pytest.approx(75.0)
    assert row["status"] == STATUS_COLLAPSED


# ---- near-zero, low-volume series -----------------------------------------

NEAR_ZERO_APEX_POSITION = 42


def near_zero_shape() -> np.ndarray:
    """Almost entirely zero, with one nine-week bump topping out at 3."""
    values = np.zeros(160)
    values[38:47] = [1, 1, 2, 3, 3, 2, 1, 1, 1]
    return values


def test_near_zero_series_still_produces_a_peak_on_its_own_tiny_scale():
    values = near_zero_shape()

    row = metrics_for(values)

    assert row["peak_date"] == week(NEAR_ZERO_APEX_POSITION)
    # (2 + 3 + 3 + 2) / 4
    assert row["peak_value"] == pytest.approx(2.5)
    assert row["peak_value_raw"] == pytest.approx(3.0)
    assert row["current_value"] == pytest.approx(0.0)
    assert row["pct_dropped"] == pytest.approx(100.0)
    assert row["status"] == STATUS_COLLAPSED


def test_near_zero_series_has_too_few_positive_weeks_to_fit_a_decay_constant():
    # Only four post-peak weeks are above zero, and `log(0)` cannot be fitted.
    # Below `min_decay_fit_weeks` the constant is null rather than a number
    # extrapolated from a handful of rounded-up weeks.
    row = metrics_for(near_zero_shape())

    assert pd.isna(row["decay_rate_exp"])
    assert pd.isna(row["decay_fit_r2"])
    assert pd.isna(row["decay_fit_weeks"])
    # The linear rate does survive -- it needs only the drop and the elapsed
    # weeks, neither of which depends on the fit.
    assert pd.notna(row["decay_rate_linear"])


def test_low_resolution_flag_rides_through_the_engine_onto_the_metrics_row():
    # Computed during ingestion against the shared rescaled axis, not here --
    # the engine's job is to carry it onto the row so the caveat travels with
    # the numbers it qualifies.
    assert bool(metrics_for(near_zero_shape(), low_resolution=True)["low_resolution"]) is True
    assert bool(metrics_for(near_zero_shape(), low_resolution=False)["low_resolution"]) is False


# ---- a series shorter than the smoothing window ---------------------------


def test_series_shorter_than_the_smoothing_window_still_yields_a_peak():
    # `min_periods=1` means three weeks smooth to three values rather than to
    # NaN, so the engine has something to find a peak in.
    values = np.array([10.0, 40.0, 20.0])

    row = metrics_for(values)

    assert pd.notna(row["peak_date"])
    # Position 0's window is raw[0:2] -- the whole window doesn't fit, and the
    # two weeks that do average to 25.
    assert row["peak_value"] == pytest.approx(25.0)
    assert bool(row["peak_at_boundary"]) is True


def test_series_shorter_than_the_smoothing_window_nulls_the_fit():
    values = np.array([10.0, 40.0, 20.0])

    row = metrics_for(values)

    assert pd.isna(row["decay_rate_exp"])
    assert pd.isna(row["decay_fit_r2"])
    assert pd.isna(row["decay_fit_weeks"])
    assert row["status"] == STATUS_DECLINING


# ---- nothing to measure at all --------------------------------------------


def test_an_all_gap_series_returns_nulls_and_the_unknown_status():
    # The escape hatch every metric shares: no peak was found, so nothing
    # measured relative to a peak exists either. None of these may be 0.
    row = metrics_for(np.full(30, np.nan))

    assert pd.isna(row["peak_date"])
    assert pd.isna(row["peak_value"])
    assert pd.isna(row["peak_value_raw"])
    assert pd.isna(row["weeks_since_peak"])
    assert pd.isna(row["pct_dropped"])
    assert pd.isna(row["current_value"])
    assert pd.isna(row["decay_rate_linear"])
    assert pd.isna(row["decay_rate_exp"])
    assert pd.isna(row["decay_fit_r2"])
    assert pd.isna(row["decay_fit_weeks"])
    assert pd.isna(row["weeks_to_half"])
    assert pd.isna(row["half_life_date"])
    assert row["time_to_half_status"] == HALF_LIFE_UNKNOWN
    assert row["status"] == STATUS_UNKNOWN


def test_an_all_gap_series_leaves_every_peak_flag_false():
    row = metrics_for(np.full(30, np.nan))

    assert bool(row["peak_is_spike"]) is False
    assert bool(row["has_secondary_peak"]) is False
    assert bool(row["peak_at_boundary"]) is False
    assert bool(row["pre_peak"]) is False
    assert bool(row["current_above_peak"]) is False


# ---- every shape at once --------------------------------------------------


def test_each_shape_lands_on_the_lifecycle_label_it_was_built_for():
    # One table, so the labels can be read against each other: the same engine
    # settings must separate these six shapes, not just classify each alone.
    shapes = {
        STATUS_COLLAPSED: exponential_decay_shape(),
        STATUS_STABILIZED: slow_fade_shape(),
        STATUS_PRE_PEAK: still_rising_shape(),
        STATUS_REVIVED: revival_shape(),
        STATUS_UNKNOWN: np.full(30, np.nan),
    }

    assert {status: metrics_for(values)["status"] for status, values in shapes.items()} == {status: status for status in shapes}
