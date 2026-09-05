import pandas as pd
import pytest

from fashion_trends.metrics.status import (
    STATUS_COLLAPSED,
    STATUS_COLUMNS,
    STATUS_DECLINING,
    STATUS_PRE_PEAK,
    STATUS_REVIVED,
    STATUS_STABILIZED,
    STATUS_UNKNOWN,
    classify_status,
    compute_status_by_trend,
)

COLLAPSED_THRESHOLD = 70.0
STABILIZED_WINDOW = 26
FLAT_TOLERANCE = 0.15
MIN_RETAINED_PCT = 40.0


def _dates(n, start="2026-01-04"):
    return pd.date_range(start, periods=n, freq="W-SUN")


def _smoothed(values, start="2026-01-04"):
    return pd.DataFrame({"interest_smooth": values}, index=_dates(len(values), start=start))


def _classify(
    values,
    pre_peak=False,
    has_secondary_peak=False,
    weeks_since_peak=0,
    pct_dropped=None,
    collapsed_threshold=COLLAPSED_THRESHOLD,
    stabilized_window=STABILIZED_WINDOW,
    flat_tolerance=FLAT_TOLERANCE,
    min_retained_pct=MIN_RETAINED_PCT,
):
    return classify_status(
        _smoothed(values),
        pre_peak,
        has_secondary_peak,
        weeks_since_peak,
        pct_dropped,
        collapsed_threshold,
        stabilized_window,
        flat_tolerance,
        min_retained_pct,
    )


# ---- unknown: no peak found at all ----------------------------------------------------


def test_status_is_unknown_when_no_peak_was_found():
    result = _classify([float("nan")] * 4, weeks_since_peak=None)

    assert result.status == STATUS_UNKNOWN


def test_unknown_takes_precedence_over_every_other_flag():
    # Nonsensical combination on purpose: even a trend flagged pre_peak and
    # revived is reported as unknown once there is no peak to hang either
    # label on.
    result = _classify([100.0] * 30, pre_peak=True, has_secondary_peak=True, weeks_since_peak=None, pct_dropped=90.0)

    assert result.status == STATUS_UNKNOWN


# ---- pre_peak ----------------------------------------------------


def test_status_is_pre_peak_when_still_climbing():
    result = _classify([10.0, 20.0, 30.0], pre_peak=True, weeks_since_peak=0)

    assert result.status == STATUS_PRE_PEAK


def test_pre_peak_takes_precedence_over_revived_and_collapsed():
    result = _classify([100.0] * 30, pre_peak=True, has_secondary_peak=True, weeks_since_peak=0, pct_dropped=90.0)

    assert result.status == STATUS_PRE_PEAK


# ---- revived ----------------------------------------------------


def test_status_is_revived_when_a_secondary_peak_was_flagged():
    result = _classify([100.0] * 10, has_secondary_peak=True, weeks_since_peak=9, pct_dropped=20.0)

    assert result.status == STATUS_REVIVED


def test_revived_takes_precedence_over_collapsed():
    # Down 90% from peak *and* flagged as having come back -- the comeback is
    # the more informative story.
    result = _classify([100.0] * 10, has_secondary_peak=True, weeks_since_peak=9, pct_dropped=90.0)

    assert result.status == STATUS_REVIVED


def test_revived_takes_precedence_over_stabilized():
    flat = [50.0] * STABILIZED_WINDOW
    result = _classify(flat, has_secondary_peak=True, weeks_since_peak=STABILIZED_WINDOW, pct_dropped=10.0)

    assert result.status == STATUS_REVIVED


# ---- collapsed ----------------------------------------------------


def test_status_is_collapsed_at_the_configured_threshold():
    result = _classify([100.0] * 10, weeks_since_peak=9, pct_dropped=70.0)

    assert result.status == STATUS_COLLAPSED


def test_status_is_not_collapsed_just_under_the_threshold():
    result = _classify([100.0] * 10, weeks_since_peak=9, pct_dropped=69.9)

    assert result.status != STATUS_COLLAPSED


def test_collapsed_takes_precedence_over_stabilized_even_when_flat():
    # Faded almost to nothing and then went flat at that residual floor --
    # still a collapse, not a plateau worth calling a wardrobe staple.
    flat_near_zero = [100.0] + [5.0] * STABILIZED_WINDOW
    result = _classify(flat_near_zero, weeks_since_peak=STABILIZED_WINDOW, pct_dropped=95.0)

    assert result.status == STATUS_COLLAPSED


# ---- stabilized ----------------------------------------------------


def test_status_is_stabilized_when_flat_and_retained_enough_of_peak():
    flat = [60.0] * STABILIZED_WINDOW
    result = _classify(flat, weeks_since_peak=STABILIZED_WINDOW, pct_dropped=40.0)

    assert result.status == STATUS_STABILIZED


def test_stabilized_requires_the_full_window_to_have_elapsed_since_peak():
    # Only just peaked -- one week short of the required window -- so this
    # cannot yet read its own peak plateau as stability.
    flat = [60.0] * STABILIZED_WINDOW
    result = _classify(flat, weeks_since_peak=STABILIZED_WINDOW - 1, pct_dropped=40.0)

    assert result.status == STATUS_DECLINING


def test_stabilized_requires_retaining_a_meaningful_share_of_peak():
    # Flat, but the retained share (100 - 65 = 35) falls short of the
    # configured minimum (40) -- flat *and* faded away is still a fade.
    flat = [35.0] * STABILIZED_WINDOW
    result = _classify(flat, weeks_since_peak=STABILIZED_WINDOW, pct_dropped=65.0)

    assert result.status == STATUS_DECLINING


def test_stabilized_requires_actual_flatness_not_just_low_pct_dropped():
    still_moving = [90.0 - 3.0 * week for week in range(STABILIZED_WINDOW)]
    result = _classify(still_moving, weeks_since_peak=STABILIZED_WINDOW, pct_dropped=20.0)

    assert result.status == STATUS_DECLINING


def test_stabilized_requires_a_full_window_of_real_observations():
    # A gap inside the trailing window means there isn't enough evidence of a
    # plateau, even though the values present are all identical.
    with_gap = [60.0] * STABILIZED_WINDOW
    with_gap[3] = float("nan")
    result = _classify(with_gap, weeks_since_peak=STABILIZED_WINDOW, pct_dropped=40.0)

    assert result.status == STATUS_DECLINING


def test_flatness_is_relative_to_the_windows_own_mean():
    # A small residual trend moving by a couple of points is proportionally
    # far from flat; the same absolute range on a much larger plateau is well
    # within tolerance.
    pattern = [5.0, 4.0, 6.0, 5.0]
    small_and_noisy = [pattern[i % 4] for i in range(STABILIZED_WINDOW)]
    large_pattern = [500.0, 499.0, 501.0, 500.0]
    large_and_steady = [large_pattern[i % 4] for i in range(STABILIZED_WINDOW)]

    small_result = _classify(small_and_noisy, weeks_since_peak=STABILIZED_WINDOW, pct_dropped=40.0)
    large_result = _classify(large_and_steady, weeks_since_peak=STABILIZED_WINDOW, pct_dropped=40.0)

    assert small_result.status == STATUS_DECLINING
    assert large_result.status == STATUS_STABILIZED


# ---- declining: the default ----------------------------------------------------


def test_declining_is_the_default_for_a_falling_post_peak_trend():
    falling = [100.0, 90.0, 80.0, 70.0, 60.0]
    result = _classify(falling, weeks_since_peak=4, pct_dropped=40.0)

    assert result.status == STATUS_DECLINING


def test_declining_is_the_result_when_nothing_else_matched():
    # Post-peak, not revived, well under the collapse threshold, and not
    # flat long enough to qualify as stabilized.
    result = _classify([100.0, 95.0, 92.0], weeks_since_peak=2, pct_dropped=8.0)

    assert result.status == STATUS_DECLINING


# ---- every trend gets exactly one status ----------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(pre_peak=True, weeks_since_peak=0),
        dict(has_secondary_peak=True, weeks_since_peak=10, pct_dropped=20.0),
        dict(weeks_since_peak=10, pct_dropped=80.0),
        dict(weeks_since_peak=STABILIZED_WINDOW, pct_dropped=30.0),
        dict(weeks_since_peak=5, pct_dropped=10.0),
        dict(weeks_since_peak=None),
    ],
)
def test_every_case_returns_exactly_one_of_the_named_statuses(kwargs):
    values = kwargs.pop("_values", [60.0] * STABILIZED_WINDOW)
    result = _classify(values, **kwargs)

    assert result.status in {
        STATUS_UNKNOWN,
        STATUS_PRE_PEAK,
        STATUS_REVIVED,
        STATUS_COLLAPSED,
        STATUS_STABILIZED,
        STATUS_DECLINING,
    }


# ---- compute_status_by_trend ----------------------------------------------------


def _smoothed_series_rows(trend_id, values, start="2026-01-04"):
    return pd.DataFrame({"date": _dates(len(values), start=start), "trend_id": trend_id, "interest_smooth": values})


def _peak_row(trend_id, pre_peak=False, has_secondary_peak=False, weeks_since_peak=0):
    return {
        "trend_id": trend_id,
        "pre_peak": pre_peak,
        "has_secondary_peak": has_secondary_peak,
        "weeks_since_peak": weeks_since_peak,
    }


def test_compute_status_by_trend_returns_one_row_per_trend():
    falling = [100.0, 90.0, 80.0, 70.0, 60.0]
    flat = [60.0] * STABILIZED_WINDOW
    series = pd.concat(
        [_smoothed_series_rows("mob", falling), _smoothed_series_rows("demure", flat)],
        ignore_index=True,
    )
    peaks = pd.DataFrame(
        [
            _peak_row("mob", weeks_since_peak=4),
            _peak_row("demure", weeks_since_peak=STABILIZED_WINDOW),
        ]
    )
    pct_dropped = pd.DataFrame([{"trend_id": "mob", "pct_dropped": 40.0}, {"trend_id": "demure", "pct_dropped": 40.0}])

    result = compute_status_by_trend(
        series, peaks, pct_dropped, COLLAPSED_THRESHOLD, STABILIZED_WINDOW, FLAT_TOLERANCE, MIN_RETAINED_PCT
    )

    assert list(result.columns) == ["trend_id", *STATUS_COLUMNS]
    by_id = result.set_index("trend_id")
    assert by_id.loc["mob", "status"] == STATUS_DECLINING
    assert by_id.loc["demure", "status"] == STATUS_STABILIZED


def test_compute_status_by_trend_types_the_column_even_when_unknown():
    series = _smoothed_series_rows("mob", [float("nan")] * 3)
    peaks = pd.DataFrame([_peak_row("mob", weeks_since_peak=None)])
    pct_dropped = pd.DataFrame([{"trend_id": "mob", "pct_dropped": None}])

    result = compute_status_by_trend(
        series, peaks, pct_dropped, COLLAPSED_THRESHOLD, STABILIZED_WINDOW, FLAT_TOLERANCE, MIN_RETAINED_PCT
    )

    assert result["status"].dtype == "string"
    assert result["status"].iloc[0] == STATUS_UNKNOWN
