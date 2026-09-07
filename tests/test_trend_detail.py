import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pytest

from fashion_trends import metrics as metrics_module
from fashion_trends.keywords import Trend
from fashion_trends.metrics import compute_all
from fashion_trends.settings import Settings
from fashion_trends.viz.decay_curves import build_decay_curve_frame
from fashion_trends.viz.trend_detail import (
    build_trend_vs_median_frame,
    plot_trend_series,
    plot_trend_vs_median,
)


def _trend(id_, keyword, category="aesthetic"):
    return Trend(id=id_, keyword=keyword, display_name=keyword.title(), category=category, notes="t")


def _dates(n, start="2020-01-05"):
    return pd.date_range(start, periods=n, freq="W-SUN")


def _series_rows(trend_id, keyword, display_name, category, values, start="2020-01-05"):
    return pd.DataFrame(
        {
            "date": _dates(len(values), start=start),
            "trend_id": trend_id,
            "keyword": keyword,
            "display_name": display_name,
            "category": category,
            "interest_raw": values,
            "interest_smooth": values,
            "low_resolution": False,
        }
    )


# Flat lead-in long enough to keep every peak away from either edge of the
# window -- see test_decay_curves.py, which uses the same pad for the same
# reason.
_LEAD_PAD = [5.0] * 6


def _fast_collapse_values():
    rise = [10.0, 40.0, 90.0]
    decay = [100.0 * (0.6**week) for week in range(1, 40)]
    return _LEAD_PAD + rise + decay


def _slow_fade_values():
    rise = [10.0, 40.0, 90.0]
    decay = [100.0 * (0.99**week) for week in range(1, 40)]
    return _LEAD_PAD + rise + decay


def _still_rising_values():
    return [10.0, 20.0, 30.0, 40.0, 55.0, 70.0, 90.0]


def _revival_values():
    # A first peak of 100, a decay well below the 0.8-of-peak secondary-peak
    # threshold, then a second hump (92/96/90) that clears it again -- a
    # revival without ever beating the first peak's height.
    rise = [10.0, 40.0, 90.0, 100.0]
    decay = [70.0, 50.0, 30.0, 20.0, 15.0]
    bump = [30.0, 55.0, 75.0, 92.0, 96.0, 90.0, 70.0]
    tail = [50.0, 30.0, 20.0, 15.0, 12.0, 10.0, 8.0, 6.0, 5.0]
    return _LEAD_PAD + rise + decay + bump + tail


@pytest.fixture
def catalog(monkeypatch):
    trends = [
        _trend("fast", "fast trend"),
        _trend("slow", "slow trend"),
        _trend("rising", "rising trend"),
        _trend("unknown", "unknown trend"),
        _trend("revival", "revival trend"),
    ]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)
    return trends


@pytest.fixture
def series(catalog):
    return pd.concat(
        [
            _series_rows("fast", "fast trend", "Fast Trend", "aesthetic", _fast_collapse_values()),
            _series_rows("slow", "slow trend", "Slow Trend", "garment", _slow_fade_values()),
            _series_rows("rising", "rising trend", "Rising Trend", "accessory", _still_rising_values()),
            _series_rows("unknown", "unknown trend", "Unknown Trend", "styling", [float("nan")] * 10),
            _series_rows("revival", "revival trend", "Revival Trend", "aesthetic", _revival_values()),
        ],
        ignore_index=True,
    )


@pytest.fixture
def metrics(series):
    return compute_all(series, Settings())


def _row(metrics, trend_id):
    return metrics.loc[metrics["trend_id"] == trend_id].iloc[0]


def _legend_labels(fig):
    return {trace.name for trace in fig.data if trace.showlegend is not False and trace.name}


def _captions(fig):
    return [annotation.text for annotation in fig.layout.annotations]


# ---- plot_trend_series ----------------------------------------------------


def test_plot_trend_series_labels_raw_smoothed_peak_and_crossing_for_a_crossed_trend(metrics, series):
    fig = plot_trend_series(series[series["trend_id"] == "fast"], _row(metrics, "fast"))

    assert _legend_labels(fig) == {"Raw interest", "Smoothed", "Peak", "Half-life crossing"}
    assert _captions(fig) == []


def test_plot_trend_series_never_crossed_shows_peak_but_no_crossing_marker(metrics, series):
    fig = plot_trend_series(series[series["trend_id"] == "slow"], _row(metrics, "slow"))

    assert _legend_labels(fig) == {"Raw interest", "Smoothed", "Peak"}
    assert any("Never fell below half its peak" in text for text in _captions(fig))


def test_plot_trend_series_pre_peak_shows_peak_but_no_threshold_or_crossing(metrics, series):
    fig = plot_trend_series(series[series["trend_id"] == "rising"], _row(metrics, "rising"))

    assert _legend_labels(fig) == {"Raw interest", "Smoothed", "Peak"}
    assert any("Still climbing" in text for text in _captions(fig))


def test_plot_trend_series_no_usable_peak_shows_no_peak_marker(metrics, series):
    fig = plot_trend_series(series[series["trend_id"] == "unknown"], _row(metrics, "unknown"))

    assert _legend_labels(fig) == {"Raw interest", "Smoothed"}
    assert any("No usable peak was detected" in text for text in _captions(fig))


def test_plot_trend_series_marks_the_secondary_peak_for_a_revival(metrics, series):
    fig = plot_trend_series(series[series["trend_id"] == "revival"], _row(metrics, "revival"))

    assert "Secondary peak (revival)" in _legend_labels(fig)


# ---- build_trend_vs_median_frame ----------------------------------------------------


def test_own_frame_is_empty_for_a_pre_peak_trend(metrics, series):
    own, _median = build_trend_vs_median_frame(series, metrics, "rising")

    assert own.empty


def test_own_frame_is_empty_when_no_peak_was_found(metrics, series):
    own, _median = build_trend_vs_median_frame(series, metrics, "unknown")

    assert own.empty


def test_own_frame_holds_the_trends_own_peak_aligned_curve(metrics, series):
    own, _median = build_trend_vs_median_frame(series, metrics, "fast")

    at_peak = own.loc[own["weeks_since_peak"] == 0, "pct_of_peak"]
    assert at_peak.iloc[0] == pytest.approx(100.0)


def test_median_excludes_the_trend_itself(metrics, series):
    frame = build_decay_curve_frame(series, metrics)
    own, median = build_trend_vs_median_frame(series, metrics, "fast")

    week5_others = frame[(frame["trend_id"] != "fast") & (frame["weeks_since_peak"] == 5)]
    expected = week5_others["pct_of_peak"].median()

    actual = median.loc[median["weeks_since_peak"] == 5, "pct_of_peak"].iloc[0]
    own_value = own.loc[own["weeks_since_peak"] == 5, "pct_of_peak"].iloc[0]

    assert actual == pytest.approx(expected)
    assert actual != pytest.approx(own_value)


# ---- plot_trend_vs_median ----------------------------------------------------


def test_plot_trend_vs_median_draws_both_lines_when_the_trend_is_eligible(metrics, series):
    fig = plot_trend_vs_median(series, metrics, "fast")

    assert _legend_labels(fig) == {"Median of all other trends", "Fast Trend"}


def test_plot_trend_vs_median_captions_a_trend_with_no_curve_of_its_own(metrics, series):
    fig = plot_trend_vs_median(series, metrics, "rising")

    assert _legend_labels(fig) == {"Median of all other trends"}
    assert any("no post-peak curve to compare yet" in text for text in _captions(fig))
