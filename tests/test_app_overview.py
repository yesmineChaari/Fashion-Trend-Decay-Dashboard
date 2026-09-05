import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pytest

from fashion_trends import metrics as metrics_module
from fashion_trends.app.overview import (
    ALL_CATEGORIES,
    ALL_STATUSES,
    JUST_PEAKED,
    NEVER_HALVED,
    NO_PEAK_DETECTED,
    OVERVIEW_COLUMNS,
    STILL_RISING,
    filter_metrics,
    format_overview_table,
    summary_tiles,
)
from fashion_trends.keywords import Trend
from fashion_trends.metrics import compute_all
from fashion_trends.settings import Settings

# ---- fixtures reused from the rankings suite's shape --------------------


def _trend(id_, keyword, category="aesthetic"):
    return Trend(id=id_, keyword=keyword, display_name=keyword.title(), category=category, notes="t")


def _dates(n, start="2020-01-05"):
    return pd.date_range(start, periods=n, freq="W-SUN")


def _series_rows(trend_id, keyword, display_name, category, raw, start="2020-01-05"):
    return pd.DataFrame(
        {
            "date": _dates(len(raw), start=start),
            "trend_id": trend_id,
            "keyword": keyword,
            "display_name": display_name,
            "category": category,
            "interest_raw": raw,
            "interest_smooth": raw,
            "low_resolution": False,
        }
    )


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


@pytest.fixture
def catalog(monkeypatch):
    trends = [
        _trend("fast", "fast trend", category="aesthetic"),
        _trend("slow", "slow trend", category="garment"),
        _trend("rising", "rising trend", category="accessory"),
        _trend("unknown", "unknown trend", category="styling"),
    ]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)
    return trends


@pytest.fixture
def metrics(catalog):
    series = pd.concat(
        [
            _series_rows("fast", "fast trend", "Fast Trend", "aesthetic", _fast_collapse_values()),
            _series_rows("slow", "slow trend", "Slow Trend", "garment", _slow_fade_values()),
            _series_rows("rising", "rising trend", "Rising Trend", "accessory", _still_rising_values()),
            _series_rows("unknown", "unknown trend", "Unknown Trend", "styling", [float("nan")] * 10),
        ],
        ignore_index=True,
    )
    return compute_all(series, Settings())


# ---- filter_metrics ----------------------------------------------------


def test_filter_metrics_returns_everything_with_both_sentinels(metrics):
    filtered = filter_metrics(metrics, ALL_CATEGORIES, ALL_STATUSES)

    assert len(filtered) == len(metrics)


def test_filter_metrics_by_category_only(metrics):
    filtered = filter_metrics(metrics, "garment", ALL_STATUSES)

    assert set(filtered["trend_id"]) == {"slow"}


def test_filter_metrics_by_status_only(metrics):
    filtered = filter_metrics(metrics, ALL_CATEGORIES, "pre_peak")

    assert set(filtered["trend_id"]) == {"rising"}


def test_filter_metrics_composes_category_and_status(metrics):
    filtered = filter_metrics(metrics, "aesthetic", "collapsed")

    assert set(filtered["trend_id"]) == {"fast"}


def test_filter_metrics_empty_when_nothing_matches(metrics):
    filtered = filter_metrics(metrics, "garment", "pre_peak")

    assert filtered.empty


# ---- summary_tiles ----------------------------------------------------


def test_summary_tiles_median_pct_dropped_excludes_null_rows(metrics):
    tiles = summary_tiles(metrics)

    pct_dropped = metrics["pct_dropped"].dropna()
    assert tiles["median_pct_dropped"] == pytest.approx(pct_dropped.median())


def test_summary_tiles_median_weeks_to_half_only_counts_crossed_trends(metrics):
    tiles = summary_tiles(metrics)

    # Only "fast" crosses half its peak within the window (see test_rankings.py).
    assert tiles["median_weeks_to_half"] == metrics.loc[metrics["trend_id"] == "fast", "weeks_to_half"].iloc[0]


def test_summary_tiles_status_counts_match_value_counts(metrics):
    tiles = summary_tiles(metrics)

    assert tiles["status_counts"] == metrics["status"].value_counts().to_dict()


def test_summary_tiles_medians_are_none_when_nothing_qualifies(metrics):
    only_rising = metrics[metrics["trend_id"] == "rising"]

    tiles = summary_tiles(only_rising)

    assert tiles["median_pct_dropped"] is None
    assert tiles["median_weeks_to_half"] is None


# ---- format_overview_table ----------------------------------------------------


def test_format_overview_table_empty_input_returns_empty_frame_with_columns():
    table = format_overview_table(pd.DataFrame())

    assert table.empty
    assert list(table.columns) == list(OVERVIEW_COLUMNS)


def test_format_overview_table_labels_pre_peak_trend_as_still_rising(metrics):
    table = format_overview_table(metrics)
    row = table[metrics["trend_id"].values == "rising"].iloc[0]

    # peak_date is real even pre-peak (see fashion_trends.metrics.peaks) —
    # only the metrics measured *from* that peak are still rising.
    assert row["peak_date"] != NO_PEAK_DETECTED
    assert row["pct_dropped"] == STILL_RISING
    assert row["decay_rate_linear"] == STILL_RISING
    assert row["weeks_to_half"] == STILL_RISING


def test_format_overview_table_labels_no_peak_trend_as_no_usable_peak(metrics):
    table = format_overview_table(metrics)
    row = table[metrics["trend_id"].values == "unknown"].iloc[0]

    assert row["peak_date"] == NO_PEAK_DETECTED
    assert row["pct_dropped"] == NO_PEAK_DETECTED
    assert row["decay_rate_linear"] == NO_PEAK_DETECTED
    assert row["weeks_to_half"] == NO_PEAK_DETECTED


def test_format_overview_table_renders_real_values_for_a_crossed_trend(metrics):
    table = format_overview_table(metrics)
    row = table[metrics["trend_id"].values == "fast"].iloc[0]

    assert row["pct_dropped"].endswith("%")
    assert row["decay_rate_linear"].endswith("pts/wk")
    assert row["weeks_to_half"].endswith("wk")


def _minimal_row(**overrides):
    base = {
        "display_name": "Trend",
        "category": "aesthetic",
        "status": "declining",
        "peak_date": pd.Timestamp("2024-01-07"),
        "pre_peak": False,
        "pct_dropped": 42.0,
        "decay_rate_linear": 1.5,
        "weeks_since_peak": 4,
        "time_to_half_status": "still_above_half",
        "weeks_to_half": pd.NA,
        "low_resolution": False,
        "peak_at_boundary": False,
        "has_secondary_peak": False,
    }
    base.update(overrides)
    return pd.DataFrame([base])


def test_format_overview_table_labels_still_above_half_as_never_halved():
    table = format_overview_table(_minimal_row())

    assert table.iloc[0]["weeks_to_half"] == NEVER_HALVED


def test_format_overview_table_labels_zero_weeks_since_peak_as_just_peaked():
    table = format_overview_table(_minimal_row(decay_rate_linear=float("nan"), weeks_since_peak=0))

    assert table.iloc[0]["decay_rate_linear"] == JUST_PEAKED


def test_format_overview_table_lists_active_flags():
    table = format_overview_table(_minimal_row(peak_at_boundary=True, has_secondary_peak=True))

    flags = table.iloc[0]["flags"]
    assert "peak near window edge" in flags
    assert "secondary peak (revival)" in flags
    assert "low-resolution data" not in flags


def test_format_overview_table_empty_flags_string_when_no_caveats():
    table = format_overview_table(_minimal_row())

    assert table.iloc[0]["flags"] == ""
