import numpy as np
import pandas as pd
import pytest

from fashion_trends.app import live_search
from fashion_trends.app.live_search import (
    LIVE_CATEGORY,
    LIVE_TREND_ID,
    NO_DATA_MESSAGE,
    RATE_LIMITED_MESSAGE,
    TRANSPORT_MESSAGE,
    UNKNOWN_FAILURE_MESSAGE,
    analyze_keyword,
    build_live_series,
    describe_failure,
    is_sparse,
    normalize_keyword,
    seconds_until_next_lookup,
)
from fashion_trends.ingest.cache import CachedBatch
from fashion_trends.ingest.pytrends_client import (
    NoDataError,
    RateLimitedError,
    TransportError,
    TrendsClientError,
)
from fashion_trends.metrics import compute_all
from fashion_trends.metrics.schema import METRICS_COLUMNS
from fashion_trends.settings import Settings

WEEKS = 120


def _weekly_index(periods=WEEKS):
    return pd.date_range("2024-01-07", periods=periods, freq="W-SUN")


def _decaying_values(periods=WEEKS):
    """A clean rise-then-decay shape: peak in the middle, exponential fade after."""
    index = np.arange(periods)
    peak_at = periods // 3
    rising = np.linspace(5, 100, peak_at + 1)
    falling = 100 * np.exp(-0.05 * np.arange(1, periods - peak_at))
    return np.concatenate([rising, falling])[:periods]


def _pull_frame(keyword, values=None, periods=WEEKS):
    """A pytrends-shaped pull: a date-indexed frame with one column per keyword."""
    values = _decaying_values(periods) if values is None else values
    return pd.DataFrame({keyword: values}, index=_weekly_index(periods))


def _stub_fetch(monkeypatch, frame, keyword):
    """Point `analyze_keyword`'s only network path at `frame`."""
    calls = []

    def fake_fetch_batch(keywords, timeframe, geo, settings, refresh=False):
        calls.append((tuple(keywords), timeframe, geo, refresh))
        return CachedBatch(
            keywords=list(keywords),
            timeframe=timeframe,
            geo=geo,
            frame=frame,
            fetched_at=pd.Timestamp("2026-09-01", tz="UTC").to_pydatetime(),
            source="network",
            pytrends_version="4.9.2",
        )

    monkeypatch.setattr(live_search, "fetch_batch", fake_fetch_batch)
    return calls


def _stub_fetch_raising(monkeypatch, error):
    def fake_fetch_batch(keywords, timeframe, geo, settings, refresh=False):
        raise error

    monkeypatch.setattr(live_search, "fetch_batch", fake_fetch_batch)


# ---- normalize_keyword ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  barrel jeans  ", "barrel jeans"),
        ("barrel   jeans", "barrel jeans"),
        ("barrel\tjeans", "barrel jeans"),
        ("   ", ""),
        ("", ""),
    ],
)
def test_normalize_keyword_trims_and_collapses_whitespace(raw, expected):
    assert normalize_keyword(raw) == expected


def test_normalize_keyword_preserves_case():
    # Lowercasing would make the label echoed back differ from what was typed
    # without buying anything -- Google Trends is case-insensitive already.
    assert normalize_keyword("Barrel Jeans") == "Barrel Jeans"


# ---- is_sparse ----------------------------------------------------


def test_is_sparse_flags_a_mostly_zero_series():
    values = [0.0] * 90 + [4.0] * 10
    assert is_sparse(pd.Series(values)) is True


def test_is_sparse_does_not_flag_a_dense_series():
    assert is_sparse(pd.Series(_decaying_values())) is False


def test_is_sparse_counts_gap_weeks_against_the_fraction():
    # A NaN week is not evidence of interest any more than a zero is.
    values = pd.Series([np.nan] * 90 + [50.0] * 10)
    assert is_sparse(values) is True


def test_is_sparse_treats_an_empty_series_as_sparse():
    assert is_sparse(pd.Series(dtype=float)) is True


def test_is_sparse_threshold_is_a_fraction_of_nonzero_weeks():
    values = pd.Series([0.0] * 70 + [1.0] * 30)
    assert is_sparse(values, min_nonzero_fraction=0.25) is False
    assert is_sparse(values, min_nonzero_fraction=0.5) is True


# ---- build_live_series ----------------------------------------------------


def test_build_live_series_matches_the_processed_series_shape():
    frame = _pull_frame("barrel jeans")

    series = build_live_series("barrel jeans", frame, smoothing_window=4)

    assert list(series.columns) == [
        "date",
        "trend_id",
        "keyword",
        "display_name",
        "category",
        "interest_raw",
        "interest_smooth",
        "interest_rescaled",
        "low_resolution",
    ]
    assert set(series["trend_id"]) == {LIVE_TREND_ID}
    assert set(series["keyword"]) == {"barrel jeans"}
    assert set(series["category"]) == {LIVE_CATEGORY}
    assert len(series) == WEEKS


def test_build_live_series_leaves_values_on_their_own_scale():
    # A solo pull has no anchor and no reference batch, so there is nothing to
    # rescale against and nothing to sit low on a shared axis.
    frame = _pull_frame("barrel jeans")

    series = build_live_series("barrel jeans", frame, smoothing_window=4)

    pd.testing.assert_series_equal(
        series["interest_rescaled"], series["interest_raw"], check_names=False
    )
    assert not series["low_resolution"].any()


def test_build_live_series_smooths_with_the_configured_window():
    frame = _pull_frame("barrel jeans")

    narrow = build_live_series("barrel jeans", frame, smoothing_window=2)
    wide = build_live_series("barrel jeans", frame, smoothing_window=12)

    assert not np.allclose(narrow["interest_smooth"], wide["interest_smooth"])


# ---- analyze_keyword ----------------------------------------------------


def test_analyze_keyword_fetches_the_keyword_alone_with_the_request_shape(monkeypatch):
    calls = _stub_fetch(monkeypatch, _pull_frame("barrel jeans"), "barrel jeans")
    settings = Settings(timeframe="today 12-m", geo="FR")

    analyze_keyword("barrel jeans", settings)

    assert calls == [(("barrel jeans",), "today 12-m", "FR", False)]


def test_analyze_keyword_returns_a_canonical_one_row_metrics_frame(monkeypatch):
    _stub_fetch(monkeypatch, _pull_frame("barrel jeans"), "barrel jeans")

    result = analyze_keyword("barrel jeans", Settings())

    assert list(result.metrics.columns) == list(METRICS_COLUMNS)
    assert len(result.metrics) == 1
    assert result.metrics_row["keyword"] == "barrel jeans"
    assert result.metrics_row["display_name"] == "barrel jeans"


def test_analyze_keyword_matches_what_the_batch_pipeline_would_compute(monkeypatch):
    # The acceptance criterion for this ticket: a live lookup and the batch
    # pipeline must produce the same numbers for the same series, because they
    # are literally the same engine rather than two implementations agreeing.
    frame = _pull_frame("barrel jeans")
    _stub_fetch(monkeypatch, frame, "barrel jeans")
    settings = Settings()

    result = analyze_keyword("barrel jeans", settings)
    expected = compute_all(build_live_series("barrel jeans", frame, settings.smoothing_window), settings)

    pd.testing.assert_frame_equal(result.metrics, expected)


def test_analyze_keyword_does_not_inherit_isolate_from_the_catalog(monkeypatch):
    # An ad-hoc keyword has no catalog entry, so `isolate` has no value to map
    # from -- it must land as False rather than as a NaN cast to True.
    _stub_fetch(monkeypatch, _pull_frame("barrel jeans"), "barrel jeans")

    result = analyze_keyword("barrel jeans", Settings())

    assert bool(result.metrics_row["isolate"]) is False


def test_analyze_keyword_flags_a_sparse_series_but_still_returns_it(monkeypatch):
    values = np.array([0.0] * 110 + [3.0] * 10)
    _stub_fetch(monkeypatch, _pull_frame("obscure term", values), "obscure term")

    result = analyze_keyword("obscure term", Settings())

    assert result.sparse is True
    assert len(result.series) == WEEKS
    assert len(result.metrics) == 1


def test_analyze_keyword_does_not_flag_a_dense_series(monkeypatch):
    _stub_fetch(monkeypatch, _pull_frame("barrel jeans"), "barrel jeans")

    assert analyze_keyword("barrel jeans", Settings()).sparse is False


def test_analyze_keyword_raises_no_data_for_an_all_gap_series(monkeypatch):
    values = np.full(WEEKS, np.nan)
    _stub_fetch(monkeypatch, _pull_frame("nonsense term", values), "nonsense term")

    with pytest.raises(NoDataError):
        analyze_keyword("nonsense term", Settings())


@pytest.mark.parametrize(
    "error",
    [
        NoDataError("no rows"),
        RateLimitedError("429"),
        TransportError("connection reset"),
    ],
)
def test_analyze_keyword_propagates_client_errors_unchanged(monkeypatch, error):
    _stub_fetch_raising(monkeypatch, error)

    with pytest.raises(type(error)):
        analyze_keyword("barrel jeans", Settings())


def test_analyze_keyword_forwards_the_refresh_flag(monkeypatch):
    calls = _stub_fetch(monkeypatch, _pull_frame("barrel jeans"), "barrel jeans")

    analyze_keyword("barrel jeans", Settings(), refresh=True)

    assert calls[0][3] is True


def test_analyze_keyword_records_the_request_shape_on_the_result(monkeypatch):
    _stub_fetch(monkeypatch, _pull_frame("barrel jeans"), "barrel jeans")

    result = analyze_keyword("barrel jeans", Settings(timeframe="today 12-m", geo="GB"))

    assert (result.timeframe, result.geo) == ("today 12-m", "GB")


# ---- describe_failure ----------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NoDataError("no rows"), NO_DATA_MESSAGE),
        (RateLimitedError("429"), RATE_LIMITED_MESSAGE),
        (TransportError("connection reset"), TRANSPORT_MESSAGE),
        (TrendsClientError("something else"), UNKNOWN_FAILURE_MESSAGE),
    ],
)
def test_describe_failure_gives_each_failure_mode_its_own_message(error, expected):
    assert describe_failure(error) == expected


def test_describe_failure_messages_are_all_distinct():
    messages = {NO_DATA_MESSAGE, RATE_LIMITED_MESSAGE, TRANSPORT_MESSAGE, UNKNOWN_FAILURE_MESSAGE}
    assert len(messages) == 4


def test_describe_failure_explains_that_google_throttles_unofficial_access():
    assert "rate-limit" in RATE_LIMITED_MESSAGE
    assert "few minutes" in RATE_LIMITED_MESSAGE


def test_describe_failure_reraises_an_unexpected_exception():
    # An unexpected error is a bug to surface, not a state to explain away.
    with pytest.raises(ValueError):
        describe_failure(ValueError("boom"))


# ---- seconds_until_next_lookup ----------------------------------------------------


def test_seconds_until_next_lookup_allows_the_first_submission():
    assert seconds_until_next_lookup(None, now=100.0) == 0.0


def test_seconds_until_next_lookup_blocks_a_rapid_repeat():
    assert seconds_until_next_lookup(100.0, now=101.0, min_interval=3.0) == pytest.approx(2.0)


def test_seconds_until_next_lookup_allows_a_submission_after_the_interval():
    assert seconds_until_next_lookup(100.0, now=104.0, min_interval=3.0) == 0.0


def test_seconds_until_next_lookup_never_returns_a_negative_wait():
    assert seconds_until_next_lookup(100.0, now=1_000.0, min_interval=3.0) == 0.0
