import pandas as pd
import pytest

from fashion_trends import metrics as metrics_module
from fashion_trends.app import trend_detail as trend_detail_module
from fashion_trends.app.overview import JUST_PEAKED, NEVER_HALVED, NO_PEAK_DETECTED, STILL_RISING
from fashion_trends.app.trend_detail import NO_NOTES, catalog_notes, metric_cards
from fashion_trends.keywords import Trend
from fashion_trends.metrics import compute_all
from fashion_trends.settings import Settings

# ---- fixtures reused from the overview suite's shape --------------------


def _trend(id_, keyword, category="aesthetic", notes="curation note"):
    return Trend(id=id_, keyword=keyword, display_name=keyword.title(), category=category, notes=notes)


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


def _still_rising_values():
    return [10.0, 20.0, 30.0, 40.0, 55.0, 70.0, 90.0]


@pytest.fixture
def catalog(monkeypatch):
    trends = [
        _trend("fast", "fast trend", notes="Picked as a fast-collapse example."),
        _trend("rising", "rising trend", notes=""),
        _trend("unknown", "unknown trend", notes="t"),
    ]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)
    monkeypatch.setattr(trend_detail_module, "load_trends", lambda: trends)
    return trends


@pytest.fixture
def metrics(catalog):
    series = pd.concat(
        [
            _series_rows("fast", "fast trend", "Fast Trend", "aesthetic", _fast_collapse_values()),
            _series_rows("rising", "rising trend", "Rising Trend", "accessory", _still_rising_values()),
            _series_rows("unknown", "unknown trend", "Unknown Trend", "styling", [float("nan")] * 10),
        ],
        ignore_index=True,
    )
    return compute_all(series, Settings())


def _row(metrics, trend_id):
    return metrics.loc[metrics["trend_id"] == trend_id].iloc[0]


# ---- metric_cards ----------------------------------------------------


def test_metric_cards_renders_real_values_for_a_crossed_trend(metrics):
    cards = metric_cards(_row(metrics, "fast"))

    assert cards["peak_value"] != NO_PEAK_DETECTED
    assert cards["pct_dropped"].endswith("%")
    assert cards["decay_rate"].endswith("pts/wk")
    assert cards["weeks_to_half"].endswith("wk")
    assert cards["status"] == "Collapsed"


def test_metric_cards_explains_a_pre_peak_trend(metrics):
    cards = metric_cards(_row(metrics, "rising"))

    # peak_date/peak_value are real even pre-peak -- only the metrics
    # measured *from* the peak are still rising (see fashion_trends.metrics.peaks).
    assert cards["peak_value"] != NO_PEAK_DETECTED
    assert cards["pct_dropped"] == STILL_RISING
    assert cards["decay_rate"] == STILL_RISING
    assert cards["weeks_to_half"] == STILL_RISING
    assert "Pre-peak" in cards["status"]


def test_metric_cards_explains_a_trend_with_no_usable_peak(metrics):
    cards = metric_cards(_row(metrics, "unknown"))

    assert cards["peak_value"] == NO_PEAK_DETECTED
    assert cards["peak_date"] == NO_PEAK_DETECTED
    assert cards["pct_dropped"] == NO_PEAK_DETECTED
    assert cards["decay_rate"] == NO_PEAK_DETECTED
    assert cards["weeks_to_half"] == NO_PEAK_DETECTED
    assert "Unknown" in cards["status"]


def _minimal_row(**overrides):
    base = {
        "display_name": "Trend",
        "category": "aesthetic",
        "status": "stabilized",
        "peak_date": pd.Timestamp("2024-01-07"),
        "peak_value": 80.0,
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
    return pd.Series(base)


def test_metric_cards_labels_never_halved(metrics):
    cards = metric_cards(_minimal_row())

    assert cards["weeks_to_half"] == NEVER_HALVED


def test_metric_cards_labels_just_peaked(metrics):
    cards = metric_cards(_minimal_row(decay_rate_linear=float("nan"), weeks_since_peak=0))

    assert cards["decay_rate"] == JUST_PEAKED


def test_metric_cards_expands_every_status_to_plain_language(metrics):
    for status in ("unknown", "pre_peak", "revived", "collapsed", "stabilized", "declining"):
        cards = metric_cards(_minimal_row(status=status))
        assert cards["status"] != status  # every one gets expanded, none left as the bare label


def test_metric_cards_lists_active_flags():
    cards = metric_cards(_minimal_row(peak_at_boundary=True, has_secondary_peak=True))

    assert "peak near window edge" in cards["flags"]
    assert "secondary peak (revival)" in cards["flags"]


def test_metric_cards_empty_flags_string_when_no_caveats():
    cards = metric_cards(_minimal_row())

    assert cards["flags"] == ""


# ---- catalog_notes ----------------------------------------------------


def test_catalog_notes_returns_the_catalogs_notes_field(catalog):
    assert catalog_notes("fast") == "Picked as a fast-collapse example."


def test_catalog_notes_returns_placeholder_for_an_unknown_trend_id(catalog):
    assert catalog_notes("not-in-catalog") == NO_NOTES
