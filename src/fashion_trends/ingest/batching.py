"""Split trends into Google Trends batches and rescale them onto one axis.

Google Trends accepts at most five keywords per request and scales each
batch's values 0-100 relative to that batch's own maximum, so raw values
across batches aren't comparable. Every batch carries a shared anchor
keyword (`settings.anchor_keyword`); the ratio between the anchor's peak in
a given batch and in the reference batch puts that batch back on a common
scale.

The four headline decay metrics are relative to a trend's own peak, so they
don't need this. It only matters for comparing trends to each other and for
protecting low-volume trends from a dominant batchmate.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fashion_trends.ingest.cache import fetch_batch, write_raw_manifest
from fashion_trends.keywords import Trend
from fashion_trends.settings import Settings


def build_batches(
    trends: list[Trend],
    anchor_keyword: str,
    max_batch_keywords: int = 5,
) -> list[list[str]]:
    """Group `trends` into keyword lists for `fetch_interest_over_time`.

    Every batch starts with `anchor_keyword` plus up to
    `max_batch_keywords - 1` trend keywords. A trend with `isolate=True` gets
    a batch to itself (anchor + that one keyword), see `Trend.isolate`.
    """
    batch_capacity = max_batch_keywords - 1
    if batch_capacity < 1:
        raise ValueError("max_batch_keywords must allow at least one trend keyword alongside the anchor")

    isolated = [t for t in trends if t.isolate]
    shared = [t for t in trends if not t.isolate]

    batches = [[anchor_keyword, t.keyword] for t in isolated]

    for start in range(0, len(shared), batch_capacity):
        chunk = shared[start : start + batch_capacity]
        batches.append([anchor_keyword] + [t.keyword for t in chunk])

    return batches


def rescale_batches(
    batch_frames: list[pd.DataFrame],
    anchor_keyword: str,
    reference_index: int | None = None,
) -> list[pd.DataFrame]:
    """Rescale every batch in `batch_frames` onto one shared axis.

    Since every batch shares `anchor_keyword`, the ratio between the
    anchor's peak in a reference batch and in each other batch converts that
    batch onto the reference batch's scale. `reference_index` defaults to
    the batch where the anchor's raw peak is highest (least crushed by a
    dominant batchmate). Returns new frames; `batch_frames` are left
    untouched.
    """
    if not batch_frames:
        return []

    anchor_peaks = [frame[anchor_keyword].max() for frame in batch_frames]
    if reference_index is None:
        reference_index = max(range(len(anchor_peaks)), key=lambda i: anchor_peaks[i])

    reference_peak = anchor_peaks[reference_index]
    if reference_peak <= 0:
        raise ValueError(
            f"anchor keyword {anchor_keyword!r} has a zero peak in the reference batch "
            f"(index {reference_index}). Cannot compute a rescaling ratio from it"
        )

    rescaled = []
    for frame, batch_peak in zip(batch_frames, anchor_peaks, strict=True):
        if batch_peak <= 0:
            raise ValueError(
                f"anchor keyword {anchor_keyword!r} has a zero peak in one of the batches "
                "being rescaled. Check the batch actually included the anchor keyword"
            )
        ratio = reference_peak / batch_peak
        rescaled.append(frame.mul(ratio))

    return rescaled


def is_low_resolution(rescaled_series: pd.Series, threshold: float) -> bool:
    """True if `rescaled_series` never clears the noise floor after rescaling."""
    return bool(rescaled_series.max() < threshold)


@dataclass(frozen=True)
class NormalizedTrend:
    keyword: str
    raw: pd.Series
    rescaled: pd.Series
    low_resolution: bool


@dataclass(frozen=True)
class CollectionResult:
    anchor_keyword: str
    batches: list[list[str]]
    raw_batch_frames: list[pd.DataFrame]
    trends: dict[str, NormalizedTrend]

    @property
    def low_resolution_keywords(self) -> list[str]:
        """Keywords flagged `low_resolution`, sorted for stable output."""
        return sorted(k for k, t in self.trends.items() if t.low_resolution)


def collect_normalized_trends(
    trends: list[Trend],
    settings: Settings,
    refresh: bool = False,
) -> CollectionResult:
    """Fetch every batch for `trends` and rescale them onto one shared axis.

    Goes through the on-disk raw cache, so a repeat run within
    `settings.cache_ttl_days` makes no network requests; `refresh=True`
    forces a re-pull. Writes the cache and provenance manifest as a side
    effect; persisting the rescaled/processed data is still the caller's job.
    """
    batches = build_batches(trends, settings.anchor_keyword, settings.max_batch_keywords)
    cached_batches = [fetch_batch(batch, settings.timeframe, settings.geo, settings, refresh=refresh) for batch in batches]
    write_raw_manifest(settings, cached_batches)

    raw_frames = [cached.frame for cached in cached_batches]
    rescaled_frames = rescale_batches(raw_frames, settings.anchor_keyword)

    results: dict[str, NormalizedTrend] = {}
    for raw_frame, rescaled_frame in zip(raw_frames, rescaled_frames, strict=True):
        for keyword in raw_frame.columns:
            if keyword == settings.anchor_keyword:
                continue
            rescaled_series = rescaled_frame[keyword]
            results[keyword] = NormalizedTrend(
                keyword=keyword,
                raw=raw_frame[keyword],
                rescaled=rescaled_series,
                low_resolution=is_low_resolution(rescaled_series, settings.low_resolution_threshold),
            )

    return CollectionResult(
        anchor_keyword=settings.anchor_keyword,
        batches=batches,
        raw_batch_frames=raw_frames,
        trends=results,
    )
