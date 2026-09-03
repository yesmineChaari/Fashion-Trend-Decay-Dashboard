"""Thin wrapper around pytrends — the only module allowed to import it.

Retry/backoff, the polite inter-request delay, and typed error handling all
live here so callers (metrics, viz, the dashboard's live search) never touch
the unofficial API or its raw exceptions directly.
"""

from __future__ import annotations

import logging
import random
import time

import pandas as pd
from pytrends.exceptions import ResponseError, TooManyRequestsError
from pytrends.request import TrendReq
from requests.exceptions import RequestException

from fashion_trends.settings import Settings, load_settings

logger = logging.getLogger(__name__)

# Backoff schedule for retried attempts: base * 2**(attempt-1), plus jitter
# so concurrent callers (e.g. the dashboard fetching several keywords) don't
# all retry in lockstep.
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_JITTER_SECONDS = 0.5

_client: TrendReq | None = None
_last_request_at: float | None = None


class TrendsClientError(Exception):
    """Base class for errors raised by this wrapper."""


class RateLimitedError(TrendsClientError):
    """Google Trends kept returning HTTP 429 past `settings.max_retries`."""


class NoDataError(TrendsClientError):
    """Google Trends returned no rows, e.g. for an unrecognized keyword."""


class TransportError(TrendsClientError):
    """A non-rate-limit request failure, or a network error past retries."""


def _get_client() -> TrendReq:
    """Return the process-wide `TrendReq`, creating it on first use.

    `retries=0` disables pytrends' own urllib3 retry loop so every retry
    decision goes through the backoff-with-jitter logic below instead.
    """
    global _client
    if _client is None:
        _client = TrendReq(retries=0)
    return _client


def _throttle(request_delay_seconds: float) -> None:
    """Block until at least `request_delay_seconds` have passed since the
    last request this process made, regardless of which keyword it was for."""
    global _last_request_at
    now = time.monotonic()
    if _last_request_at is not None:
        remaining = request_delay_seconds - (now - _last_request_at)
        if remaining > 0:
            time.sleep(remaining)
    _last_request_at = time.monotonic()


def _sleep_backoff(attempt: int) -> None:
    delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    delay += random.uniform(0, _BACKOFF_JITTER_SECONDS)
    time.sleep(delay)


def _drop_partial_rows(frame: pd.DataFrame, keywords: list[str]) -> pd.DataFrame:
    if frame.empty:
        raise NoDataError(f"Google Trends returned no data for {keywords!r}")

    if "isPartial" in frame.columns:
        partial_count = int(pd.Series(frame["isPartial"]).astype(bool).sum())
        if partial_count:
            logger.info(
                "Dropping %d trailing partial-week row(s) for %r — the most "
                "recent week is usually incomplete and would otherwise "
                "depress the current-interest value.",
                partial_count,
                keywords,
            )
        frame = frame.drop(columns=["isPartial"])

    return frame


def fetch_interest_over_time(
    keywords: list[str],
    timeframe: str,
    geo: str,
    settings: Settings | None = None,
) -> pd.DataFrame:
    """Fetch Google Trends interest-over-time for `keywords`.

    Retries on HTTP 429 and on transient network errors with exponential
    backoff and jitter, up to `settings.max_retries` extra attempts, and
    waits `settings.request_delay_seconds` between consecutive requests to
    Google Trends (this call included).

    Raises `RateLimitedError` if 429s persist past `max_retries`,
    `TransportError` for other request or persistent network failures, and
    `NoDataError` if the response has no rows (e.g. an unknown keyword).
    """
    settings = settings or load_settings([])
    client = _get_client()
    total_attempts = settings.max_retries + 1

    for attempt in range(1, total_attempts + 1):
        _throttle(settings.request_delay_seconds)
        try:
            client.build_payload(keywords, timeframe=timeframe, geo=geo)
            frame = client.interest_over_time()
        except TooManyRequestsError as exc:
            if attempt < total_attempts:
                logger.warning(
                    "Rate-limited fetching %r (attempt %d/%d), backing off",
                    keywords,
                    attempt,
                    total_attempts,
                )
                _sleep_backoff(attempt)
                continue
            raise RateLimitedError(
                f"Google Trends rate-limited {keywords!r} after {attempt} attempt(s)"
            ) from exc
        except ResponseError as exc:
            raise TransportError(
                f"Google Trends rejected the request for {keywords!r}: {exc}"
            ) from exc
        except RequestException as exc:
            if attempt < total_attempts:
                logger.warning(
                    "Network error fetching %r (attempt %d/%d), backing off: %s",
                    keywords,
                    attempt,
                    total_attempts,
                    exc,
                )
                _sleep_backoff(attempt)
                continue
            raise TransportError(
                f"Network error fetching {keywords!r} after {attempt} attempt(s): {exc}"
            ) from exc
        else:
            return _drop_partial_rows(frame, keywords)

    raise AssertionError("unreachable: loop always returns or raises")
