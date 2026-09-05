"""The metrics engine's single entry point.

`compute_all` turns a `series.parquet`-shaped frame into a
`metrics.parquet`-shaped one: one row per trend, running peak detection
(`fashion_trends.metrics.peaks`) and then every metric measured relative to
that peak — % dropped, decay rate, time-to-50% (`fashion_trends.metrics.decay`)
and the rule-based lifecycle label (`fashion_trends.metrics.status`) — plus
the provenance columns that tie a row back to the settings that produced it.

This is the function `fashion_trends.ingest.pipeline.run_pipeline` calls to
build the metrics half of a run, and it is meant to be the same function a
future dashboard live search calls to turn one freshly-pulled trend into a
metrics row: two callers computing the same numbers two different ways is
exactly the drift `fashion_trends.metrics.schema.validate_metrics_schema`
exists to catch, which is why that check runs here rather than being left to
each caller to remember.
"""

from __future__ import annotations

import pandas as pd

from fashion_trends.keywords import load_trends
from fashion_trends.metrics.decay import (
    compute_decay_rate_by_trend,
    compute_pct_dropped_by_trend,
    compute_time_to_half_by_trend,
)
from fashion_trends.metrics.peaks import detect_peaks_by_trend
from fashion_trends.metrics.schema import IDENTITY_COLUMNS, METRICS_COLUMNS, METRICS_DTYPES, validate_metrics_schema
from fashion_trends.metrics.status import compute_status_by_trend
from fashion_trends.settings import Settings

__all__ = ["compute_all"]


def compute_all(series: pd.DataFrame, settings: Settings | None = None) -> pd.DataFrame:
    """One row per trend in `series`: identity, every metric, and provenance.

    `series` has `series.parquet`'s shape — one row per (trend, week) with
    `trend_id`, `keyword`, `display_name`, `category`, `interest_raw`,
    `interest_smooth`, and `low_resolution` columns (see
    `fashion_trends.ingest.pipeline._build_series_frame`). `isolate` is looked
    up from the trend catalog by keyword rather than carried in `series` — it
    describes the trend itself, not one pull of it.

    `settings` defaults to `Settings()`: the pipeline passes its own resolved
    settings through so a run's actual parameters govern its own metrics, and
    a caller that just wants the documented defaults (a live-search lookup,
    say) can omit it entirely.

    `data_pull_date` is stamped as of this call, not read from `series` —
    for the pipeline that is effectively when the run's fetch completed; for
    a one-off live lookup it is simply "now," which is what that metric
    means in both cases: when was the interest data behind this row current.

    Returns a frame matching `fashion_trends.metrics.schema.METRICS_COLUMNS`
    exactly; `validate_metrics_schema` runs before returning, so a caller
    never has to re-check the shape of what comes back.
    """
    settings = settings or Settings()

    if series.empty:
        return pd.DataFrame(columns=METRICS_COLUMNS).astype(METRICS_DTYPES)

    isolate_by_keyword = {trend.keyword: trend.isolate for trend in load_trends()}

    per_trend = series.groupby("trend_id", as_index=False).agg(
        keyword=("keyword", "first"),
        display_name=("display_name", "first"),
        category=("category", "first"),
        low_resolution=("low_resolution", "any"),
    )
    # A keyword outside the catalog — a live-search lookup — has no `isolate`
    # setting to inherit, and the honest default is False: `isolate` describes
    # a trend needing a batch to itself, and a live lookup is fetched alone
    # regardless. Defaulted in the lookup rather than left as a NaN, since
    # `astype("bool")` further down would turn that NaN into True.
    per_trend["isolate"] = per_trend["keyword"].map(lambda kw: isolate_by_keyword.get(kw, False))

    peaks = detect_peaks_by_trend(
        series,
        settings.smoothing_window,
        settings.secondary_peak_ratio,
        settings.spike_peak_ratio,
        settings.peak_boundary_weeks,
        settings.pre_peak_rise_weeks,
    )
    pct_dropped = compute_pct_dropped_by_trend(series, peaks, settings.smoothing_window)
    decay_rate = compute_decay_rate_by_trend(series, peaks, pct_dropped, settings.min_decay_fit_weeks)
    time_to_half = compute_time_to_half_by_trend(series, peaks, settings.half_life_sustained_weeks)
    status = compute_status_by_trend(
        series,
        peaks,
        pct_dropped,
        settings.collapsed_pct_dropped_threshold,
        settings.stabilized_window_weeks,
        settings.stabilized_flat_tolerance,
        settings.stabilized_min_retained_pct,
    )

    metrics = per_trend[list(IDENTITY_COLUMNS)]
    for metric_frame in (peaks, pct_dropped, decay_rate, time_to_half, status):
        metrics = metrics.merge(metric_frame, on="trend_id", how="left")

    metrics["data_pull_date"] = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    metrics["timeframe"] = settings.timeframe
    metrics["geo"] = settings.geo

    metrics = metrics[list(METRICS_COLUMNS)].astype(METRICS_DTYPES)
    validate_metrics_schema(metrics)
    return metrics
