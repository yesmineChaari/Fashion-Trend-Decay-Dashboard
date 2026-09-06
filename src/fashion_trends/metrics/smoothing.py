"""Prepare a raw interest series for peak and decay detection.

Peak detection and every decay metric read off a smoothed series so a single
noisy week isn't mistaken for the peak; charts keep the raw series alongside
it for display. A centred (not trailing) rolling window avoids biasing every
peak later than it actually was, and gaps are reindexed to explicit `NaN`
rows rather than silently shortening the series.
"""

from __future__ import annotations

import pandas as pd


def normalize_weekly_index(series: pd.Series) -> pd.Series:
    """Reindex `series` onto a complete, evenly-spaced `DatetimeIndex`.

    Spacing is inferred from the series' own most common gap. Fewer than two
    points can't imply a spacing, so they're returned as-is.
    """
    index = pd.DatetimeIndex(series.index).sort_values()
    if len(index) < 2:
        return series.reindex(index)

    step = index.to_series().diff().dropna().mode().iloc[0]
    full_index = pd.date_range(index.min(), index.max(), freq=step)
    return series.reindex(full_index)


def smooth_series(series: pd.Series, window: int) -> pd.Series:
    """Centred rolling mean of `series`, safe for series shorter than `window`.

    `min_periods=1` means the edges (and short series) still get a value
    computed from however many points are available, instead of `NaN`.
    """
    if window <= 1:
        return series.copy()
    return series.rolling(window=window, center=True, min_periods=1).mean()


def preprocess_series(
    raw: pd.Series,
    window: int,
    is_partial: pd.Series | None = None,
) -> pd.DataFrame:
    """Prepare one trend's raw interest series for peak and decay detection.

    Returns a frame indexed by a complete, gap-filled `DatetimeIndex` with
    `interest_raw` (`NaN` at a filled gap) and `interest_smooth` columns.
    `is_partial` (pytrends' `isPartial` flag) drops the trailing in-progress
    week first, so it never distorts the smoothed line.
    """
    series = raw
    if is_partial is not None:
        partial_dates = is_partial[is_partial.astype(bool)].index
        series = series.drop(index=partial_dates, errors="ignore")

    series = normalize_weekly_index(series)
    smoothed = smooth_series(series, window)

    return pd.DataFrame({"interest_raw": series, "interest_smooth": smoothed})
