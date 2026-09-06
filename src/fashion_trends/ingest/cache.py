"""On-disk cache for raw Google Trends pulls, and the manifest that records
where every pulled value came from.

Google Trends samples its data, so re-running the same request can return
slightly different numbers; without a cache, results aren't reproducible
and every re-run burns quota. Each batch response is cached as a Parquet
file keyed by a hash of its `(keywords, timeframe, geo)`, alongside a JSON
side-car recording its fetch timestamp. A cache hit within
`settings.cache_ttl_days` needs no network access; `refresh=True` (or a
stale/missing entry) falls through to the network.

`settings.fixture_mode` bypasses both, serving from the committed
`tests/fixtures/` snapshot instead, labelled `source: "fixture"` in the
manifest.

`write_raw_manifest` records one entry per keyword actually pulled, so any
number downstream can be traced back to a pull date.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version as _package_version
from pathlib import Path
from typing import Literal

import pandas as pd

from fashion_trends.ingest import fixtures
from fashion_trends.ingest.pytrends_client import NoDataError, fetch_interest_over_time
from fashion_trends.settings import Settings
from fashion_trends.settings import write_manifest as _write_run_manifest

MANIFEST_FILENAME = "manifest.json"

Source = Literal["cache", "network", "fixture"]


def _cache_key(keywords: list[str], timeframe: str, geo: str) -> str:
    """A stable identifier for a batch request, independent of keyword order."""
    payload = json.dumps({"keywords": sorted(keywords), "timeframe": timeframe, "geo": geo}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entry_paths(data_raw_dir: Path, key: str) -> tuple[Path, Path]:
    cache_dir = Path(data_raw_dir) / "cache"
    return cache_dir / f"{key}.parquet", cache_dir / f"{key}.json"


def _pytrends_version() -> str:
    """The installed pytrends version, read from package metadata (not imported directly)."""
    return _package_version("pytrends")


@dataclass(frozen=True)
class CachedBatch:
    keywords: list[str]
    timeframe: str
    geo: str
    frame: pd.DataFrame
    fetched_at: datetime
    source: Source
    pytrends_version: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_fresh(fetched_at: datetime, ttl_days: int, now: datetime) -> bool:
    return (now - fetched_at).total_seconds() <= ttl_days * 86400


def _read_cache_entry(data_raw_dir: Path, key: str) -> tuple[pd.DataFrame, dict] | None:
    parquet_path, meta_path = _entry_paths(data_raw_dir, key)
    if not parquet_path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    frame = pd.read_parquet(parquet_path)
    return frame, meta


def _write_cache_entry(
    data_raw_dir: Path,
    key: str,
    keywords: list[str],
    timeframe: str,
    geo: str,
    frame: pd.DataFrame,
    fetched_at: datetime,
    pytrends_version: str,
) -> None:
    parquet_path, meta_path = _entry_paths(data_raw_dir, key)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path)
    meta = {
        "keywords": sorted(keywords),
        "timeframe": timeframe,
        "geo": geo,
        "fetched_at": fetched_at.isoformat(),
        "pytrends_version": pytrends_version,
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")


def fetch_batch(
    keywords: list[str],
    timeframe: str,
    geo: str,
    settings: Settings,
    refresh: bool = False,
) -> CachedBatch:
    """Fetch one Google Trends batch, serving from the on-disk cache when possible.

    A cache hit within `settings.cache_ttl_days` makes no network request.
    `refresh=True`, a missing entry, or a stale one fall through to
    `fetch_interest_over_time`. `settings.fixture_mode` takes precedence over
    all of this, serving from the fixture snapshot instead.
    """
    if settings.fixture_mode:
        try:
            frame = fixtures.fetch_interest_over_time(keywords)
        except fixtures.FixtureNotFoundError as exc:
            raise NoDataError(str(exc)) from exc
        return CachedBatch(
            keywords=keywords,
            timeframe=timeframe,
            geo=geo,
            frame=frame,
            fetched_at=datetime.fromisoformat(fixtures.captured_at()),
            source="fixture",
            pytrends_version=fixtures.pytrends_version(),
        )

    key = _cache_key(keywords, timeframe, geo)
    now = _utcnow()

    if not refresh:
        cached = _read_cache_entry(settings.data_raw_dir, key)
        if cached is not None:
            frame, meta = cached
            fetched_at = datetime.fromisoformat(meta["fetched_at"])
            if _is_fresh(fetched_at, settings.cache_ttl_days, now):
                return CachedBatch(
                    keywords=keywords,
                    timeframe=timeframe,
                    geo=geo,
                    frame=frame,
                    fetched_at=fetched_at,
                    source="cache",
                    pytrends_version=meta["pytrends_version"],
                )

    frame = fetch_interest_over_time(keywords, timeframe, geo, settings)
    pytrends_version = _pytrends_version()
    _write_cache_entry(settings.data_raw_dir, key, keywords, timeframe, geo, frame, now, pytrends_version)
    return CachedBatch(
        keywords=keywords,
        timeframe=timeframe,
        geo=geo,
        frame=frame,
        fetched_at=now,
        source="network",
        pytrends_version=pytrends_version,
    )


def write_raw_manifest(
    settings: Settings,
    batches: list[CachedBatch],
    path: Path | str | None = None,
) -> Path:
    """Write `data/raw/manifest.json`, recording per-keyword pull provenance for every keyword in `batches`."""
    path = Path(path) if path is not None else settings.data_raw_dir / MANIFEST_FILENAME

    series = [
        {
            "keyword": keyword,
            "timeframe": batch.timeframe,
            "geo": batch.geo,
            "fetched_at": batch.fetched_at.isoformat(),
            "row_count": len(batch.frame),
            "pytrends_version": batch.pytrends_version,
            "source": batch.source,
        }
        for batch in batches
        for keyword in batch.frame.columns
    ]

    return _write_run_manifest(settings, path, series=series)
