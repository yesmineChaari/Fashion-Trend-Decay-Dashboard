"""Ingestion and pipeline behaviour verified without ever touching the endpoint.

`tests/conftest.py` closes the socket layer for every test in the suite, so
"this runs offline" is enforced rather than assumed — the first test here
proves the guard is actually armed. Everything below it exercises the real
ingestion code against mocked responses, recorded fixtures, or the on-disk
cache: what is under test is the layer's own behaviour (batching, rescaling,
caching, retry, partial-failure tolerance, manifest provenance), none of
which needs Google Trends to be reachable to be checked.

The per-unit behaviours already have close-up tests in `test_cache.py`,
`test_batching.py`, `test_pytrends_client.py` and `test_pipeline.py`. What
this file adds is the seams between them — a full catalog going through the
real batch size, a rescaling ratio surviving all the way into
`series.parquet`, a partial failure reaching the manifest a reader will
actually consult, and the trailing in-progress week never arriving at all.
"""

import json
import socket
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from conftest import NetworkAccessDuringTestError
from fashion_trends.ingest import cache as cache_module
from fashion_trends.ingest import pipeline as pipeline_module
from fashion_trends.ingest import pytrends_client as client_module
from fashion_trends.ingest.batching import build_batches
from fashion_trends.ingest.cache import CachedBatch
from fashion_trends.ingest.pipeline import (
    MANIFEST_FILENAME,
    METRICS_FILENAME,
    SERIES_FILENAME,
    run_pipeline,
)
from fashion_trends.ingest.pytrends_client import NoDataError, RateLimitedError
from fashion_trends.keywords import Trend, load_trends
from fashion_trends.metrics.schema import METRICS_COLUMNS
from fashion_trends.settings import Settings

ANCHOR = "haute couture"


def trend(id_, keyword, isolate=False):
    return Trend(
        id=id_,
        keyword=keyword,
        display_name=keyword.title(),
        category="aesthetic",
        notes="test",
        isolate=isolate,
    )


def dates(n):
    return pd.date_range("2026-01-04", periods=n, freq="W-SUN")


def cached(frame, source="network"):
    return CachedBatch(
        keywords=list(frame.columns),
        timeframe="today 5-y",
        geo="US",
        frame=frame,
        fetched_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        source=source,
        pytrends_version="4.9.2",
    )


def settings_for(tmp_path, **overrides):
    """Pipeline settings pointed at `tmp_path`, at the real default batch size."""
    return Settings(
        anchor_keyword=ANCHOR,
        request_delay_seconds=0.0,
        max_retries=0,
        data_raw_dir=tmp_path / "raw",
        data_processed_dir=tmp_path / "processed",
        **overrides,
    )


# ---- the offline guarantee itself -----------------------------------------


def test_a_real_connection_attempt_fails_the_test():
    # Proves the autouse guard in conftest.py is armed. Without this, every
    # "runs offline" claim below rests on the guard silently still working.
    with pytest.raises(NetworkAccessDuringTestError):
        socket.create_connection(("trends.google.com", 443), timeout=1)


def test_loopback_stays_reachable():
    # The guard blocks the outside world, not local machinery -- a debugger or
    # a multiprocessing pipe must still work.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        client = socket.create_connection(listener.getsockname(), timeout=1)
        client.close()
    finally:
        listener.close()


# ---- batching at the real batch size --------------------------------------


def test_a_catalog_larger_than_one_batch_splits_with_the_anchor_in_every_batch():
    settings = Settings()
    trends = [trend(f"t{i}", f"keyword {i}") for i in range(12)]
    trends.append(trend("solo", "labubu", isolate=True))

    batches = build_batches(trends, settings.anchor_keyword, settings.max_batch_keywords)

    assert all(len(batch) <= settings.max_batch_keywords for batch in batches)
    assert all(batch[0] == settings.anchor_keyword for batch in batches)
    # Every trend keyword is fetched exactly once, and the isolated one shares
    # its batch with nothing but the anchor.
    fetched = [kw for batch in batches for kw in batch if kw != settings.anchor_keyword]
    assert sorted(fetched) == sorted(t.keyword for t in trends)
    assert [ANCHOR, "labubu"] in batches


def test_the_real_catalog_batches_within_the_google_trends_five_keyword_limit():
    settings = Settings()

    batches = build_batches(load_trends(), settings.anchor_keyword, settings.max_batch_keywords)

    assert batches
    assert all(1 < len(batch) <= 5 for batch in batches)
    assert all(batch.count(settings.anchor_keyword) == 1 for batch in batches)


def test_run_pipeline_sends_the_anchor_with_every_batch_it_fetches(monkeypatch, tmp_path):
    trends = [trend(f"t{i}", f"keyword {i}") for i in range(9)]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    sent = []

    def fake_fetch_batch(keywords, timeframe, geo, settings, refresh=False):
        sent.append(list(keywords))
        frame = pd.DataFrame({kw: [10, 40, 30, 20] for kw in keywords}, index=dates(4))
        return cached(frame)

    monkeypatch.setattr(pipeline_module, "fetch_batch", fake_fetch_batch)

    run_pipeline(settings_for(tmp_path))

    # 9 trends at 4 trend slots per batch -> 3 batches.
    assert len(sent) == 3
    assert all(batch[0] == ANCHOR for batch in sent)
    assert all(len(batch) <= 5 for batch in sent)


# ---- normalization end to end ---------------------------------------------


def test_a_known_anchor_ratio_rescales_all_the_way_into_the_persisted_series(monkeypatch, tmp_path):
    # The anchor peaks at 100 in one batch and 50 in the other, so the second
    # batch's values must come out doubled onto the first batch's axis while
    # its raw column is persisted untouched alongside them.
    trends = [trend("tall", "tall trend"), trend("small", "small trend", isolate=True)]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    reference = pd.DataFrame({ANCHOR: [50, 100, 75, 60], "tall trend": [20, 80, 60, 40]}, index=dates(4))
    crushed = pd.DataFrame({ANCHOR: [25, 50, 38, 30], "small trend": [10, 40, 30, 20]}, index=dates(4))
    monkeypatch.setattr(pipeline_module, "fetch_batch", MagicMock(side_effect=[cached(crushed), cached(reference)]))

    result = run_pipeline(settings_for(tmp_path))
    series = pd.read_parquet(result.series_path).set_index(["trend_id", "date"])

    small = series.loc["small"]
    assert list(small["interest_raw"]) == [10, 40, 30, 20]
    assert list(small["interest_rescaled"]) == pytest.approx([20, 80, 60, 40])
    # The reference batch is already on its own axis, so it is left alone.
    tall = series.loc["tall"]
    assert list(tall["interest_rescaled"]) == pytest.approx(list(tall["interest_raw"]))


def test_a_trend_that_never_clears_the_noise_floor_is_flagged_low_resolution(monkeypatch, tmp_path):
    trends = [trend("tall", "tall trend"), trend("tiny", "tiny trend", isolate=True)]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    reference = pd.DataFrame({ANCHOR: [50, 100, 75, 60], "tall trend": [20, 80, 60, 40]}, index=dates(4))
    # The anchor is not crushed here, so `tiny trend`'s 1-3 stays 1-3 after
    # rescaling -- below the 5.0 noise floor on the shared axis.
    tiny = pd.DataFrame({ANCHOR: [50, 100, 75, 60], "tiny trend": [1, 3, 2, 1]}, index=dates(4))
    monkeypatch.setattr(pipeline_module, "fetch_batch", MagicMock(side_effect=[cached(tiny), cached(reference)]))

    result = run_pipeline(settings_for(tmp_path))
    metrics = pd.read_parquet(result.metrics_path).set_index("trend_id")

    assert bool(metrics.loc["tiny", "low_resolution"]) is True
    assert bool(metrics.loc["tall", "low_resolution"]) is False


# ---- the trailing in-progress week ----------------------------------------


def install_fake_client(monkeypatch, frame):
    """Stand in for pytrends itself, so the real client wrapper is exercised."""
    trend_req = MagicMock()
    trend_req.interest_over_time.return_value = frame
    monkeypatch.setattr(client_module, "_client", None)
    monkeypatch.setattr(client_module, "_last_request_at", None)
    monkeypatch.setattr(client_module, "TrendReq", MagicMock(return_value=trend_req))
    return trend_req


def test_the_partial_week_never_reaches_the_persisted_series(monkeypatch, tmp_path):
    # Through the real client wrapper and the real cache, not around them --
    # the exclusion has to hold on the path the pipeline actually takes.
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: [trend("mob", "mob wife")])
    index = dates(5)
    install_fake_client(
        monkeypatch,
        pd.DataFrame(
            {
                ANCHOR: [50, 50, 50, 50, 9],
                "mob wife": [40, 40, 40, 40, 7],
                "isPartial": [False, False, False, False, True],
            },
            index=index,
        ),
    )

    result = run_pipeline(settings_for(tmp_path))
    series = pd.read_parquet(result.series_path)

    assert list(series["date"]) == list(index[:-1])
    assert index[-1] not in set(series["date"])
    assert 7 not in set(series["interest_raw"])


def test_keeping_the_partial_week_would_bias_pct_dropped_upward(monkeypatch, tmp_path):
    # Why the exclusion is worth a test of its own: the in-progress week lands
    # squarely in the trailing window `current_value` averages, so a
    # regression here inflates every "% dropped" in the run rather than
    # producing an obviously broken number someone would notice.
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: [trend("mob", "mob wife")])
    flat = [50] * 12
    index = dates(13)

    def run(final_week_partial):
        install_fake_client(
            monkeypatch,
            pd.DataFrame(
                {
                    ANCHOR: flat + [5],
                    "mob wife": flat + [5],
                    "isPartial": [False] * 12 + [final_week_partial],
                },
                index=index,
            ),
        )
        target = tmp_path / str(final_week_partial)
        result = run_pipeline(settings_for(target))
        return pd.read_parquet(result.metrics_path)["pct_dropped"].iloc[0]

    excluded = run(True)
    kept = run(False)

    assert excluded == pytest.approx(0.0)
    assert kept > 20.0


def test_a_response_of_nothing_but_partial_weeks_is_no_data(monkeypatch):
    install_fake_client(
        monkeypatch,
        pd.DataFrame({"mob wife": [7], "isPartial": [True]}, index=dates(1)),
    )

    with pytest.raises(NoDataError):
        client_module.fetch_interest_over_time(["mob wife"], "today 5-y", "US", Settings(request_delay_seconds=0.0))


# ---- retry and backoff ----------------------------------------------------


def test_backoff_between_retries_grows_exponentially(monkeypatch):
    from pytrends.exceptions import TooManyRequestsError

    slept = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    monkeypatch.setattr(client_module.random, "uniform", lambda a, b: 0.0)

    response = MagicMock()
    response.status_code = 429
    trend_req = MagicMock()
    trend_req.interest_over_time.side_effect = TooManyRequestsError.from_response(response)
    monkeypatch.setattr(client_module, "_client", None)
    monkeypatch.setattr(client_module, "_last_request_at", None)
    monkeypatch.setattr(client_module, "TrendReq", MagicMock(return_value=trend_req))

    with pytest.raises(RateLimitedError):
        client_module.fetch_interest_over_time(["kw"], "today 5-y", "US", Settings(max_retries=3, request_delay_seconds=0.0))

    # Four attempts, three backoffs: 1s, 2s, 4s. Retrying at a fixed interval
    # against a rate limiter is how a temporary 429 becomes a permanent one.
    assert slept == [1.0, 2.0, 4.0]
    assert trend_req.interest_over_time.call_count == 4


# ---- the orchestrator's manifest ------------------------------------------


def test_a_partial_failure_records_the_failed_keywords_in_the_processed_manifest(monkeypatch, tmp_path):
    trends = [trend("mob", "mob wife"), trend("demure", "demure", isolate=True)]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    good = pd.DataFrame({ANCHOR: [10, 50, 40, 30], "mob wife": [5, 25, 20, 15]}, index=dates(4))
    monkeypatch.setattr(
        pipeline_module,
        "fetch_batch",
        MagicMock(side_effect=[RateLimitedError("rate limited"), cached(good)]),
    )

    result = run_pipeline(settings_for(tmp_path))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    # The successful trend is persisted -- a bad batch must not lose the run's
    # other work -- and the failure is recorded rather than silently dropped.
    assert manifest["trends_requested"] == 2
    assert manifest["trends_succeeded"] == 1
    assert manifest["trends_failed"] == 1
    assert manifest["failures"] == [{"keywords": ["demure"], "reason": "rate limited"}]
    assert set(pd.read_parquet(result.metrics_path)["trend_id"]) == {"mob"}


def test_the_processed_manifest_records_the_settings_behind_the_run(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: [trend("mob", "mob wife")])
    frame = pd.DataFrame({ANCHOR: [10, 50, 40, 30], "mob wife": [5, 25, 20, 15]}, index=dates(4))
    monkeypatch.setattr(pipeline_module, "fetch_batch", MagicMock(return_value=cached(frame)))

    settings = settings_for(tmp_path, geo="FR")
    result = run_pipeline(settings)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert manifest["settings"] == settings.to_manifest()
    assert manifest["series_path"] == str(result.series_path)
    assert manifest["metrics_path"] == str(result.metrics_path)


def test_every_persisted_keyword_has_a_raw_manifest_entry(monkeypatch, tmp_path):
    trends = [trend("mob", "mob wife"), trend("demure", "demure", isolate=True)]
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: trends)

    demure = pd.DataFrame({ANCHOR: [40, 100, 80, 60], "demure": [50, 100, 90, 70]}, index=dates(4))
    mob = pd.DataFrame({ANCHOR: [10, 50, 40, 30], "mob wife": [5, 25, 20, 15]}, index=dates(4))
    monkeypatch.setattr(pipeline_module, "fetch_batch", MagicMock(side_effect=[cached(demure), cached(mob)]))

    settings = settings_for(tmp_path)
    result = run_pipeline(settings)

    raw_manifest = json.loads((settings.data_raw_dir / cache_module.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    recorded = {entry["keyword"] for entry in raw_manifest["series"]}
    persisted = set(pd.read_parquet(result.series_path)["keyword"])

    # Provenance is only useful if it is complete: every number that reached
    # `series.parquet` must be traceable to a pull date and a source.
    assert persisted <= recorded
    assert ANCHOR in recorded
    for entry in raw_manifest["series"]:
        assert entry["row_count"] == 4
        assert entry["source"] == "network"
        assert entry["fetched_at"]
        assert entry["pytrends_version"]


def test_a_cache_hit_is_recorded_as_a_cache_hit_in_the_raw_manifest(monkeypatch, tmp_path):
    # A rerun's numbers came from disk, not from Google that day, and the
    # manifest has to say so or the pull date it reports is a fiction.
    monkeypatch.setattr(pipeline_module, "load_trends", lambda: [trend("mob", "mob wife")])
    frame = pd.DataFrame({ANCHOR: [10, 50, 40, 30], "mob wife": [5, 25, 20, 15]}, index=dates(4))
    fetch = MagicMock(return_value=frame)
    monkeypatch.setattr(cache_module, "fetch_interest_over_time", fetch)
    monkeypatch.setattr(cache_module, "_pytrends_version", lambda: "4.9.2")

    settings = settings_for(tmp_path)
    run_pipeline(settings)
    run_pipeline(settings)

    assert fetch.call_count == 1
    raw_manifest = json.loads((settings.data_raw_dir / cache_module.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert {entry["source"] for entry in raw_manifest["series"]} == {"cache"}


# ---- the whole pipeline, offline, over the real catalog -------------------


def test_run_pipeline_completes_offline_against_the_recorded_fixture_set(tmp_path):
    # `fixture_mode` exists so a rate-limited or offline day is still a day of
    # progress; this is the end-to-end proof that it covers the whole catalog
    # and produces artifacts of the canonical shape.
    settings = settings_for(tmp_path, fixture_mode=True)

    result = run_pipeline(settings)

    assert result.failures == []
    assert result.trends_failed == 0
    assert result.trends_succeeded == result.trends_requested == len(load_trends())

    metrics = pd.read_parquet(settings.data_processed_dir / METRICS_FILENAME)
    assert list(metrics.columns) == list(METRICS_COLUMNS)
    assert set(metrics["trend_id"]) == {t.id for t in load_trends()}

    series = pd.read_parquet(settings.data_processed_dir / SERIES_FILENAME)
    assert set(series["trend_id"]) == set(metrics["trend_id"])
    assert (settings.data_processed_dir / MANIFEST_FILENAME).exists()


def test_fixture_mode_leaves_the_on_disk_cache_untouched(tmp_path):
    # Fixture runs are labelled `fixture` in the manifest and write nothing to
    # the raw cache, so a day spent offline can't be mistaken later for a day
    # of real pulls.
    settings = settings_for(tmp_path, fixture_mode=True)

    run_pipeline(settings)

    assert not (settings.data_raw_dir / "cache").exists()
    raw_manifest = json.loads((settings.data_raw_dir / cache_module.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert {entry["source"] for entry in raw_manifest["series"]} == {"fixture"}
