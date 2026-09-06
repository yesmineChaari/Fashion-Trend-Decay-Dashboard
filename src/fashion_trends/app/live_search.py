"""Ad-hoc analysis of any keyword, for the dashboard's Live search page.

The point of this module is what it *doesn't* contain: no peak detection, no
decay maths, no second definition of what "% dropped" means. A live lookup
fetches one keyword through the same ingest path the batch pipeline uses
(`fashion_trends.ingest.cache.fetch_batch` — retry/backoff, the polite
inter-request delay, the on-disk raw cache and `fixture_mode` all included)
and then hands the result to `fashion_trends.metrics.compute_all`, the same
engine that produces `metrics.parquet`. A keyword typed into the dashboard
and a keyword listed in `config/trends.yaml` therefore get numbers that are
identical by construction rather than by two implementations agreeing.

One thing a live lookup genuinely cannot reproduce is the cross-batch
rescaling (`fashion_trends.ingest.batching`): it fetches a single keyword on
its own, with no shared anchor and no reference batch, so its 0-100 values
are relative to its own maximum and nothing else. That is fine for the four
headline decay metrics — each is measured against the trend's own peak — but
it does mean a live result's *height* is not comparable to the curated set's,
which is why `AD_HOC_NOTICE` exists and why the page must show it.

The Streamlit page (`app/views/live_search.py`) holds only widgets; every
decision that has a right answer — how a keyword is normalized, when a series
is too sparse to carry metrics, what each failure mode should say, whether a
submission arrived too soon after the last — lives here so it can be tested
without a running Streamlit script.
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

# A live result is one trend in a frame of its own, so its id and display
# name only ever have to be unique against itself. `LIVE_CATEGORY` is
# deliberately not one of `fashion_trends.keywords.VALID_CATEGORIES` — an
# ad-hoc keyword has no curated category, and `viz.theme.category_style`
# already falls back to a distinct neutral style for an unrecognized one.
LIVE_TREND_ID = "live"
LIVE_CATEGORY = "live search"

# Below this fraction of weeks carrying any measured interest at all, the
# series is mostly zeros: a peak, a "% dropped" and a decay constant can all
# still be computed from it, but they would be describing the handful of
# weeks Google Trends happened to round up to 1 rather than a trend. The
# chart is still worth showing — seeing the emptiness is the finding.
SPARSE_NONZERO_FRACTION = 0.25

# Minimum gap between two submissions. Google Trends throttles unofficial
# access aggressively, and a user retyping a keyword three times in five
# seconds is the fastest way to spend a session's quota on nothing.
MIN_SECONDS_BETWEEN_LOOKUPS = 3.0

AD_HOC_NOTICE = (
    "This result was just pulled for the keyword you typed, on its own scale — "
    "its height isn't directly comparable to trends in the curated catalog. "
    "The numbers above it are still solid, though: each is measured against "
    "this keyword's own peak, not against anything else."
)

NO_DATA_MESSAGE = "Not enough search volume for this term. Try a broader phrasing."
RATE_LIMITED_MESSAGE = (
    "Google Trends is throttling us. It has no official API, and the "
    "unofficial endpoint this app uses rate-limits bursts of requests — "
    "wait a few minutes and try again."
)
TRANSPORT_MESSAGE = "Couldn't reach Google Trends. Check your connection and try again."
SPARSE_MESSAGE = (
    "This series is too sparse to support metrics — most weeks recorded no "
    "measurable interest at all, so a peak and a decay rate computed from it "
    "would describe rounding noise rather than a trend. The weekly series is "
    "shown below as-is."
)
UNKNOWN_FAILURE_MESSAGE = "The lookup failed. Try again in a moment."


@dataclass(frozen=True)
class LiveResult:
    """One ad-hoc keyword lookup: its series, its metrics, and whether to trust them.

    `series` matches `series.parquet`'s shape (restricted to this one
    keyword) and `metrics` matches
    `fashion_trends.metrics.schema.METRICS_COLUMNS` with exactly one row, so
    both feed the existing chart and card helpers unchanged rather than
    needing live-search variants of either.

    `sparse` is the one piece of presentation advice this carries: the
    metrics were computed either way — the chart's own peak and half-life
    annotations read off them — but a sparse series' numbers should not be
    put in front of a reader as findings. See `SPARSE_NONZERO_FRACTION`.
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
    """Trim and collapse whitespace in a typed keyword; `""` if nothing is left.

    Case is left alone — Google Trends is case-insensitive, so lowercasing
    would only make the label shown back to the user differ from what they
    typed, for no gain. Collapsing interior whitespace does matter: it is
    what stops `"barrel  jeans"` and `"barrel jeans"` from occupying two
    cache entries and costing two requests for one question.
    """
    return re.sub(r"\s+", " ", raw).strip()


def is_sparse(raw: pd.Series, min_nonzero_fraction: float = SPARSE_NONZERO_FRACTION) -> bool:
    """True if too few of `raw`'s weeks carry measured interest to support metrics.

    Gap weeks (`NaN`) count against the fraction the same way zeros do —
    neither is evidence of interest — and an empty series is sparse by
    definition rather than an error, so a caller can ask this before
    deciding whether a result is worth reporting numbers for.
    """
    if len(raw) == 0:
        return True
    nonzero = int((raw.fillna(0) > 0).sum())
    return nonzero / len(raw) < min_nonzero_fraction


def build_live_series(keyword: str, frame: pd.DataFrame, smoothing_window: int) -> pd.DataFrame:
    """Turn one raw keyword pull into a one-trend `series.parquet`-shaped frame.

    Mirrors `fashion_trends.ingest.pipeline._build_series_frame` for the
    single-keyword case, and reuses the same
    `fashion_trends.metrics.smoothing.preprocess_series`, so the smoothed
    column a live lookup's metrics are read off is produced by identical code
    to the batch pipeline's.

    Two columns differ in meaning here, both because a live lookup fetches
    one keyword with no anchor alongside it:

    * `interest_rescaled` equals `interest_raw`. There is no second batch to
      put on a shared axis, so the pull is already on the only scale it has.
    * `low_resolution` is `False`. That flag means "this trend's tallest week
      barely clears the noise floor *of the shared rescaled axis*" (see
      `fashion_trends.ingest.batching.is_low_resolution`), and a solo pull
      has no shared axis to sit low on — its own maximum is 100 by
      construction. `is_sparse` is what catches the genuinely thin series
      here instead.
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

    Goes through `fashion_trends.ingest.cache.fetch_batch`, so this honours
    the on-disk raw cache, `settings.cache_ttl_days`, the retry/backoff
    schedule, the inter-request delay, and `settings.fixture_mode` without
    reimplementing any of them, and then through
    `fashion_trends.metrics.compute_all` with the same `settings` — a live
    lookup and a pipeline run of the same keyword differ only in which
    keywords were fetched alongside it.

    Raises `NoDataError` for a keyword Google Trends has nothing for (an
    empty response, or one whose every week is a gap), `RateLimitedError`
    when 429s persist past `settings.max_retries`, and `TransportError` for
    other request failures — `describe_failure` turns each into the message
    the page shows.
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

    `settings` carries the timeframe and geo, so this is the per-`(keyword,
    timeframe, geo)` cache the page needs: coming back to a keyword already
    looked at re-renders it without a second request, which matters because
    what is being conserved is a rate-limit budget rather than milliseconds.

    Only successful lookups are cached — Streamlit re-raises rather than
    memoizing an exception, which is the behaviour we want: a
    `RateLimitedError` is a temporary state the user is being told to retry
    out of, not an answer about their keyword.
    """
    return analyze_keyword(keyword, settings, refresh=refresh)


def describe_failure(error: Exception) -> str:
    """The message to show for a failed lookup, one per distinct failure mode.

    Each of the three `fashion_trends.ingest.pytrends_client` errors means
    something different to the person who typed the keyword — nothing to
    measure, throttled, or unreachable — and only the first is about their
    keyword at all, so they never share a message. Anything that isn't a
    `TrendsClientError` is re-raised rather than dressed up as a friendly
    message: an unexpected exception is a bug to see, not a state to explain.
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

    `last_lookup_at` and `now` are monotonic-clock readings
    (`time.monotonic`), and `None` means nothing has been submitted yet this
    session. Kept as a plain function of two timestamps so the page's guard
    is testable without a session, a clock, or a running script.
    """
    if last_lookup_at is None:
        return 0.0
    return max(0.0, min_interval - (now - last_lookup_at))
