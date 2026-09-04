import pandas as pd
import pytest

from fashion_trends.metrics.decay import (
    PCT_DROPPED_COLUMNS,
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
