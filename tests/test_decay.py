import math

import pandas as pd
import pytest

from fashion_trends.metrics.decay import (
    DECAY_RATE_COLUMNS,
    PCT_DROPPED_COLUMNS,
    compute_decay_rate,
    compute_decay_rate_by_trend,
    compute_pct_dropped,
    compute_pct_dropped_by_trend,
)


def _dates(n, start="2026-01-04"):
    return pd.date_range(start, periods=n, freq="W-SUN")


def _processed(values, start="2026-01-04"):
    return pd.DataFrame({"interest_raw": values}, index=_dates(len(values), start=start))


# ---- the headline calculation ----------------------------------------------------


def test_pct_dropped_uses_the_mean_of_the_trailing_window_not_the_last_week_alone():
    # Last 4 raw weeks are 40, 30, 20, 10 -> mean 25. Off a peak of 100 that is
    # a 75% drop, hand-computable without touching the earlier, irrelevant
    # weeks of the series.
    values = [100, 90, 80, 70, 60, 50, 40, 30, 20, 10]
    result = compute_pct_dropped(_processed(values), peak_value=100.0, pre_peak=False, smoothing_window=4)

    assert result.current_value == 25.0
    assert result.pct_dropped == 75.0
    assert result.current_window_end == _dates(len(values))[-1]
    assert not result.current_above_peak


def test_pct_dropped_is_not_swung_by_a_single_noisy_trailing_week():
    # The final week alone (90) would read as only a 10% drop from a peak of
    # 100. Averaged with the three weeks before it (40, 30, 20) the trend is
    # still down 55% -- the trailing mean is what keeps the noisy last week
    # from dominating the headline number.
    values = [100, 90, 80, 70, 60, 50, 40, 30, 20, 90]
    last_week_only_pct = (100.0 - 90.0) / 100.0 * 100
    result = compute_pct_dropped(_processed(values), peak_value=100.0, pre_peak=False, smoothing_window=4)

    assert result.current_value == 45.0
    assert result.pct_dropped == pytest.approx(55.0)
    assert result.pct_dropped != last_week_only_pct


def test_pct_dropped_skips_gap_weeks_rather_than_counting_them_as_zero():
    # A gap (NaN) week sits inside the trailing window. It must be skipped,
    # not averaged in as a zero -- a hole in the data is not evidence of a
    # bigger drop than actually happened.
    values = [100, 90, 80, 70, float("nan"), 60, 50, 40]
    result = compute_pct_dropped(_processed(values), peak_value=100.0, pre_peak=False, smoothing_window=4)

    # Last 4 non-null raw weeks: 70, 60, 50, 40 -> mean 55.
    assert result.current_value == 55.0
    assert result.pct_dropped == 45.0


def test_pct_dropped_averages_however_many_weeks_are_available_below_the_window():
    # Only 2 raw weeks exist -- fewer than the 4-week window -- so both get
    # averaged rather than the call failing or padding with nothing.
    values = [100, 40, 20]
    result = compute_pct_dropped(_processed(values[1:]), peak_value=100.0, pre_peak=False, smoothing_window=4)

    assert result.current_value == 30.0
    assert result.pct_dropped == 70.0


# ---- clamping a misdetected peak ----------------------------------------------------


def test_a_current_level_above_the_peak_is_clamped_to_zero_and_flagged():
    # The trailing mean (80) exceeds the supplied peak (50) -- the peak was
    # found in the wrong place. The clamp keeps the headline number sane
    # while the flag keeps that fact visible rather than silently hidden.
    values = [50, 60, 70, 80, 90, 80]
    result = compute_pct_dropped(_processed(values), peak_value=50.0, pre_peak=False, smoothing_window=4)

    assert result.pct_dropped == 0.0
    assert result.current_above_peak
    assert result.current_value == 80.0


def test_a_current_level_at_or_below_the_peak_is_not_flagged():
    result = compute_pct_dropped(
        _processed([100, 80, 60, 40, 20]), peak_value=100.0, pre_peak=False, smoothing_window=4
    )

    assert not result.current_above_peak


# ---- null cases ----------------------------------------------------


def test_pct_dropped_is_null_for_a_pre_peak_trend():
    result = compute_pct_dropped(
        _processed([10, 20, 30, 40]), peak_value=40.0, pre_peak=True, smoothing_window=4
    )

    assert result.pct_dropped is None
    assert result.current_value is None
    assert result.current_window_end is None
    assert not result.current_above_peak


def test_pct_dropped_is_null_when_no_peak_was_found():
    result = compute_pct_dropped(_processed([10, 20]), peak_value=None, pre_peak=False, smoothing_window=4)

    assert result.pct_dropped is None


def test_pct_dropped_is_null_when_there_are_no_raw_observations():
    values = [float("nan")] * 4
    result = compute_pct_dropped(_processed(values), peak_value=40.0, pre_peak=False, smoothing_window=4)

    assert result.pct_dropped is None
    assert result.current_value is None


def test_a_zero_peak_yields_a_current_value_but_no_percentage():
    # Nothing was ever measurably above zero -- there is no drop to express
    # as a fraction of it, but the trailing mean is still worth recording.
    result = compute_pct_dropped(_processed([0, 0, 0, 0]), peak_value=0.0, pre_peak=False, smoothing_window=4)

    assert result.pct_dropped is None
    assert result.current_value == 0.0
    assert result.current_window_end is not None


# ---- compute_pct_dropped_by_trend ----------------------------------------------------


def _series_rows(trend_id, values, start="2026-01-04"):
    return pd.DataFrame(
        {"date": _dates(len(values), start=start), "trend_id": trend_id, "interest_raw": values}
    )


def _peak_row(trend_id, peak_value, pre_peak):
    return {"trend_id": trend_id, "peak_value": peak_value, "pre_peak": pre_peak}


def test_compute_pct_dropped_by_trend_returns_one_row_per_trend():
    series = pd.concat(
        [
            _series_rows("mob", [100, 80, 60, 40, 20]),
            _series_rows("demure", [10, 20, 30, 40, 50]),
        ],
        ignore_index=True,
    )
    peaks = pd.DataFrame(
        [_peak_row("mob", 100.0, False), _peak_row("demure", 50.0, True)]
    )

    result = compute_pct_dropped_by_trend(series, peaks, smoothing_window=4)

    assert list(result.columns) == ["trend_id", *PCT_DROPPED_COLUMNS]
    assert set(result["trend_id"]) == {"mob", "demure"}
    by_id = result.set_index("trend_id")
    assert by_id.loc["mob", "pct_dropped"] == pytest.approx(50.0)
    assert pd.isna(by_id.loc["demure", "pct_dropped"])


def test_compute_pct_dropped_by_trend_types_columns_even_when_every_result_is_null():
    series = _series_rows("mob", [float("nan")] * 3)
    peaks = pd.DataFrame([_peak_row("mob", None, False)])

    result = compute_pct_dropped_by_trend(series, peaks, smoothing_window=4)

    assert result["pct_dropped"].dtype == "float64"
    assert result["current_window_end"].dtype == "datetime64[ns]"
    assert result["current_above_peak"].dtype == "bool"
    assert result["pct_dropped"].isna().all()


# ---- decay rate: the linear reading ----------------------------------------------------


def _smoothed(values, start="2026-01-04"):
    return pd.DataFrame({"interest_smooth": values}, index=_dates(len(values), start=start))


def _decay_rate(processed, weeks_since_peak, pct_dropped, pre_peak=False, min_fit_weeks=8):
    return compute_decay_rate(
        processed, processed.index[0], weeks_since_peak, pct_dropped, pre_peak, min_fit_weeks
    )


def _exponential(peak, k, weeks):
    return [peak * math.exp(-k * week) for week in range(weeks)]


def test_decay_rate_linear_spreads_the_drop_over_the_weeks_since_the_peak():
    # 80% lost over 20 weeks is 4 percentage points of the peak per week.
    result = _decay_rate(_smoothed([100.0] * 21), weeks_since_peak=20, pct_dropped=80.0)

    assert result.decay_rate_linear == pytest.approx(4.0)


def test_two_trends_with_the_same_drop_but_different_speeds_get_different_rates():
    # The whole reason this metric exists: an identical "% dropped" reached
    # over 8 weeks and over 104 weeks are not the same story.
    fast = _decay_rate(_smoothed([100.0] * 9), weeks_since_peak=8, pct_dropped=60.0)
    slow = _decay_rate(_smoothed([100.0] * 105), weeks_since_peak=104, pct_dropped=60.0)

    assert fast.decay_rate_linear > slow.decay_rate_linear
    assert fast.decay_rate_linear == pytest.approx(7.5)
    assert slow.decay_rate_linear == pytest.approx(60.0 / 104)


# ---- decay rate: the exponential fit ----------------------------------------------------


def test_the_fit_recovers_the_constant_of_a_known_exponential_decay():
    # A textbook exponential decay: the fit must return the k it was built
    # with, and an R^2 of 1 for a curve that is exactly exponential.
    values = _exponential(peak=100.0, k=0.12, weeks=30)
    result = _decay_rate(_smoothed(values), weeks_since_peak=29, pct_dropped=90.0)

    assert result.decay_rate_exp == pytest.approx(0.12, abs=1e-9)
    assert result.decay_fit_r2 == pytest.approx(1.0)
    assert result.decay_fit_weeks == 30


def test_a_trend_that_dropped_then_plateaued_fits_badly_and_says_so():
    # A cliff followed by a flat line is not an exponential. The fit still
    # returns a constant -- the R^2 is what tells the reader not to trust a
    # single decay number for this shape.
    cliff_then_flat = [100.0, 40.0] + [38.0] * 18
    plateaued = _decay_rate(_smoothed(cliff_then_flat), weeks_since_peak=19, pct_dropped=62.0)
    clean = _decay_rate(
        _smoothed(_exponential(peak=100.0, k=0.12, weeks=20)), weeks_since_peak=19, pct_dropped=90.0
    )

    assert plateaued.decay_fit_r2 < 0.6
    assert clean.decay_fit_r2 > plateaued.decay_fit_r2


def test_the_fit_ignores_gap_and_zero_weeks_without_shifting_the_weeks_after_them():
    # A gap week and a week at zero cannot be logged, so they drop out of the
    # fit -- but the weeks after them keep their real distance from the peak,
    # so the recovered constant is unchanged.
    values = _exponential(peak=100.0, k=0.1, weeks=20)
    values[5] = float("nan")
    values[9] = 0.0
    result = _decay_rate(_smoothed(values), weeks_since_peak=19, pct_dropped=85.0)

    assert result.decay_rate_exp == pytest.approx(0.1, abs=1e-9)
    assert result.decay_fit_weeks == 18


def test_a_post_peak_segment_shorter_than_the_minimum_is_not_fitted():
    # Six weeks of decline cannot support a decay constant that would be
    # extrapolated over years -- null is the honest answer, though the linear
    # reading still stands.
    result = _decay_rate(
        _smoothed(_exponential(peak=100.0, k=0.2, weeks=6)), weeks_since_peak=5, pct_dropped=60.0
    )

    assert result.decay_rate_exp is None
    assert result.decay_fit_r2 is None
    assert result.decay_fit_weeks is None
    assert result.decay_rate_linear == pytest.approx(12.0)


def test_a_flat_post_peak_segment_fits_a_zero_decay_constant_exactly():
    # No variance for the fit to explain, and nothing left unexplained: a
    # trend that has not moved decays at 0 per week, and that constant
    # describes it perfectly.
    result = _decay_rate(_smoothed([50.0] * 12), weeks_since_peak=11, pct_dropped=0.0)

    assert result.decay_rate_exp == pytest.approx(0.0, abs=1e-12)
    assert result.decay_fit_r2 == 1.0


def test_the_fit_starts_at_the_peak_week_not_at_the_start_of_the_series():
    # The weeks before the peak are a rise, not a decay. Including them would
    # flatten the fitted constant, so the fit must ignore them entirely.
    rise = [10.0, 30.0, 60.0]
    decay = _exponential(peak=100.0, k=0.15, weeks=20)
    processed = _smoothed(rise + decay)
    peak_date = processed.index[len(rise)]

    result = compute_decay_rate(processed, peak_date, 19, 90.0, False, 8)

    assert result.decay_rate_exp == pytest.approx(0.15, abs=1e-9)
    assert result.decay_fit_weeks == 20


# ---- decay rate: null cases ----------------------------------------------------


def test_decay_rate_is_null_for_a_pre_peak_trend():
    result = _decay_rate(
        _smoothed([10.0, 20.0, 30.0] * 4), weeks_since_peak=0, pct_dropped=None, pre_peak=True
    )

    assert result.decay_rate_linear is None
    assert result.decay_rate_exp is None
    assert result.decay_fit_r2 is None


def test_decay_rate_linear_is_null_when_the_peak_is_the_most_recent_week():
    # Nothing to divide by: no time has passed for the drop to spread over.
    # The exponential fit has no post-peak segment to work with either.
    processed = _smoothed([100.0] * 12)
    result = compute_decay_rate(processed, processed.index[-1], 0, 0.0, False, 8)

    assert result.decay_rate_linear is None
    assert result.decay_rate_exp is None


def test_decay_rate_linear_is_null_when_pct_dropped_is():
    # No peak was found, or the peak was zero -- either way there is no drop
    # to spread over the weeks. The fit is independent and still runs.
    result = _decay_rate(
        _smoothed(_exponential(peak=100.0, k=0.1, weeks=20)), weeks_since_peak=19, pct_dropped=None
    )

    assert result.decay_rate_linear is None
    assert result.decay_rate_exp == pytest.approx(0.1, abs=1e-9)


def test_decay_rate_is_null_when_no_peak_date_was_found():
    result = compute_decay_rate(_smoothed([float("nan")] * 12), None, None, None, False, 8)

    assert result.decay_rate_linear is None
    assert result.decay_rate_exp is None


# ---- compute_decay_rate_by_trend ----------------------------------------------------


def _smoothed_series_rows(trend_id, values, start="2026-01-04"):
    return pd.DataFrame(
        {"date": _dates(len(values), start=start), "trend_id": trend_id, "interest_smooth": values}
    )


def _decay_peak_row(trend_id, peak_date, weeks_since_peak, pre_peak):
    return {
        "trend_id": trend_id,
        "peak_date": peak_date,
        "weeks_since_peak": weeks_since_peak,
        "pre_peak": pre_peak,
    }


def test_compute_decay_rate_by_trend_returns_one_row_per_trend():
    fading = _exponential(peak=100.0, k=0.1, weeks=20)
    rising = [float(week) for week in range(1, 21)]
    series = pd.concat(
        [_smoothed_series_rows("mob", fading), _smoothed_series_rows("demure", rising)],
        ignore_index=True,
    )
    dates = _dates(20)
    peaks = pd.DataFrame(
        [
            _decay_peak_row("mob", dates[0], 19, False),
            _decay_peak_row("demure", dates[-1], 0, True),
        ]
    )
    pct_dropped = pd.DataFrame(
        [{"trend_id": "mob", "pct_dropped": 85.0}, {"trend_id": "demure", "pct_dropped": None}]
    )

    result = compute_decay_rate_by_trend(series, peaks, pct_dropped, min_fit_weeks=8)

    assert list(result.columns) == ["trend_id", *DECAY_RATE_COLUMNS]
    by_id = result.set_index("trend_id")
    assert by_id.loc["mob", "decay_rate_exp"] == pytest.approx(0.1, abs=1e-9)
    assert by_id.loc["mob", "decay_rate_linear"] == pytest.approx(85.0 / 19)
    assert pd.isna(by_id.loc["demure", "decay_rate_linear"])
    assert pd.isna(by_id.loc["demure", "decay_rate_exp"])


def test_compute_decay_rate_by_trend_types_columns_even_when_every_result_is_null():
    series = _smoothed_series_rows("mob", [float("nan")] * 3)
    peaks = pd.DataFrame([_decay_peak_row("mob", None, None, False)])
    pct_dropped = pd.DataFrame([{"trend_id": "mob", "pct_dropped": None}])

    result = compute_decay_rate_by_trend(series, peaks, pct_dropped, min_fit_weeks=8)

    assert result["decay_rate_linear"].dtype == "float64"
    assert result["decay_fit_r2"].dtype == "float64"
    assert result["decay_fit_weeks"].dtype == "Int64"
    assert result["decay_rate_exp"].isna().all()
