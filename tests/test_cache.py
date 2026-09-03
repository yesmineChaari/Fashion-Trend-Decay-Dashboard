from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from fashion_trends.ingest import cache as cache_module
from fashion_trends.ingest.cache import fetch_batch, write_raw_manifest
from fashion_trends.settings import Settings


def _frame():
    return pd.DataFrame(
        {"haute couture": [10, 20], "mob wife": [1, 2]},
        index=pd.to_datetime(["2026-08-24", "2026-08-31"]),
    )


def _settings(tmp_path, **overrides):
    return Settings(data_raw_dir=tmp_path, cache_ttl_days=7, **overrides)


def test_fetch_batch_misses_then_hits_cache_with_no_network(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    fetch = MagicMock(return_value=_frame())
    monkeypatch.setattr(cache_module, "fetch_interest_over_time", fetch)
    monkeypatch.setattr(cache_module, "_pytrends_version", lambda: "4.9.2")

    first = fetch_batch(["haute couture", "mob wife"], "today 5-y", "US", settings)
    assert first.source == "network"
    assert fetch.call_count == 1

    # A network call on the second, identical request would fail the test —
    # this is the "second consecutive run makes zero network requests" case.
    fetch.side_effect = AssertionError("network should not be called on a cache hit")
    second = fetch_batch(["haute couture", "mob wife"], "today 5-y", "US", settings)

    assert second.source == "cache"
    assert fetch.call_count == 1
    pd.testing.assert_frame_equal(second.frame, first.frame)
    assert second.pytrends_version == "4.9.2"


def test_fetch_batch_key_is_order_independent(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    fetch = MagicMock(return_value=_frame())
    monkeypatch.setattr(cache_module, "fetch_interest_over_time", fetch)
    monkeypatch.setattr(cache_module, "_pytrends_version", lambda: "4.9.2")

    fetch_batch(["haute couture", "mob wife"], "today 5-y", "US", settings)
    second = fetch_batch(["mob wife", "haute couture"], "today 5-y", "US", settings)

    assert second.source == "cache"
    assert fetch.call_count == 1


def test_fetch_batch_refresh_forces_network(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    fetch = MagicMock(side_effect=[_frame(), _frame()])
    monkeypatch.setattr(cache_module, "fetch_interest_over_time", fetch)
    monkeypatch.setattr(cache_module, "_pytrends_version", lambda: "4.9.2")

    fetch_batch(["haute couture", "mob wife"], "today 5-y", "US", settings)
    second = fetch_batch(["haute couture", "mob wife"], "today 5-y", "US", settings, refresh=True)

    assert second.source == "network"
    assert fetch.call_count == 2


def test_fetch_batch_stale_entry_falls_through_to_network(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    fetch = MagicMock(side_effect=[_frame(), _frame()])
    monkeypatch.setattr(cache_module, "fetch_interest_over_time", fetch)
    monkeypatch.setattr(cache_module, "_pytrends_version", lambda: "4.9.2")

    stale_now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(cache_module, "_utcnow", lambda: stale_now)
    fetch_batch(["haute couture", "mob wife"], "today 5-y", "US", settings)

    fresh_now = stale_now + timedelta(days=8)
    monkeypatch.setattr(cache_module, "_utcnow", lambda: fresh_now)
    second = fetch_batch(["haute couture", "mob wife"], "today 5-y", "US", settings)

    assert second.source == "network"
    assert fetch.call_count == 2


def test_write_raw_manifest_records_one_entry_per_keyword_with_source(tmp_path):
    settings = _settings(tmp_path)
    network_batch = cache_module.CachedBatch(
        keywords=["haute couture", "mob wife"],
        timeframe="today 5-y",
        geo="US",
        frame=_frame(),
        fetched_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        source="network",
        pytrends_version="4.9.2",
    )

    path = write_raw_manifest(settings, [network_batch])

    assert path == tmp_path / "manifest.json"
    import json

    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["settings"]["geo"] == "US"

    by_keyword = {entry["keyword"]: entry for entry in manifest["series"]}
    assert set(by_keyword) == {"haute couture", "mob wife"}
    assert by_keyword["mob wife"]["source"] == "network"
    assert by_keyword["mob wife"]["row_count"] == 2
    assert by_keyword["mob wife"]["fetched_at"] == "2026-08-31T00:00:00+00:00"
    assert by_keyword["mob wife"]["pytrends_version"] == "4.9.2"
