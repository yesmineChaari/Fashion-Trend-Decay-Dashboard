"""The metrics engine's single entry point.

`compute_all` turns a `series.parquet`-shaped frame into a
`metrics.parquet`-shaped one: one row per trend, running peak detection,
then every metric measured relative to that peak, plus provenance columns.
Both the batch pipeline and the dashboard's live search call this, so
`validate_metrics_schema` runs here to catch any drift between them.
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

    `isolate` is looked up from the trend catalog by keyword rather than
    carried in `series`, since it describes the trend itself, not one pull of
    it. `data_pull_date` is stamped as of this call, not read from `series`.
    Returns a frame matching `fashion_trends.metrics.schema.METRICS_COLUMNS`
    exactly; `validate_metrics_schema` runs before returning.
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
    # A keyword outside the catalog (a live-search lookup) defaults to False
    # rather than NaN, since `astype("bool")` would turn NaN into True.
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
