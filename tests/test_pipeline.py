from unittest.mock import MagicMock

import pandas as pd
import pytest

from fashion_trends.ingest import pipeline as pipeline_module
from fashion_trends.ingest.cache import CachedBatch
from fashion_trends.ingest.pipeline import (
    PipelineFailedError,
    UnknownTrendIdsError,
    run_pipeline,
)
from fashion_trends.ingest.pytrends_client import NoDataError, RateLimitedError
from fashion_trends.keywords import Trend
from fashion_trends.metrics.decay import (
    DECAY_RATE_COLUMNS,
    PCT_DROPPED_COLUMNS,
    TIME_TO_HALF_COLUMNS,
)
from fashion_trends.metrics.peaks import PEAK_COLUMNS
from fashion_trends.metrics.status import STATUS_COLUMNS
from fashion_trends.settings import Settings

ANCHOR = "haute couture"


def _trend(id_, keyword, isolate=False):
    return Trend(
        id=id_,
        keyword=keyword,
        display_name=keyword.title(),
        category="aesthetic",
        notes="test",
        isolate=isolate,
    )


def _dates(n):
    return pd.to_datetime([f"2026-01-{i + 1:02d}" for i in range(n)])


def _cached(frame, source="network"):
    from datetime import datetime, timezone

    return CachedBatch(
        keywords=list(frame.columns),
        timeframe="today 5-y",
        geo="US",
        frame=frame,
        fetched_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        source=source,
        pytrends_version="4.9.2",
    )


def _settings(tmp_path):
    return Settings(
        anchor_keyword=ANCHOR,
        max_batch_keywords=3,
        low_resolution_threshold=5.0,
        request_delay_seconds=0.0,
        max_retries=0,
        data_raw_dir=tmp_path / "raw",
        data_processed_dir=tmp_path / "processed",
    )


def test_run_pipeline_persists_series_and_metrics(monkeypatch, tmp_path):
    trends = [_trend("mob", "mob wife"), _trend("demure", "demure", isolate=True)]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    demure_batch = pd.DataFrame({ANCHOR: [40, 100], "demure": [50, 100]}, index=_dates(2))
    mob_batch = pd.DataFrame({ANCHOR: [10, 50], "mob wife": [5, 25]}, index=_dates(2))
    fetch = MagicMock(side_effect=[_cached(demure_batch), _cached(mob_batch)])
    monkeypatch.setattr(pipeline_module, "fetch_batch", fetch)

    settings = _settings(tmp_path)
    result = run_pipeline(settings)

    assert result.trends_requested == 2
    assert result.trends_succeeded == 2
    assert result.trends_failed == 0
    assert result.failures == []
    assert result.series_path.exists()
    assert result.metrics_path.exists()
    assert result.manifest_path.exists()

    series = pd.read_parquet(result.series_path)
    assert set(series["trend_id"]) == {"mob", "demure"}
    assert list(series.columns) == [
        "date",
        "trend_id",
        "keyword",
        "display_name",
        "category",
        "interest_raw",
        "interest_smooth",
        "interest_rescaled",
        "low_resolution",
    ]

    metrics = pd.read_parquet(result.metrics_path)
    assert set(metrics["trend_id"]) == {"mob", "demure"}
    assert set(metrics.columns) == {
        "trend_id",
        "keyword",
        "display_name",
        "category",
        "isolate",
        "low_resolution",
        *PEAK_COLUMNS,
        *PCT_DROPPED_COLUMNS,
        *DECAY_RATE_COLUMNS,
        *TIME_TO_HALF_COLUMNS,
        *STATUS_COLUMNS,
    }
    assert bool(metrics.loc[metrics["trend_id"] == "demure", "isolate"].iloc[0]) is True
    # Peak detection runs as part of the same pass, so every persisted trend
    # carries the peak its decay metrics will be measured against.
    assert metrics["peak_date"].notna().all()
    # With only two pulled weeks, a centred 4-week smoothing window averages
    # both into an identical value for each trend — the "peak" and "current"
    # windows land on the same number, so % dropped is a deterministic 0.
    assert (metrics["pct_dropped"] == 0.0).all()
    # Two weeks is far too short a post-peak segment to fit a decay constant
    # to, so the fit columns come back null rather than extrapolating one.
    assert metrics["decay_rate_exp"].isna().all()
    # Neither trend drops below half its own (identically smoothed) peak, so
    # both are reported as still above half rather than as a failed metric.
    assert (metrics["time_to_half_status"] == "still_above_half").all()


def test_run_pipeline_tolerates_partial_batch_failure(monkeypatch, tmp_path):
    trends = [_trend("mob", "mob wife"), _trend("demure", "demure", isolate=True)]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    mob_batch = pd.DataFrame({ANCHOR: [10, 50], "mob wife": [5, 25]}, index=_dates(2))
    fetch = MagicMock(
        side_effect=[RateLimitedError("rate limited"), _cached(mob_batch)]
    )
    monkeypatch.setattr(pipeline_module, "fetch_batch", fetch)

    settings = _settings(tmp_path)
    result = run_pipeline(settings)

    assert result.trends_succeeded == 1
    assert result.trends_failed == 1
    assert result.failures == [pipeline_module.BatchFailure(keywords=["demure"], reason="rate limited")]

    series = pd.read_parquet(result.series_path)
    assert set(series["trend_id"]) == {"mob"}


def test_run_pipeline_raises_when_every_batch_fails(monkeypatch, tmp_path):
    trends = [_trend("mob", "mob wife")]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)
    monkeypatch.setattr(
        pipeline_module, "fetch_batch", MagicMock(side_effect=NoDataError("no data"))
    )

    settings = _settings(tmp_path)
    with pytest.raises(PipelineFailedError):
        run_pipeline(settings)


def test_run_pipeline_filters_by_trend_ids(monkeypatch, tmp_path):
    trends = [_trend("mob", "mob wife"), _trend("demure", "demure", isolate=True)]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    mob_batch = pd.DataFrame({ANCHOR: [10, 50], "mob wife": [5, 25]}, index=_dates(2))
    fetch = MagicMock(return_value=_cached(mob_batch))
    monkeypatch.setattr(pipeline_module, "fetch_batch", fetch)

    settings = _settings(tmp_path)
    result = run_pipeline(settings, trend_ids=["mob"])

    assert result.trends_requested == 1
    assert fetch.call_count == 1


def test_run_pipeline_rejects_unknown_trend_id(monkeypatch, tmp_path):
    trends = [_trend("mob", "mob wife")]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    settings = _settings(tmp_path)
    with pytest.raises(UnknownTrendIdsError):
        run_pipeline(settings, trend_ids=["not_a_real_id"])


def test_run_pipeline_is_idempotent_with_warm_cache(monkeypatch, tmp_path):
    trends = [_trend("mob", "mob wife")]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    mob_batch = pd.DataFrame({ANCHOR: [10, 50], "mob wife": [5, 25]}, index=_dates(2))
    # cache.fetch_batch itself (not pipeline's import) is exercised here, so the
    # cache layer's own TTL logic is what makes the second run network-free.
    fetch_network = MagicMock(return_value=mob_batch)
    from fashion_trends.ingest import cache as cache_module

    monkeypatch.setattr(cache_module, "fetch_interest_over_time", fetch_network)
    monkeypatch.setattr(cache_module, "_pytrends_version", lambda: "4.9.2")

    settings = _settings(tmp_path)
    first = run_pipeline(settings)
    second = run_pipeline(settings)

    assert fetch_network.call_count == 1
    first_series = pd.read_parquet(first.series_path)
    second_series = pd.read_parquet(second.series_path)
    pd.testing.assert_frame_equal(first_series, second_series)
