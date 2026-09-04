import matplotlib

matplotlib.use("Agg")

from datetime import date

import matplotlib.pyplot as plt
import pandas as pd

from fashion_trends.keywords import VALID_CATEGORIES
from fashion_trends.viz.theme import (
    CATEGORY_COLORS,
    CATEGORY_LINESTYLES,
    CATEGORY_MARKERS,
    FALLBACK_COLOR,
    FALLBACK_LINESTYLE,
    FALLBACK_MARKER,
    apply_theme,
    category_style,
    save_figure,
)


# ---- category_style ----------------------------------------------------


def test_every_valid_category_has_its_own_color():
    colors = {category_style(category)["color"] for category in VALID_CATEGORIES}

    assert len(colors) == len(VALID_CATEGORIES)


def test_every_valid_category_has_its_own_linestyle_and_marker():
    # Colour is never the only signal: linestyle and marker must also
    # distinguish categories so figures survive greyscale printing.
    linestyles = {category_style(category)["linestyle"] for category in VALID_CATEGORIES}
    markers = {category_style(category)["marker"] for category in VALID_CATEGORIES}

    assert len(linestyles) == len(VALID_CATEGORIES)
    assert len(markers) == len(VALID_CATEGORIES)


def test_category_style_matches_the_published_lookup_tables():
    style = category_style("aesthetic")

    assert style == {
        "color": CATEGORY_COLORS["aesthetic"],
        "linestyle": CATEGORY_LINESTYLES["aesthetic"],
        "marker": CATEGORY_MARKERS["aesthetic"],
    }


def test_category_style_falls_back_for_an_unknown_category():
    # A catalog typo should still produce a drawable style, not a KeyError.
    style = category_style("not_a_real_category")

    assert style == {
        "color": FALLBACK_COLOR,
        "linestyle": FALLBACK_LINESTYLE,
        "marker": FALLBACK_MARKER,
    }


# ---- apply_theme ----------------------------------------------------


def test_apply_theme_sets_grid_and_figure_rcparams():
    apply_theme()

    assert matplotlib.rcParams["axes.grid"] is True
    assert matplotlib.rcParams["figure.dpi"] == 150
    assert matplotlib.rcParams["savefig.dpi"] == 150


def test_apply_theme_cycles_through_the_category_palette():
    apply_theme()

    cycle_colors = [entry["color"] for entry in matplotlib.rcParams["axes.prop_cycle"]]

    assert cycle_colors == list(CATEGORY_COLORS.values())


# ---- save_figure ----------------------------------------------------


def _line_figure():
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [1, 4, 9])
    return fig


def test_save_figure_creates_parent_directories(tmp_path):
    out_path = tmp_path / "nested" / "dir" / "chart.png"
    fig = _line_figure()

    result = save_figure(fig, out_path, pull_date=date(2026, 9, 1), timeframe="today 5-y")

    assert result == out_path
    assert out_path.exists()


def test_save_figure_stamps_a_source_and_pull_date_footer(tmp_path):
    fig = _line_figure()

    save_figure(fig, tmp_path / "chart.png", pull_date=date(2026, 9, 1), timeframe="today 5-y")

    footer_texts = [child.get_text() for child in fig.texts]
    assert any("Google Trends" in text and "2026-09-01" in text for text in footer_texts)


def test_save_figure_accepts_a_pandas_timestamp(tmp_path):
    fig = _line_figure()

    save_figure(
        fig,
        tmp_path / "chart.png",
        pull_date=pd.Timestamp("2026-09-01"),
        timeframe="today 5-y",
    )

    footer_texts = [child.get_text() for child in fig.texts]
    assert any("2026-09-01" in text for text in footer_texts)


def test_save_figure_uses_a_custom_source_label(tmp_path):
    fig = _line_figure()

    save_figure(
        fig,
        tmp_path / "chart.png",
        pull_date="2026-09-01",
        timeframe="today 5-y",
        source="Custom Source",
    )

    footer_texts = [child.get_text() for child in fig.texts]
    assert any("Custom Source" in text for text in footer_texts)
