"""Ad-hoc analysis of any keyword, for the dashboard's Live search page.

Fetches one keyword through the same ingest path and metrics engine
(`fashion_trends.metrics.compute_all`) the batch pipeline uses, so a live
lookup and a curated trend get numbers that are identical by construction.

A live lookup has no shared batch to rescale against, so its 0-100 values are
relative to its own maximum only; the four decay metrics are unaffected since
each is measured against the trend's own peak, but its height isn't
comparable to the curated set's (`AD_HOC_NOTICE`).

The Streamlit page (`app/views/live_search.py`) holds only widgets; all
decision logic lives here so it's testable without a running script.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from fashion_trends.ingest.cache import fetch_batch
from fashion_trends.ingest.pytrends_client import (
    NoDataError,
    RateLimitedError,
    TransportError,
    TrendsClientError,
)
from fashion_trends.metrics import compute_all
from fashion_trends.metrics.smoothing import preprocess_series
from fashion_trends.settings import Settings

__all__ = [
    "AD_HOC_NOTICE",
    "LiveResult",
    "analyze_keyword",
    "build_live_series",
    "describe_failure",
    "is_sparse",
    "lookup_keyword",
    "normalize_keyword",
    "seconds_until_next_lookup",
]

# `LIVE_CATEGORY` is deliberately not one of `fashion_trends.keywords.VALID_CATEGORIES`.
LIVE_TREND_ID = "live"
LIVE_CATEGORY = "live search"

# Below this fraction of nonzero weeks, a series is mostly zeros/gaps and any
# computed peak or decay would describe rounding noise, not a trend.
SPARSE_NONZERO_FRACTION = 0.25

# Google Trends throttles unofficial access aggressively.
MIN_SECONDS_BETWEEN_LOOKUPS = 3.0

AD_HOC_NOTICE = (
    "This result was just pulled for the keyword you typed, on its own scale. "
    "Its height isn't directly comparable to trends in the curated catalog. "
    "The numbers above it are still solid, though: each is measured against "
    "this keyword's own peak, not against anything else."
)

NO_DATA_MESSAGE = "Not enough search volume for this term. Try a broader phrasing."
RATE_LIMITED_MESSAGE = (
    "Google Trends is throttling us. It has no official API, and the "
    "unofficial endpoint this app uses rate-limits bursts of requests. "
    "Wait a few minutes and try again."
)
TRANSPORT_MESSAGE = "Couldn't reach Google Trends. Check your connection and try again."
SPARSE_MESSAGE = (
    "This series is too sparse to support metrics. Most weeks recorded no "
    "measurable interest at all, so a peak and a decay rate computed from it "
    "would describe rounding noise rather than a trend. The weekly series is "
    "shown below as-is."
)
UNKNOWN_FAILURE_MESSAGE = "The lookup failed. Try again in a moment."


@dataclass(frozen=True)
class LiveResult:
    """One ad-hoc keyword lookup: its series, its metrics, and whether to trust them.

    `series`/`metrics` match `series.parquet`/`metrics.parquet`'s shapes, so
    they feed the existing chart and card helpers unchanged. `sparse` means
    the metrics were computed but shouldn't be shown as findings, see
    `SPARSE_NONZERO_FRACTION`.
    """

    keyword: str
    timeframe: str
    geo: str
    series: pd.DataFrame
    metrics: pd.DataFrame
    sparse: bool

    @property
    def metrics_row(self) -> pd.Series:
        """The single metrics row, in the shape the card and chart helpers expect."""
        return self.metrics.iloc[0]


def normalize_keyword(raw: str) -> str:
    """Trim and collapse whitespace in a typed keyword; `""` if nothing is left. Case is left alone."""
    return re.sub(r"\s+", " ", raw).strip()


def is_sparse(raw: pd.Series, min_nonzero_fraction: float = SPARSE_NONZERO_FRACTION) -> bool:
    """True if too few of `raw`'s weeks carry measured interest to support metrics.

    Gap weeks (`NaN`) count against the fraction the same way zeros do; an
    empty series is sparse by definition.
    """
    if len(raw) == 0:
        return True
    nonzero = int((raw.fillna(0) > 0).sum())
    return nonzero / len(raw) < min_nonzero_fraction


def build_live_series(keyword: str, frame: pd.DataFrame, smoothing_window: int) -> pd.DataFrame:
    """Turn one raw keyword pull into a one-trend `series.parquet`-shaped frame.

    Mirrors `fashion_trends.ingest.pipeline._build_series_frame` for the
    single-keyword case. `interest_rescaled` equals `interest_raw` (no second
    batch to share an axis with) and `low_resolution` is always `False`
    (`is_sparse` catches a genuinely thin series instead).
    """
    processed = preprocess_series(frame[keyword], smoothing_window)

    return pd.DataFrame(
        {
            "date": processed.index,
            "trend_id": LIVE_TREND_ID,
            "keyword": keyword,
            "display_name": keyword,
            "category": LIVE_CATEGORY,
            "interest_raw": processed["interest_raw"].to_numpy(),
            "interest_smooth": processed["interest_smooth"].to_numpy(),
            "interest_rescaled": processed["interest_raw"].to_numpy(),
            "low_resolution": False,
        },
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


def analyze_keyword(keyword: str, settings: Settings, refresh: bool = False) -> LiveResult:
    """Fetch `keyword` and run it through the batch pipeline's own metrics engine.

    Goes through `fashion_trends.ingest.cache.fetch_batch` and
    `fashion_trends.metrics.compute_all` with the same `settings`. Raises
    `NoDataError`, `RateLimitedError`, or `TransportError`; `describe_failure`
    turns each into the message the page shows.
    """
    batch = fetch_batch([keyword], settings.timeframe, settings.geo, settings, refresh=refresh)

    series = build_live_series(keyword, batch.frame, settings.smoothing_window)
    if series.empty or series["interest_raw"].dropna().empty:
        raise NoDataError(f"Google Trends returned no usable weeks for {keyword!r}")

    return LiveResult(
        keyword=keyword,
        timeframe=settings.timeframe,
        geo=settings.geo,
        series=series,
        metrics=compute_all(series, settings),
        sparse=is_sparse(series["interest_raw"]),
    )


@st.cache_data(show_spinner="Fetching Google Trends…")
def lookup_keyword(keyword: str, settings: Settings, refresh: bool = False) -> LiveResult:
    """`analyze_keyword`, memoized per `(keyword, settings, refresh)` for the session.

    Only successful lookups are cached; Streamlit re-raises rather than
    memoizing an exception, since a `RateLimitedError` is a temporary state
    to retry, not an answer about the keyword.
    """
    return analyze_keyword(keyword, settings, refresh=refresh)


def describe_failure(error: Exception) -> str:
    """The message to show for a failed lookup, one per distinct failure mode.

    Anything that isn't a `TrendsClientError` is re-raised rather than
    dressed up as a friendly message.
    """
    if isinstance(error, NoDataError):
        return NO_DATA_MESSAGE
    if isinstance(error, RateLimitedError):
        return RATE_LIMITED_MESSAGE
    if isinstance(error, TransportError):
        return TRANSPORT_MESSAGE
    if isinstance(error, TrendsClientError):
        return UNKNOWN_FAILURE_MESSAGE
    raise error


def seconds_until_next_lookup(
    last_lookup_at: float | None,
    now: float,
    min_interval: float = MIN_SECONDS_BETWEEN_LOOKUPS,
) -> float:
    """Seconds a submission must still wait, or `0.0` if it can run now.

    `last_lookup_at`/`now` are `time.monotonic` readings; `None` means
    nothing submitted yet this session.
    """
    if last_lookup_at is None:
        return 0.0
    return max(0.0, min_interval - (now - last_lookup_at))
