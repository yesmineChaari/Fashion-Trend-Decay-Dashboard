from unittest.mock import MagicMock

import pandas as pd
import pytest

from fashion_trends.ingest import batching as batching_module
from fashion_trends.ingest.batching import (
    build_batches,
    collect_normalized_trends,
    is_low_resolution,
    rescale_batches,
)
from fashion_trends.keywords import Trend
from fashion_trends.settings import Settings

# A synthetic placeholder, deliberately not the real `Settings.anchor_keyword`
# default — these tests exercise the rescaling math, not the anchor choice.
ANCHOR = "anchor keyword"


def _trend(id_, keyword, isolate=False):
    return Trend(
        id=id_,
        keyword=keyword,
        display_name=keyword.title(),
        category="aesthetic",
        notes="test",
        isolate=isolate,
    )


def _dates(n):
    return pd.to_datetime([f"2026-01-{i + 1:02d}" for i in range(n)])


# ---- build_batches ----------------------------------------------------


def test_build_batches_includes_anchor_in_every_batch():
    trends = [_trend("a", "kw a"), _trend("b", "kw b")]

    batches = build_batches(trends, ANCHOR)

    assert all(batch[0] == ANCHOR for batch in batches)


def test_build_batches_isolates_flagged_trends_into_their_own_batch():
    trends = [
        _trend("mob", "mob wife"),
        _trend("demure", "demure", isolate=True),
        _trend("labubu", "labubu", isolate=True),
    ]

    batches = build_batches(trends, ANCHOR, max_batch_keywords=5)

    assert [ANCHOR, "demure"] in batches
    assert [ANCHOR, "labubu"] in batches
    assert [ANCHOR, "mob wife"] in batches
    assert len(batches) == 3


def test_build_batches_respects_max_batch_keywords():
    trends = [_trend(str(i), f"kw {i}") for i in range(5)]

    batches = build_batches(trends, ANCHOR, max_batch_keywords=3)

    assert all(len(batch) <= 3 for batch in batches)
    assert sum(len(batch) - 1 for batch in batches) == 5
    assert len(batches) == 3  # 2 + 2 + 1 trend keywords, capacity 2 per batch


def test_build_batches_rejects_capacity_below_one():
    with pytest.raises(ValueError, match="at least one trend keyword"):
        build_batches([_trend("a", "kw a")], ANCHOR, max_batch_keywords=1)


# ---- rescale_batches ----------------------------------------------------


def test_rescale_batches_uses_anchor_peak_ratio_on_overlapping_keyword():
    # Batch 0 is best-resolved for the anchor (peak 50); batch 1's anchor is
    # crushed to a peak of 25 by a dominant batchmate.
    batch0 = pd.DataFrame(
        {ANCHOR: [10, 50, 20], "kw ref": [5, 25, 10]}, index=_dates(3)
    )
    batch1 = pd.DataFrame(
        {ANCHOR: [5, 25, 12], "kw other": [2, 25, 8]}, index=_dates(3)
    )

    rescaled = rescale_batches([batch0, batch1], ANCHOR)

    # batch0 is auto-selected as reference (higher anchor peak) -> unchanged
    # in value (ratio 1.0 promotes it to float64, which is fine).
    pd.testing.assert_frame_equal(rescaled[0], batch0, check_dtype=False)
    # batch1 is rescaled by 50/25 = 2.0.
    assert list(rescaled[1]["kw other"]) == [4, 50, 16]
    assert list(rescaled[1][ANCHOR]) == [10, 50, 24]


def test_rescale_batches_auto_selects_best_resolved_anchor_as_reference():
    isolate_batch = pd.DataFrame({ANCHOR: [1, 2], "demure": [50, 100]}, index=_dates(2))
    shared_batch = pd.DataFrame({ANCHOR: [40, 100], "mob wife": [20, 80]}, index=_dates(2))

    # Isolate batch listed first, as build_batches would order it — the
    # reference must still be the shared batch (higher anchor peak: 100 > 2).
    rescaled = rescale_batches([isolate_batch, shared_batch], ANCHOR)

    pd.testing.assert_frame_equal(rescaled[1], shared_batch, check_dtype=False)
    ratio = 100 / 2
    assert list(rescaled[0]["demure"]) == [50 * ratio, 100 * ratio]


def test_rescale_batches_raises_on_zero_anchor_peak():
    batch = pd.DataFrame({ANCHOR: [0, 0], "kw": [0, 0]}, index=_dates(2))

    with pytest.raises(ValueError, match="zero peak"):
        rescale_batches([batch], ANCHOR)


def test_rescale_batches_empty_input_returns_empty_list():
    assert rescale_batches([], ANCHOR) == []


# ---- is_low_resolution ----------------------------------------------------


def test_is_low_resolution_flags_series_below_threshold():
    series = pd.Series([0, 1, 2, 3])

    assert is_low_resolution(series, threshold=5.0) is True


def test_is_low_resolution_does_not_flag_series_at_or_above_threshold():
    series = pd.Series([0, 10, 40, 100])

    assert is_low_resolution(series, threshold=5.0) is False


# ---- collect_normalized_trends ----------------------------------------------------


def test_collect_normalized_trends_flags_low_resolution_and_keeps_raw(monkeypatch):
    trends = [
        _trend("mob", "mob wife"),
        _trend("demure", "demure", isolate=True),
    ]
    settings = Settings(
        anchor_keyword=ANCHOR,
        max_batch_keywords=5,
        low_resolution_threshold=5.0,
        request_delay_seconds=0.0,
        max_retries=0,
    )

    demure_batch = pd.DataFrame({ANCHOR: [1, 2], "demure": [50, 100]}, index=_dates(2))
    mob_batch = pd.DataFrame({ANCHOR: [40, 100], "mob wife": [1, 3]}, index=_dates(2))

    fetch = MagicMock(side_effect=[demure_batch, mob_batch])
    monkeypatch.setattr(batching_module, "fetch_interest_over_time", fetch)

    result = collect_normalized_trends(trends, settings)

    assert fetch.call_count == 2
    assert result.batches == [[ANCHOR, "demure"], [ANCHOR, "mob wife"]]
    assert set(result.trends) == {"demure", "mob wife"}

    # mob batch (anchor peak 100) is best-resolved -> stays the reference.
    assert list(result.trends["mob wife"].rescaled) == [1, 3]
    assert list(result.trends["mob wife"].raw) == [1, 3]

    # demure batch rescaled by 100/2 = 50.
    assert list(result.trends["demure"].rescaled) == [2500, 5000]
    assert list(result.trends["demure"].raw) == [50, 100]

    # mob wife's rescaled peak (3) is below the threshold (5) -> flagged.
    assert result.trends["mob wife"].low_resolution is True
    assert result.trends["demure"].low_resolution is False
    assert result.low_resolution_keywords == ["mob wife"]
