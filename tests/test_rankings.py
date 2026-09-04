import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pytest

from fashion_trends import metrics as metrics_module
from fashion_trends.keywords import Trend
from fashion_trends.metrics import compute_all
from fashion_trends.metrics.decay import HALF_LIFE_STILL_ABOVE
from fashion_trends.settings import Settings
from fashion_trends.viz.rankings import (
    DROP_RANKING_FILENAME,
    TIME_TO_DECLINE_FILENAME,
    build_drop_ranking_frame,
    build_time_to_decline_frames,
    drop_ranking_caption,
    plot_drop_ranking,
    plot_time_to_decline,
    save_drop_ranking_figure,
    save_time_to_decline_figure,
    time_to_decline_caption,
)


def _trend(id_, keyword, category="aesthetic"):
    return Trend(id=id_, keyword=keyword, display_name=keyword.title(), category=category, notes="t")


def _dates(n, start="2020-01-05"):
    return pd.date_range(start, periods=n, freq="W-SUN")


def _series_rows(trend_id, keyword, display_name, category, raw, smooth=None, start="2020-01-05"):
    return pd.DataFrame(
        {
            "date": _dates(len(raw), start=start),
            "trend_id": trend_id,
            "keyword": keyword,
            "display_name": display_name,
            "category": category,
            "interest_raw": raw,
            "interest_smooth": raw if smooth is None else smooth,
            "low_resolution": False,
        }
    )


_LEAD_PAD = [5.0] * 6


def _fast_collapse_values():
    rise = [10.0, 40.0, 90.0]
    decay = [100.0 * (0.6**week) for week in range(1, 40)]
    return _LEAD_PAD + rise + decay


def _slow_fade_values():
    rise = [10.0, 40.0, 90.0]
    decay = [100.0 * (0.99**week) for week in range(1, 40)]
    return _LEAD_PAD + rise + decay


def _still_rising_values():
    return [10.0, 20.0, 30.0, 40.0, 55.0, 70.0, 90.0]


@pytest.fixture
def catalog(monkeypatch):
    trends = [
        _trend("fast", "fast trend"),
        _trend("slow", "slow trend"),
        _trend("rising", "rising trend"),
        _trend("unknown", "unknown trend"),
    ]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)
    return trends


@pytest.fixture
def series(catalog):
    return pd.concat(
        [
            _series_rows("fast", "fast trend", "Fast Trend", "aesthetic", _fast_collapse_values()),
            _series_rows("slow", "slow trend", "Slow Trend", "garment", _slow_fade_values()),
            _series_rows("rising", "rising trend", "Rising Trend", "accessory", _still_rising_values()),
            _series_rows("unknown", "unknown trend", "Unknown Trend", "styling", [float("nan")] * 10),
        ],
        ignore_index=True,
    )


@pytest.fixture
def metrics(series):
    return compute_all(series, Settings())


# ---- build_drop_ranking_frame ----------------------------------------------------


def test_drop_ranking_excludes_pre_peak_trend(metrics):
    frame = build_drop_ranking_frame(metrics)

    assert "rising" not in set(frame["trend_id"])


def test_drop_ranking_excludes_trend_with_no_usable_peak(metrics):
    frame = build_drop_ranking_frame(metrics)

    assert "unknown" not in set(frame["trend_id"])


def test_drop_ranking_keeps_eligible_trends(metrics):
    frame = build_drop_ranking_frame(metrics)

    assert {"fast", "slow"} <= set(frame["trend_id"])


def test_drop_ranking_sorted_descending_by_pct_dropped(metrics):
    frame = build_drop_ranking_frame(metrics)

    assert list(frame["pct_dropped"]) == sorted(frame["pct_dropped"], reverse=True)


# ---- drop_ranking_caption ----------------------------------------------------


def test_drop_ranking_caption_names_the_pre_peak_trend(metrics):
    caption = drop_ranking_caption(metrics)

    assert "Rising Trend" in caption


def test_drop_ranking_caption_names_the_no_metric_trend(metrics):
    caption = drop_ranking_caption(metrics)

    assert "Unknown Trend" in caption


def test_drop_ranking_caption_empty_when_nothing_excluded(metrics):
    ranked = metrics[metrics["trend_id"].isin(["fast", "slow"])]

    assert drop_ranking_caption(ranked) == ""


# ---- plot_drop_ranking ----------------------------------------------------


def test_plot_drop_ranking_draws_one_bar_per_ranked_trend(metrics):
    fig = plot_drop_ranking(metrics)

    ax = fig.axes[0]
    assert len(ax.containers) == 1
    assert len(ax.containers[0]) == len(build_drop_ranking_frame(metrics))


def test_plot_drop_ranking_labels_carry_the_peak_date(metrics):
    fig = plot_drop_ranking(metrics)

    ax = fig.axes[0]
    labels = [label.get_text() for label in ax.get_yticklabels()]
    assert any("Fast Trend" in label and "peak" in label for label in labels)


def test_plot_drop_ranking_captions_the_excluded_trends(metrics):
    fig = plot_drop_ranking(metrics)

    caption_texts = [child.get_text() for child in fig.texts]
    assert any("Rising Trend" in text and "Unknown Trend" in text for text in caption_texts)


def test_plot_drop_ranking_legend_matches_present_statuses(metrics):
    fig = plot_drop_ranking(metrics)

    ax = fig.axes[0]
    ranked = build_drop_ranking_frame(metrics)
    legend_labels = {text.get_text() for text in ax.get_legend().get_texts()}
    assert legend_labels == set(ranked["status"])


# ---- save_drop_ranking_figure ----------------------------------------------------


def test_save_drop_ranking_figure_writes_to_the_configured_figures_dir(metrics, tmp_path):
    settings = Settings(figures_dir=tmp_path / "figures")

    result = save_drop_ranking_figure(metrics, settings)

    assert result == tmp_path / "figures" / DROP_RANKING_FILENAME
    assert result.exists()


def test_save_drop_ranking_figure_passes_provenance_from_metrics(metrics, tmp_path, monkeypatch):
    settings = Settings(figures_dir=tmp_path / "figures")
    captured = {}

    def _fake_save_figure(fig, path, *, pull_date, timeframe, **kwargs):
        captured["pull_date"] = pull_date
        captured["timeframe"] = timeframe
        return path

    monkeypatch.setattr("fashion_trends.viz.rankings.save_figure", _fake_save_figure)

    save_drop_ranking_figure(metrics, settings)

    assert captured["pull_date"] == metrics["data_pull_date"].iloc[0]
    assert captured["timeframe"] == metrics["timeframe"].iloc[0]


# ---- build_time_to_decline_frames ----------------------------------------------------


def test_time_to_decline_crossed_excludes_pre_peak_and_unknown_and_still_above(metrics):
    crossed, _ = build_time_to_decline_frames(metrics)

    assert set(crossed["trend_id"]) == {"fast"}


def test_time_to_decline_still_above_contains_only_the_never_crossed_trend(metrics):
    _, still_above = build_time_to_decline_frames(metrics)

    assert set(still_above["trend_id"]) == {"slow"}
    assert (still_above["time_to_half_status"] == HALF_LIFE_STILL_ABOVE).all()


def test_time_to_decline_crossed_sorted_ascending_by_weeks_to_half(metrics):
    crossed, _ = build_time_to_decline_frames(metrics)

    assert list(crossed["weeks_to_half"]) == sorted(crossed["weeks_to_half"])


# ---- time_to_decline_caption ----------------------------------------------------


def test_time_to_decline_caption_names_the_pre_peak_trend(metrics):
    caption = time_to_decline_caption(metrics)

    assert "Rising Trend" in caption


def test_time_to_decline_caption_names_the_unknown_trend(metrics):
    caption = time_to_decline_caption(metrics)

    assert "Unknown Trend" in caption


# ---- plot_time_to_decline ----------------------------------------------------


def test_plot_time_to_decline_draws_one_bar_per_crossed_and_still_above_trend(metrics):
    fig = plot_time_to_decline(metrics)

    ax = fig.axes[0]
    total_bars = sum(len(container) for container in ax.containers)
    crossed, still_above = build_time_to_decline_frames(metrics)
    assert total_bars == len(crossed) + len(still_above)


def test_plot_time_to_decline_labels_include_both_groups(metrics):
    fig = plot_time_to_decline(metrics)

    ax = fig.axes[0]
    labels = {label.get_text() for label in ax.get_yticklabels()}
    assert labels == {"Fast Trend", "Slow Trend"}


def test_plot_time_to_decline_draws_a_divider_for_the_still_above_block(metrics):
    fig = plot_time_to_decline(metrics)

    ax = fig.axes[0]
    assert len(ax.lines) >= 1


def test_plot_time_to_decline_captions_the_excluded_trends(metrics):
    fig = plot_time_to_decline(metrics)

    caption_texts = [child.get_text() for child in fig.texts]
    assert any("Rising Trend" in text and "Unknown Trend" in text for text in caption_texts)


# ---- save_time_to_decline_figure ----------------------------------------------------


def test_save_time_to_decline_figure_writes_to_the_configured_figures_dir(metrics, tmp_path):
    settings = Settings(figures_dir=tmp_path / "figures")

    result = save_time_to_decline_figure(metrics, settings)

    assert result == tmp_path / "figures" / TIME_TO_DECLINE_FILENAME
    assert result.exists()


def test_save_time_to_decline_figure_passes_provenance_from_metrics(metrics, tmp_path, monkeypatch):
    settings = Settings(figures_dir=tmp_path / "figures")
    captured = {}

    def _fake_save_figure(fig, path, *, pull_date, timeframe, **kwargs):
        captured["pull_date"] = pull_date
        captured["timeframe"] = timeframe
        return path

    monkeypatch.setattr("fashion_trends.viz.rankings.save_figure", _fake_save_figure)

    save_time_to_decline_figure(metrics, settings)

    assert captured["pull_date"] == metrics["data_pull_date"].iloc[0]
    assert captured["timeframe"] == metrics["timeframe"].iloc[0]
