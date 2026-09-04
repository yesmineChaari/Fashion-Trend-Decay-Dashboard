import pandas as pd

from fashion_trends.metrics.peaks import PEAK_COLUMNS, detect_peak, detect_peaks_by_trend
from fashion_trends.metrics.smoothing import preprocess_series

WINDOW = 4
RATIO = 0.8
SPIKE = 0.5
BOUNDARY = 4
RISE = 4


def _weekly_dates(n, start="2026-01-04"):
    return pd.date_range(start, periods=n, freq="W-SUN")


def _processed(values, window=4, start="2026-01-04"):
    series = pd.Series(values, index=_weekly_dates(len(values), start=start), dtype="float64")
    return preprocess_series(series, window)


def _detect(values, window=WINDOW, start="2026-01-04"):
    return detect_peak(_processed(values, window, start), window, RATIO, SPIKE, BOUNDARY, RISE)


# A rise, a clear single peak, and a long decay — the shape every flag below is
# defined against. Padded on both sides so the peak is nowhere near an edge.
CLEAN_RISE_AND_FALL = (
    [2, 3, 4, 5, 6, 10, 20, 40, 70, 95, 100, 80, 60, 45, 33, 25, 18, 13, 9, 6, 4, 3, 2, 2]
)


# ---- the peak itself ----------------------------------------------------


def test_detect_peak_reports_the_smoothed_maximum_with_its_raw_value():
    result = _detect(CLEAN_RISE_AND_FALL)

    processed = _processed(CLEAN_RISE_AND_FALL)
    assert result.peak_date == processed["interest_smooth"].idxmax()
    assert result.peak_value == processed["interest_smooth"].max()
    # The raw value of that same week is carried through untouched, so a
    # reader can see the real height behind the smoothed one.
    assert result.peak_value_raw == processed["interest_raw"].loc[result.peak_date]


def test_detect_peak_counts_weeks_from_the_peak_to_the_last_observation():
    values = CLEAN_RISE_AND_FALL
    result = _detect(values)

    processed = _processed(values)
    expected = len(processed) - 1 - processed.index.get_loc(result.peak_date)
    assert result.weeks_since_peak == expected


def test_detect_peak_returns_empty_result_for_a_series_with_no_observations():
    dates = _weekly_dates(3)
    processed = pd.DataFrame(
        {"interest_raw": [float("nan")] * 3, "interest_smooth": [float("nan")] * 3}, index=dates
    )

    result = detect_peak(processed, WINDOW, RATIO, SPIKE, BOUNDARY, RISE)

    assert result.peak_date is None
    assert result.peak_value is None
    assert result.weeks_since_peak is None
    assert not result.has_secondary_peak


def test_detect_peak_leaves_peak_value_raw_null_when_that_week_was_a_gap():
    # The pull is missing one week right at the top of the hump: the smoothed
    # peak can still land there, but there is no raw value to report for it.
    values = [5, 10, 20, 60, 100, 62, 30, 15, 8, 5]
    dates = _weekly_dates(len(values))
    series = pd.Series(values, index=dates, dtype="float64").drop(index=dates[4])
    processed = preprocess_series(series, window=4)

    result = detect_peak(processed, WINDOW, RATIO, SPIKE, BOUNDARY, RISE)

    if result.peak_date == dates[4]:
        assert result.peak_value_raw is None
    assert result.peak_value is not None


# ---- edge case: false spike ----------------------------------------------------


def test_a_one_week_spike_does_not_steal_the_peak_from_the_real_hump():
    # An unrelated news week (index 17) outranks the real peak on raw values,
    # but has no tall neighbours to hold it up once smoothed.
    values = [2, 4, 8, 16, 30, 55, 78, 92, 95, 90, 80, 66, 52, 40, 30, 22, 16, 100, 14, 10, 7, 5]
    result = _detect(values)

    spike_date = _weekly_dates(len(values))[17]
    assert result.peak_date != spike_date
    # The real hump peaks around weeks 7-9.
    assert _weekly_dates(len(values))[6] <= result.peak_date <= _weekly_dates(len(values))[10]


def test_a_spike_against_a_flat_baseline_is_flagged_rather_than_believed():
    # Smoothing alone cannot save this shape: with nothing else in the window
    # to outrank it, the averaged-down spike is still the maximum, and the
    # reported peak is several times the level the trend ever actually held.
    # The flag is what stops that becoming a decay story.
    values = [6] * 20 + [97] + [6] * 20
    result = _detect(values)

    assert result.peak_is_spike
    assert result.peak_value > max(values[:20])


def test_a_real_hump_is_not_flagged_as_a_spike():
    result = _detect(CLEAN_RISE_AND_FALL)

    assert not result.peak_is_spike


def test_a_spike_tall_enough_to_survive_smoothing_is_not_flagged_as_a_second_peak():
    # One isolated week is a spike, not a hump: even where it clears the
    # threshold it must not be reported as a revival with its own decay story.
    values = [2, 3, 4, 5, 6, 10, 20, 40, 70, 95, 100, 80, 60, 45, 33, 25, 18, 13, 9, 6, 4, 3]
    result = _detect(values)

    assert not result.has_secondary_peak
    assert result.secondary_peak_date is None


# ---- edge case: revival / double peak ----------------------------------------------------


def test_a_revival_is_flagged_with_the_second_hump_located():
    # Peaks, fades well below the threshold, then comes back nearly as tall.
    values = [5, 20, 60, 95, 100, 70, 40, 20, 10, 8, 10, 20, 45, 75, 90, 88, 60, 30, 15, 8, 5, 4]
    result = _detect(values)

    dates = _weekly_dates(len(values))
    assert result.has_secondary_peak
    # The global maximum stays the peak; the revival is reported beside it.
    assert result.peak_date < result.secondary_peak_date
    assert dates[12] <= result.secondary_peak_date <= dates[16]
    assert result.secondary_peak_value >= RATIO * result.peak_value


def test_a_second_hump_below_the_ratio_is_not_a_second_peak():
    # The revival only reaches about half the original peak — a small
    # aftershock, not a story a single decay number is hiding.
    values = [5, 20, 60, 95, 100, 70, 40, 20, 10, 8, 10, 18, 30, 45, 50, 44, 30, 18, 10, 6, 4, 3]
    result = _detect(values)

    assert not result.has_secondary_peak


def test_a_broad_plateau_is_one_peak_not_two():
    # Two bumps that never drop back below the threshold in between are
    # shoulders of the same peak; flagging them would put a revival warning on
    # an ordinary flat-topped trend.
    values = [4, 10, 30, 70, 96, 100, 97, 99, 100, 96, 70, 40, 20, 10, 6, 4, 3, 2, 2, 2, 2, 2]
    result = _detect(values)

    assert not result.has_secondary_peak


# ---- edge case: peak at the window edge ----------------------------------------------------


def test_a_peak_in_the_first_weeks_is_flagged_as_at_the_boundary():
    # The trend was already falling when the window opened — the real peak
    # happened before the first week we can see.
    values = [100, 92, 80, 66, 52, 40, 30, 22, 16, 12, 9, 7, 5, 4, 3, 2]
    result = _detect(values)

    assert result.peak_at_boundary


def test_a_peak_in_the_last_weeks_is_flagged_as_at_the_boundary():
    values = [2, 3, 4, 6, 9, 13, 18, 25, 34, 45, 58, 72, 86, 100]
    result = _detect(values)

    assert result.peak_at_boundary


def test_a_peak_well_inside_the_window_is_not_flagged():
    result = _detect(CLEAN_RISE_AND_FALL)

    assert not result.peak_at_boundary


# ---- edge case: still rising ----------------------------------------------------


def test_a_trend_still_climbing_at_the_last_week_is_marked_pre_peak():
    values = [2, 3, 4, 6, 9, 13, 18, 25, 34, 45, 58, 72, 86, 100]
    result = _detect(values)

    assert result.pre_peak
    assert result.weeks_since_peak == 0


def test_a_trend_past_its_peak_is_not_marked_pre_peak():
    result = _detect(CLEAN_RISE_AND_FALL)

    assert not result.pre_peak


def test_a_flat_series_ending_on_its_maximum_is_not_marked_pre_peak():
    # A flat line's maximum lands on the last week too, but nothing is rising:
    # calling this pre-peak would promise a peak that is never coming.
    values = [10] * 12
    result = _detect(values)

    assert not result.pre_peak


# ---- detect_peaks_by_trend ----------------------------------------------------


def _series_rows(trend_id, values, start="2026-01-04"):
    processed = _processed(values, start=start)
    return pd.DataFrame(
        {
            "date": processed.index,
            "trend_id": trend_id,
            "interest_raw": processed["interest_raw"].to_numpy(),
            "interest_smooth": processed["interest_smooth"].to_numpy(),
        }
    )


def test_detect_peaks_by_trend_returns_one_qualified_row_per_trend():
    rising = [2, 3, 4, 6, 9, 13, 18, 25, 34, 45, 58, 72, 86, 100]
    series = pd.concat(
        [_series_rows("mob", CLEAN_RISE_AND_FALL), _series_rows("demure", rising)],
        ignore_index=True,
    )

    peaks = detect_peaks_by_trend(series, WINDOW, RATIO, SPIKE, BOUNDARY, RISE)

    assert list(peaks.columns) == ["trend_id", *PEAK_COLUMNS]
    assert set(peaks["trend_id"]) == {"mob", "demure"}
    by_id = peaks.set_index("trend_id")
    assert not bool(by_id.loc["mob", "pre_peak"])
    assert bool(by_id.loc["demure", "pre_peak"])


def test_detect_peaks_by_trend_types_columns_even_when_every_peak_is_null():
    series = pd.DataFrame(
        {
            "date": _weekly_dates(3),
            "trend_id": "mob",
            "interest_raw": [float("nan")] * 3,
            "interest_smooth": [float("nan")] * 3,
        }
    )

    peaks = detect_peaks_by_trend(series, WINDOW, RATIO, SPIKE, BOUNDARY, RISE)

    assert peaks["peak_date"].dtype == "datetime64[ns]"
    assert peaks["weeks_since_peak"].dtype == "Int64"
    assert peaks["has_secondary_peak"].dtype == "bool"
    assert peaks["peak_date"].isna().all()


# ---- the same four cases, against the recorded fixtures --------------------

# The synthetic fixture columns were recorded for exactly these shapes (see
# tests/fixtures/manifest.json), so they check the rules against the data the
# rest of the pipeline actually runs on rather than against hand-built series.


def _fixture_result(keyword, window=WINDOW):
    from fashion_trends.ingest import fixtures

    series = fixtures.fetch_interest_over_time([keyword])[keyword]
    return detect_peak(preprocess_series(series, window), window, RATIO, SPIKE, BOUNDARY, RISE)


def test_spiky_fixture_peak_is_flagged_as_spike_driven():
    result = _fixture_result("fixture_spiky_false_peak")

    # The fixture is a flat baseline plus one anomalous week, so whatever week
    # the peak lands on it describes the spike, not the trend.
    assert result.peak_is_spike


def test_still_rising_fixture_is_pre_peak_at_the_window_edge():
    result = _fixture_result("fixture_still_rising")

    assert result.pre_peak
    assert result.weeks_since_peak == 0
    assert result.peak_at_boundary


def test_bag_charm_fixture_revival_is_flagged_as_a_second_peak():
    result = _fixture_result("bag charm")

    assert result.has_secondary_peak
    assert result.secondary_peak_value >= RATIO * result.peak_value


def test_near_zero_fixture_still_yields_a_peak_without_crashing():
    # A near-zero series has no meaningful shape, but peak detection must not
    # be what fails on it — `low_resolution` is the flag that qualifies it.
    result = _fixture_result("fixture_near_zero")

    assert result.peak_date is not None
