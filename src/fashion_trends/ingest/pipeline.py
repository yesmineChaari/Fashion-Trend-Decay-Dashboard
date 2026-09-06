"""Orchestrate ingestion, normalization, and persistence into one reproducible run.

Called by `scripts/refresh_data.py`. Fetches every batch, rescales the ones
that succeeded onto one shared axis, and writes `series.parquet` (long
format, one row per trend-week) and `metrics.parquet` (one row per
successfully-collected trend, via `fashion_trends.metrics.compute_all`).

A batch is the unit of failure: pytrends fetches every keyword in a batch in
one request, so a failure there is recorded against every trend in it and
the run moves on. The run only fails outright when no batch succeeds at all.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from fashion_trends.ingest.batching import build_batches, is_low_resolution, rescale_batches
from fashion_trends.ingest.cache import fetch_batch, write_raw_manifest
from fashion_trends.ingest.pytrends_client import TrendsClientError
from fashion_trends.keywords import Trend, load_trends
from fashion_trends.metrics import compute_all
from fashion_trends.metrics.smoothing import preprocess_series
from fashion_trends.settings import Settings, write_manifest

SERIES_FILENAME = "series.parquet"
METRICS_FILENAME = "metrics.parquet"
MANIFEST_FILENAME = "manifest.json"


class UnknownTrendIdsError(ValueError):
    """Raised when `--trends` names an id that isn't in the catalog."""


class PipelineFailedError(RuntimeError):
    """Raised when every batch failed and there is nothing to persist."""


@dataclass(frozen=True)
class BatchFailure:
    keywords: list[str]
    reason: str


@dataclass(frozen=True)
class RunResult:
    series_path: Path
    metrics_path: Path
    manifest_path: Path
    trends_requested: int
    trends_succeeded: int
    trends_failed: int
    failures: list[BatchFailure] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def summary_lines(self) -> list[str]:
        lines = [
            f"trends: {self.trends_succeeded} succeeded, {self.trends_failed} failed, {self.trends_requested} requested",
            f"elapsed: {self.elapsed_seconds:.1f}s",
            f"series:   {self.series_path}",
            f"metrics:  {self.metrics_path}",
            f"manifest: {self.manifest_path}",
        ]
        for failure in self.failures:
            lines.append(f"  FAILED {failure.keywords!r}: {failure.reason}")
        return lines


def _select_trends(trend_ids: list[str] | None) -> list[Trend]:
    catalog = load_trends()
    if trend_ids is None:
        return catalog

    by_id = {trend.id: trend for trend in catalog}
    unknown = [tid for tid in trend_ids if tid not in by_id]
    if unknown:
        raise UnknownTrendIdsError(f"unknown trend id(s) {unknown!r}. Not in the catalog ({sorted(by_id)})")
    return [by_id[tid] for tid in trend_ids]


def _fetch_batches(
    batches: list[list[str]],
    settings: Settings,
    refresh: bool,
) -> tuple[list, list[list[str]], list[BatchFailure]]:
    """Fetch every batch, tolerating per-batch failure.

    Returns the successfully fetched `CachedBatch` objects, the keyword lists
    of the batches they came from (kept aligned by index), and one
    `BatchFailure` per batch that raised.
    """
    cached_batches = []
    succeeded_keyword_lists = []
    failures: list[BatchFailure] = []

    for batch in batches:
        try:
            cached_batches.append(fetch_batch(batch, settings.timeframe, settings.geo, settings, refresh=refresh))
            succeeded_keyword_lists.append(batch)
        except TrendsClientError as exc:
            failed_keywords = [kw for kw in batch if kw != settings.anchor_keyword]
            failures.append(BatchFailure(keywords=failed_keywords, reason=str(exc)))

    return cached_batches, succeeded_keyword_lists, failures


def _build_series_frame(
    trends_by_keyword: dict[str, Trend],
    raw_frames: list[pd.DataFrame],
    rescaled_frames: list[pd.DataFrame],
    anchor_keyword: str,
    low_resolution_threshold: float,
    smoothing_window: int,
) -> pd.DataFrame:
    rows = []
    for raw_frame, rescaled_frame in zip(raw_frames, rescaled_frames, strict=True):
        for keyword in raw_frame.columns:
            if keyword == anchor_keyword:
                continue
            trend = trends_by_keyword.get(keyword)
            if trend is None:
                continue
            rescaled_series = rescaled_frame[keyword]
            low_res = is_low_resolution(rescaled_series, low_resolution_threshold)

            # Smoothing runs on the trend's own raw scale; the reindex can
            # introduce gap weeks absent from the rescaled frame, so that one
            # is aligned onto the same index afterwards.
            processed = preprocess_series(raw_frame[keyword], smoothing_window)
            rescaled_series = rescaled_series.reindex(processed.index)

            for date, values in processed.iterrows():
                rows.append(
                    {
                        "date": date,
                        "trend_id": trend.id,
                        "keyword": trend.keyword,
                        "display_name": trend.display_name,
                        "category": trend.category,
                        "interest_raw": values["interest_raw"],
                        "interest_smooth": values["interest_smooth"],
                        "interest_rescaled": rescaled_series.loc[date],
                        "low_resolution": low_res,
                    }
                )

    return pd.DataFrame(
        rows,
        columns=[
            "date",
            "trend_id",
            "keyword",
            "display_name",
            "category",
            "interest_raw",
            "interest_smooth",
            "interest_rescaled",
            "low_resolution",
        ],
    )


def run_pipeline(
    settings: Settings,
    trend_ids: list[str] | None = None,
    refresh: bool = False,
) -> RunResult:
    """Fetch, normalize, and persist the requested trends (or the whole catalog).

    Raises `UnknownTrendIdsError` if `trend_ids` names an unknown id, and
    `PipelineFailedError` if every batch failed; anything less is persisted
    and reported as a partial success.
    """
    start = time.monotonic()
    trends = _select_trends(trend_ids)

    batches = build_batches(trends, settings.anchor_keyword, settings.max_batch_keywords)
    cached_batches, succeeded_keyword_lists, failures = _fetch_batches(batches, settings, refresh)
    write_raw_manifest(settings, cached_batches)

    trends_by_keyword = {trend.keyword: trend for trend in trends}
    failed_keywords = {kw for failure in failures for kw in failure.keywords}
    trends_succeeded = len(trends) - len(failed_keywords)

    if not cached_batches:
        raise PipelineFailedError(f"every batch failed, nothing to persist: {[f.reason for f in failures]}")

    raw_frames = [cached.frame for cached in cached_batches]
    rescaled_frames = rescale_batches(raw_frames, settings.anchor_keyword)

    series = _build_series_frame(
        trends_by_keyword,
        raw_frames,
        rescaled_frames,
        settings.anchor_keyword,
        settings.low_resolution_threshold,
        settings.smoothing_window,
    )
    metrics = compute_all(series, settings)

    settings.data_processed_dir.mkdir(parents=True, exist_ok=True)
    series_path = settings.data_processed_dir / SERIES_FILENAME
    metrics_path = settings.data_processed_dir / METRICS_FILENAME
    series.to_parquet(series_path)
    metrics.to_parquet(metrics_path)

    elapsed_seconds = time.monotonic() - start
    manifest_path = write_manifest(
        settings,
        settings.data_processed_dir / MANIFEST_FILENAME,
        trends_requested=len(trends),
        trends_succeeded=trends_succeeded,
        trends_failed=len(failed_keywords),
        failures=[{"keywords": f.keywords, "reason": f.reason} for f in failures],
        elapsed_seconds=elapsed_seconds,
        series_path=str(series_path),
        metrics_path=str(metrics_path),
    )

    return RunResult(
        series_path=series_path,
        metrics_path=metrics_path,
        manifest_path=manifest_path,
        trends_requested=len(trends),
        trends_succeeded=trends_succeeded,
        trends_failed=len(failed_keywords),
        failures=failures,
        elapsed_seconds=elapsed_seconds,
    )
