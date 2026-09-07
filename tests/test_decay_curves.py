import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pytest

from fashion_trends import metrics as metrics_module
from fashion_trends.keywords import Trend
from fashion_trends.metrics import compute_all
from fashion_trends.settings import Settings
from fashion_trends.viz.decay_curves import (
    DEFAULT_FILENAME,
    build_decay_curve_frame,
    plot_decay_curves,
    plot_decay_curves_interactive,
    save_decay_curves_figure,
    select_highlighted_trends,
)


def _trend(id_, keyword, category="aesthetic"):
    return Trend(id=id_, keyword=keyword, display_name=keyword.title(), category=category, notes="t")


def _dates(n, start="2020-01-05"):
    return pd.date_range(start, periods=n, freq="W-SUN")


def _series_rows(trend_id, keyword, display_name, category, values, start="2020-01-05"):
    return pd.DataFrame(
        {
            "date": _dates(len(values), start=start),
            "trend_id": trend_id,
            "keyword": keyword,
            "display_name": display_name,
            "category": category,
            "interest_raw": values,
            "interest_smooth": values,
            "low_resolution": False,
        }
    )


# Flat lead-in long enough to keep the peak away from either edge of the
# window -- otherwise `peaks.detect_peak` flags it `peak_at_boundary` and it
# gets excluded from the overlay along with the pre-peak trend.
_LEAD_PAD = [5.0] * 6


# A clean fast collapse: sharp rise, then a steep exponential fall well past
# its own half-life within the window.
def _fast_collapse_values():
    rise = [10.0, 40.0, 90.0]
    decay = [100.0 * (0.6**week) for week in range(1, 40)]
    return _LEAD_PAD + rise + decay


# A clean slow fade: rises, dips modestly, and never crosses half its peak
# within the window.
def _slow_fade_values():
    rise = [10.0, 40.0, 90.0]
    decay = [100.0 * (0.99**week) for week in range(1, 40)]
    return _LEAD_PAD + rise + decay


# Still climbing at the end of the window -- pre_peak.
def _still_rising_values():
    return [10.0, 20.0, 30.0, 40.0, 55.0, 70.0, 90.0]


@pytest.fixture
def catalog(monkeypatch):
    trends = [
        _trend("fast", "fast trend"),
        _trend("slow", "slow trend"),
        _trend("rising", "rising trend"),
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
        ],
        ignore_index=True,
    )


@pytest.fixture
def metrics(series):
    return compute_all(series, Settings())


# ---- build_decay_curve_frame ----------------------------------------------------


def test_frame_excludes_pre_peak_trends(metrics, series):
    frame = build_decay_curve_frame(series, metrics)

    assert "rising" not in set(frame["trend_id"])


def test_frame_keeps_eligible_trends(metrics, series):
    frame = build_decay_curve_frame(series, metrics)

    assert {"fast", "slow"} <= set(frame["trend_id"])


def test_frame_aligns_each_trends_own_peak_to_week_zero_at_100_pct(metrics, series):
    frame = build_decay_curve_frame(series, metrics)

    fast_at_peak = frame[(frame["trend_id"] == "fast") & (frame["weeks_since_peak"] == 0)]
    assert len(fast_at_peak) == 1
    assert fast_at_peak["pct_of_peak"].iloc[0] == pytest.approx(100.0)


def test_frame_includes_lead_in_weeks_before_the_peak(metrics, series):
    frame = build_decay_curve_frame(series, metrics)

    fast = frame[frame["trend_id"] == "fast"]
    assert (fast["weeks_since_peak"] < 0).any()


# ---- select_highlighted_trends ----------------------------------------------------


def test_highlighted_trends_include_the_fastest_collapse(metrics):
    highlighted = select_highlighted_trends(metrics)

    assert "fast" in highlighted


def test_highlighted_trends_include_the_slowest_fade(metrics):
    highlighted = select_highlighted_trends(metrics)

    assert "slow" in highlighted


def test_highlighted_trends_exclude_pre_peak_trends(metrics):
    highlighted = select_highlighted_trends(metrics)

    assert "rising" not in highlighted


# ---- plot_decay_curves ----------------------------------------------------


def test_plot_decay_curves_draws_one_line_per_eligible_trend(metrics, series):
    fig = plot_decay_curves(series, metrics)

    ax = fig.axes[0]
    # One line per eligible trend, plus the 0% axvline and 50% axhline
    # reference lines.
    assert len(ax.lines) == 2 + 2


def test_plot_decay_curves_captions_the_excluded_trend(metrics, series):
    fig = plot_decay_curves(series, metrics)

    caption_texts = [child.get_text() for child in fig.texts]
    assert any("Rising Trend" in text for text in caption_texts)


def test_plot_decay_curves_labels_only_the_highlighted_lines(metrics, series):
    fig = plot_decay_curves(series, metrics)

    ax = fig.axes[0]
    legend_labels = {text.get_text() for text in ax.get_legend().get_texts()}
    assert legend_labels == {"Fast Trend", "Slow Trend"}


# ---- plot_decay_curves_interactive ----------------------------------------------------


def test_plot_decay_curves_interactive_draws_one_trace_per_eligible_trend(metrics, series):
    fig = plot_decay_curves_interactive(series, metrics)

    # The 0% and 50% reference lines are layout shapes, not traces, so this
    # is exactly one trace per eligible trend (the pre-peak trend excluded).
    assert len(fig.data) == 2
    assert {trace.name for trace in fig.data} == {"Fast Trend", "Slow Trend"}


def test_plot_decay_curves_interactive_captions_the_excluded_trend(metrics, series):
    fig = plot_decay_curves_interactive(series, metrics)

    caption_texts = [annotation.text for annotation in fig.layout.annotations]
    assert any("Rising Trend" in text for text in caption_texts)


def test_plot_decay_curves_interactive_labels_only_the_highlighted_lines(metrics, series):
    fig = plot_decay_curves_interactive(series, metrics)

    legend_labels = {trace.name for trace in fig.data if trace.showlegend is not False}
    assert legend_labels == {"Fast Trend", "Slow Trend"}


# ---- save_decay_curves_figure ----------------------------------------------------


def test_save_decay_curves_figure_writes_to_the_configured_figures_dir(metrics, series, tmp_path):
    settings = Settings(figures_dir=tmp_path / "figures")

    result = save_decay_curves_figure(series, metrics, settings)

    assert result == tmp_path / "figures" / DEFAULT_FILENAME
    assert result.exists()


def test_save_decay_curves_figure_passes_provenance_from_metrics(metrics, series, tmp_path, monkeypatch):
    settings = Settings(figures_dir=tmp_path / "figures")
    captured = {}

    def _fake_save_figure(fig, path, *, pull_date, timeframe, **kwargs):
        captured["pull_date"] = pull_date
        captured["timeframe"] = timeframe
        return path

    monkeypatch.setattr("fashion_trends.viz.decay_curves.save_figure", _fake_save_figure)

    save_decay_curves_figure(series, metrics, settings)

    assert captured["pull_date"] == metrics["data_pull_date"].iloc[0]
    assert captured["timeframe"] == metrics["timeframe"].iloc[0]
