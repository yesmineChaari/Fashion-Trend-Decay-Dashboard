import pandas as pd

from fashion_trends.metrics.smoothing import (
    normalize_weekly_index,
    preprocess_series,
    smooth_series,
)


def _weekly_dates(n, start="2026-01-04"):
    return pd.date_range(start, periods=n, freq="W-SUN")


# ---- normalize_weekly_index ----------------------------------------------------


def test_normalize_weekly_index_fills_a_missing_week_with_nan():
    # Four other weekly gaps establish the true cadence so the one dropped
    # week (index 2) is recognized as a gap rather than as the series' own
    # spacing.
    dates = _weekly_dates(5).delete(2)
    series = pd.Series([10, 20, 40, 50], index=dates)

    normalized = normalize_weekly_index(series)

    assert len(normalized) == 5
    assert list(normalized.iloc[[0, 1, 3, 4]]) == [10, 20, 40, 50]
    assert pd.isna(normalized.iloc[2])


def test_normalize_weekly_index_leaves_a_complete_series_unchanged():
    dates = _weekly_dates(4)
    series = pd.Series([1, 2, 3, 4], index=dates)

    normalized = normalize_weekly_index(series)

    pd.testing.assert_index_equal(normalized.index, pd.DatetimeIndex(dates))
    assert list(normalized) == [1, 2, 3, 4]


def test_normalize_weekly_index_handles_fewer_than_two_points():
    series = pd.Series([5], index=_weekly_dates(1))

    normalized = normalize_weekly_index(series)

    assert list(normalized) == [5]


# ---- smooth_series ----------------------------------------------------


def test_smooth_series_centred_window_lags_far_less_than_a_trailing_window():
    # A realistic rise-then-decay shape. Pandas' centred window for an even
    # `window` isn't perfectly symmetric (it leans one point toward the
    # past), so it can nudge the reported peak a week late — but nowhere
    # near as far as a fully trailing window, which looks entirely backward
    # and reports the peak `window // 2`+ weeks late.
    values = [5, 12, 28, 55, 90, 60, 35, 18, 9, 5]
    series = pd.Series(values, index=_weekly_dates(len(values)))
    peak_date = series.idxmax()

    smoothed = smooth_series(series, window=4)
    trailing = series.rolling(window=4, center=False, min_periods=1).mean()

    smoothed_lag_weeks = (smoothed.idxmax() - peak_date).days // 7
    trailing_lag_weeks = (trailing.idxmax() - peak_date).days // 7

    assert 0 <= smoothed_lag_weeks <= 1
    assert trailing_lag_weeks > smoothed_lag_weeks


def test_smooth_series_handles_series_shorter_than_window_without_crashing():
    series = pd.Series([5, 15], index=_weekly_dates(2))

    smoothed = smooth_series(series, window=4)

    assert len(smoothed) == 2
    assert not smoothed.isna().any()


def test_smooth_series_window_of_one_returns_a_copy_of_the_input():
    series = pd.Series([1, 2, 3], index=_weekly_dates(3))

    smoothed = smooth_series(series, window=1)

    assert list(smoothed) == [1, 2, 3]
    assert smoothed is not series


# ---- preprocess_series ----------------------------------------------------


def test_preprocess_series_keeps_both_raw_and_smooth_columns():
    series = pd.Series([10, 20, 30, 20, 10], index=_weekly_dates(5))

    processed = preprocess_series(series, window=4)

    assert list(processed.columns) == ["interest_raw", "interest_smooth"]
    assert list(processed["interest_raw"]) == [10, 20, 30, 20, 10]
    assert not processed["interest_smooth"].isna().any()


def test_preprocess_series_reindexes_over_a_gap():
    dates = _weekly_dates(5).delete(2)
    series = pd.Series([10, 20, 40, 50], index=dates)

    processed = preprocess_series(series, window=4)

    assert len(processed) == 5
    assert pd.isna(processed["interest_raw"].iloc[2])


def test_preprocess_series_drops_the_trailing_partial_week():
    dates = _weekly_dates(3)
    series = pd.Series([10, 20, 3], index=dates)
    is_partial = pd.Series([False, False, True], index=dates)

    processed = preprocess_series(series, window=4, is_partial=is_partial)

    assert len(processed) == 2
    assert list(processed["interest_raw"]) == [10, 20]


def test_preprocess_series_handles_series_shorter_than_window_without_crashing():
    series = pd.Series([7], index=_weekly_dates(1))

    processed = preprocess_series(series, window=4)

    assert len(processed) == 1
    assert processed["interest_smooth"].iloc[0] == 7
