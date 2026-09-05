import pandas as pd

from fashion_trends import metrics as metrics_module
from fashion_trends.keywords import Trend
from fashion_trends.metrics import compute_all
from fashion_trends.metrics.schema import METRICS_COLUMNS, validate_metrics_schema
from fashion_trends.settings import Settings


def _trend(id_, keyword, isolate=False):
    return Trend(id=id_, keyword=keyword, display_name=keyword.title(), category="aesthetic", notes="t", isolate=isolate)


def _dates(n, start="2026-01-04"):
    return pd.date_range(start, periods=n, freq="W-SUN")


def _series_rows(trend_id, keyword, display_name, category, raw, smooth, low_resolution=False, start="2026-01-04"):
    dates = _dates(len(raw), start=start)
    return pd.DataFrame(
        {
            "date": dates,
            "trend_id": trend_id,
            "keyword": keyword,
            "display_name": display_name,
            "category": category,
            "interest_raw": raw,
            "interest_smooth": smooth,
            "low_resolution": low_resolution,
        }
    )


def test_compute_all_returns_the_canonical_schema(monkeypatch):
    trends = [_trend("mob", "mob wife"), _trend("demure", "demure", isolate=True)]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)

    falling = list(range(100, 40, -4))
    series = pd.concat(
        [
            _series_rows("mob", "mob wife", "Mob Wife", "aesthetic", falling, falling),
            _series_rows("demure", "demure", "Demure", "aesthetic", falling, falling),
        ],
        ignore_index=True,
    )

    result = compute_all(series, Settings())

    assert list(result.columns) == list(METRICS_COLUMNS)
    validate_metrics_schema(result)
    assert set(result["trend_id"]) == {"mob", "demure"}


def test_compute_all_looks_up_isolate_from_the_catalog_by_keyword(monkeypatch):
    trends = [_trend("mob", "mob wife", isolate=False), _trend("demure", "demure", isolate=True)]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)

    falling = list(range(100, 40, -4))
    series = pd.concat(
        [
            _series_rows("mob", "mob wife", "Mob Wife", "aesthetic", falling, falling),
            _series_rows("demure", "demure", "Demure", "aesthetic", falling, falling),
        ],
        ignore_index=True,
    )

    result = compute_all(series, Settings()).set_index("trend_id")

    assert bool(result.loc["mob", "isolate"]) is False
    assert bool(result.loc["demure", "isolate"]) is True


def test_compute_all_stamps_provenance_from_settings(monkeypatch):
    trends = [_trend("mob", "mob wife")]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)

    falling = list(range(100, 40, -4))
    series = _series_rows("mob", "mob wife", "Mob Wife", "aesthetic", falling, falling)
    settings = Settings(timeframe="today 5-y", geo="FR")

    result = compute_all(series, settings)

    assert (result["timeframe"] == "today 5-y").all()
    assert (result["geo"] == "FR").all()
    assert result["data_pull_date"].notna().all()
    assert result["data_pull_date"].iloc[0] == pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)


def test_compute_all_defaults_settings_when_omitted(monkeypatch):
    trends = [_trend("mob", "mob wife")]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)

    falling = list(range(100, 40, -4))
    series = _series_rows("mob", "mob wife", "Mob Wife", "aesthetic", falling, falling)

    result = compute_all(series)

    default = Settings()
    assert (result["timeframe"] == default.timeframe).all()
    assert (result["geo"] == default.geo).all()


def test_compute_all_returns_an_empty_but_schema_shaped_frame_for_empty_series(monkeypatch):
    monkeypatch.setattr(metrics_module, "load_trends", lambda: [])

    result = compute_all(pd.DataFrame(columns=["trend_id", "keyword", "display_name", "category", "low_resolution"]))

    assert list(result.columns) == list(METRICS_COLUMNS)
    assert len(result) == 0


def test_compute_all_runs_every_metric_stage(monkeypatch):
    # A synthetic trend clean enough to exercise peak detection, % dropped,
    # both decay-rate readings, and time-to-half all in one pass -- an
    # end-to-end sanity check that compute_all wires the stages together
    # correctly, not a re-test of each stage's own math.
    trends = [_trend("mob", "mob wife")]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)

    rise = [10.0, 30.0, 60.0]
    decay = [100.0 * (0.85**week) for week in range(30)]
    values = rise + decay
    series = _series_rows("mob", "mob wife", "Mob Wife", "aesthetic", values, values)

    result = compute_all(series, Settings()).iloc[0]

    assert pd.notna(result["peak_date"])
    assert result["pct_dropped"] > 0
    assert pd.notna(result["decay_rate_exp"])
    assert pd.notna(result["weeks_to_half"])
    assert result["status"] in {"declining", "collapsed", "stabilized", "revived"}
