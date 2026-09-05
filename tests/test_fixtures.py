import pandas as pd
import pytest

from fashion_trends.ingest import fixtures, pytrends_client
from fashion_trends.ingest.batching import collect_normalized_trends
from fashion_trends.keywords import load_trends
from fashion_trends.settings import Settings


def test_fetch_interest_over_time_returns_requested_columns_in_order():
    frame = fixtures.fetch_interest_over_time(["mob wife", "haute couture"])

    assert list(frame.columns) == ["mob wife", "haute couture"]
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert len(frame) > 0


def test_fetch_interest_over_time_raises_for_unknown_keyword():
    with pytest.raises(fixtures.FixtureNotFoundError, match="not a real keyword"):
        fixtures.fetch_interest_over_time(["not a real keyword"])


def test_captured_at_and_pytrends_version_come_from_manifest():
    assert fixtures.captured_at()
    assert fixtures.pytrends_version()


def test_manifest_documents_every_column_in_the_fixture_table():
    manifest = fixtures._manifest()
    documented = set(manifest["real_keywords"]) | set(manifest["synthetic_keywords"])

    assert documented == set(fixtures._table().columns)


def test_fixture_table_covers_the_full_trend_catalog_and_anchor():
    trends = load_trends()
    table_columns = set(fixtures._table().columns)

    assert {t.keyword for t in trends} <= table_columns
    assert Settings().anchor_keyword in table_columns


# ---- the required awkward cases (KAN-16 acceptance criteria) --------------


def test_still_rising_fixture_has_no_peak_inside_the_window():
    series = fixtures.fetch_interest_over_time(["fixture_still_rising"])["fixture_still_rising"]

    assert series.idxmax() == series.index[-1]


def test_spiky_fixture_has_a_single_week_false_peak():
    series = fixtures.fetch_interest_over_time(["fixture_spiky_false_peak"])["fixture_spiky_false_peak"]
    baseline = series.drop(series.idxmax())

    assert series.max() > baseline.max() * 5
    assert (baseline == baseline.iloc[0]).all()


def test_near_zero_fixture_stays_below_the_low_resolution_threshold():
    series = fixtures.fetch_interest_over_time(["fixture_near_zero"])["fixture_near_zero"]

    assert series.max() < Settings().low_resolution_threshold


def test_bag_charm_catalog_entry_covers_the_revival_two_peak_case():
    series = fixtures.fetch_interest_over_time(["bag charm"])["bag charm"]
    first_peak_idx = series.idxmax()
    trough = series[series.index > first_peak_idx].min()
    second_half_peak = series[series.index > first_peak_idx].max()

    # A real trough well below both surrounding highs is what makes this a
    # revival shape rather than one long, gently-declining peak.
    assert trough < second_half_peak * 0.5
    assert trough < series.max() * 0.5


# ---- full pipeline offline (KAN-16 acceptance criteria) -------------------


def test_collect_normalized_trends_runs_end_to_end_with_networking_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pytrends_client,
        "fetch_interest_over_time",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fixture mode must never touch the network")),
    )
    trends = load_trends()
    settings = Settings(fixture_mode=True, data_raw_dir=tmp_path)

    result = collect_normalized_trends(trends, settings)

    assert set(result.trends) == {t.keyword for t in trends}
    assert not (tmp_path / "cache").exists()
    assert (tmp_path / "manifest.json").exists()
