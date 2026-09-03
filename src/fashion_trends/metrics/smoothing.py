"""Prepare a raw interest series for peak and decay detection.

Peak detection and every decay metric downstream (% dropped, decay rate,
time-to-50%, lifecycle status) read off a *smoothed* series so a single
noisy week doesn't get mistaken for the peak or for the point decline
started. But charts must still show the reader the real, unsmoothed data
with the smoothed line overlaid — so both values are kept side by side
rather than the raw one being discarded.

Two things a naive rolling mean gets wrong for this purpose, both handled
here:

* A trailing window shifts every peak later than it actually was, which
  then biases every "weeks since peak" and "time to 50% decline" figure in
  the same direction. The window here is centred instead.
* A gap in the pulled weeks (a missing sample, not a zero) would otherwise
  silently shorten the series and throw off any "weeks since peak" count
  that assumes one row per week. The index is reindexed to make gaps
  explicit as `NaN` rows instead.
"""

from __future__ import annotations

import pandas as pd


def normalize_weekly_index(series: pd.Series) -> pd.Series:
    """Reindex `series` onto a complete, evenly-spaced `DatetimeIndex`.

    The spacing is inferred from the series' own most common gap (weekly,
    for a real Google Trends pull) rather than hardcoded, so a missing week
    becomes an explicit `NaN` row instead of silently shortening the series.
    Fewer than two points can't imply a spacing, so they're returned as-is.
    """
    index = pd.DatetimeIndex(series.index).sort_values()
    if len(index) < 2:
        return series.reindex(index)

    step = index.to_series().diff().dropna().mode().iloc[0]
    full_index = pd.date_range(index.min(), index.max(), freq=step)
    return series.reindex(full_index)


def smooth_series(series: pd.Series, window: int) -> pd.Series:
    """Centred rolling mean of `series`, safe for series shorter than `window`.

    `min_periods=1` means a series shorter than `window` — or the first/last
    few points of any series, where a full centred window doesn't fit —
    still gets a value instead of `NaN`, computed from however many points
    are available. A centred window (unlike a trailing one) doesn't shift
    the peak date: it averages points symmetrically around each week rather
    than only the weeks before it.
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
    `interest_raw` (the untouched pulled values, `NaN` at a filled gap) and
    `interest_smooth` (the centred rolling mean over `window`) columns.

    `is_partial` — pytrends' own `isPartial` flag, aligned to `raw`'s index —
    drops the trailing in-progress week before anything else runs, so it
    never distorts the smoothed line or a later peak/decay calculation. In
    the normal pipeline this has already been dropped upstream (see
    `fashion_trends.ingest.pytrends_client`); it's accepted here too so this
    function is safe to call directly on an unprocessed pull.
    """
    series = raw
    if is_partial is not None:
        partial_dates = is_partial[is_partial.astype(bool)].index
        series = series.drop(index=partial_dates, errors="ignore")

    series = normalize_weekly_index(series)
    smoothed = smooth_series(series, window)

    return pd.DataFrame({"interest_raw": series, "interest_smooth": smoothed})
