"""Shared matplotlib theme and figure-saving conventions.

One styling module so every exported chart reads as part of the same
project rather than whatever the module that drew it happened to choose that
day. `apply_theme` is the only place that touches `matplotlib.rcParams`, and
`category_style` is the only place a catalog category maps to a colour — no
other `viz` module should set an rcParam or hardcode a colour itself.

`save_figure` is the other half of the contract: it stamps every saved
figure with a standard footer naming the data source, the pull date, and the
timeframe queried, so a chart can't ship without saying when its numbers are
from. A chart of "% dropped since peak" with no visible as-of date is
misleading the moment it's a week old, and this is what makes leaving the
footer off not an option. This module never reads `data/` itself — the pull
date and timeframe are passed in by the caller, which already has them from
whatever manifest or metrics row it built the figure from — so this module
stays a pure styling layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import matplotlib

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

# Okabe-Ito palette: chosen because it stays distinguishable under every
# common form of colour-vision deficiency, not just typical vision. Keyed to
# `fashion_trends.keywords.VALID_CATEGORIES`; `category_style` falls back to
# `FALLBACK_*` for anything outside that set.
CATEGORY_COLORS: dict[str, str] = {
    "aesthetic": "#0072B2",  # blue
    "garment": "#D55E00",  # vermillion
    "accessory": "#009E73",  # bluish green
    "styling": "#E69F00",  # orange
}
FALLBACK_COLOR = "#000000"

# Colour is never the only signal a series carries: linestyle and marker
# repeat the same category distinction, so a figure still separates its
# series correctly in greyscale print or for a reader who can't rely on hue.
CATEGORY_LINESTYLES: dict[str, str] = {
    "aesthetic": "-",
    "garment": "--",
    "accessory": "-.",
    "styling": ":",
}
FALLBACK_LINESTYLE = "-"

CATEGORY_MARKERS: dict[str, str] = {
    "aesthetic": "o",
    "garment": "s",
    "accessory": "^",
    "styling": "D",
}
FALLBACK_MARKER = "x"

# A second Okabe-Ito-derived palette, kept separate from `CATEGORY_COLORS`
# because a chart that colours by lifecycle status (see
# `fashion_trends.viz.rankings`) never also colours by category in the same
# figure — reusing the category hues for a different meaning would only
# invite a reader to conflate the two. Keyed to
# `fashion_trends.metrics.status`'s `STATUS_*` constants; `status_style`
# falls back to `FALLBACK_STATUS_COLOR` for anything outside that set.
STATUS_COLORS: dict[str, str] = {
    "collapsed": "#D55E00",  # vermillion
    "declining": "#0072B2",  # blue
    "stabilized": "#009E73",  # bluish green
    "revived": "#E69F00",  # orange
    "pre_peak": "#CCCCCC",  # light grey
    "unknown": "#999999",  # mid grey
}
FALLBACK_STATUS_COLOR = "#000000"

FIGURE_SIZE = (10.0, 6.0)
FIGURE_DPI = 150
FONT_FAMILY = "sans-serif"

# Preference order, not a requirement: matplotlib walks this list and takes
# the first face actually installed, falling back to its bundled DejaVu Sans.
# Inter is the dashboard's interface font (see
# `fashion_trends.app.styles.BODY_FONT`), so on a machine that has it the
# figures and the page around them set in the same typeface.
FONT_STACK = ["Inter", "Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"]

# Paper-white plotting surface on the warm off-white the dashboard uses for
# its page ground: a figure then reads as a card sitting on the page rather
# than a rectangle pasted onto it.
FIGURE_FACECOLOR = "#FFFFFF"

# Chart furniture recedes and data advances: a hairline grid, no top or right
# spine at all, and no tick marks. Every value here is deliberately lighter
# than matplotlib's default — the previous mid-grey grid competed with the
# faint decay-curve lines drawn on top of it.
GRID_COLOR = "#EAE5DD"
GRID_LINEWIDTH = 0.8
SPINE_COLOR = "#D8D1C6"
TEXT_COLOR = "#1F1C1A"
MUTED_TEXT_COLOR = "#6B645C"

FOOTER_FONTSIZE = 8
FOOTER_COLOR = "#928A80"


def apply_theme() -> None:
    """Set the shared rcParams every figure in the project should draw with.

    Call once, before building any figure. Covers palette, typography, grid
    and spine style, figure size, and DPI, so a chart module never needs
    `plt.rcParams[...] =` or a bare hex colour of its own — pull a per-series
    style from `category_style` instead, which already matches this palette.

    Titles are left-aligned rather than centred: every figure here is read
    alongside a heading and a paragraph of explanation in the dashboard (see
    `fashion_trends.app.explainers`), and a left-aligned title lines up with
    that column of text instead of floating over the middle of the axes.
    """
    matplotlib.rcParams.update(
        {
            "figure.figsize": FIGURE_SIZE,
            "figure.dpi": FIGURE_DPI,
            "figure.facecolor": FIGURE_FACECOLOR,
            "savefig.dpi": FIGURE_DPI,
            "savefig.bbox": "tight",
            "savefig.facecolor": FIGURE_FACECOLOR,
            "font.family": FONT_FAMILY,
            "font.sans-serif": FONT_STACK,
            "font.size": 10.5,
            "axes.facecolor": FIGURE_FACECOLOR,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": GRID_COLOR,
            "grid.linewidth": GRID_LINEWIDTH,
            "axes.edgecolor": SPINE_COLOR,
            "axes.linewidth": 1.0,
            "axes.labelcolor": MUTED_TEXT_COLOR,
            "axes.labelsize": 10,
            "axes.labelpad": 8,
            "axes.titlesize": 14,
            "axes.titleweight": "semibold",
            "axes.titlelocation": "left",
            "axes.titlepad": 14,
            "axes.titlecolor": TEXT_COLOR,
            "text.color": TEXT_COLOR,
            "xtick.color": MUTED_TEXT_COLOR,
            "ytick.color": MUTED_TEXT_COLOR,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "xtick.major.size": 0,
            "ytick.major.size": 0,
            "legend.frameon": True,
            "legend.framealpha": 0.94,
            "legend.facecolor": FIGURE_FACECOLOR,
            "legend.edgecolor": GRID_COLOR,
            "legend.borderpad": 0.7,
            "legend.labelspacing": 0.5,
            "axes.prop_cycle": matplotlib.cycler(color=list(CATEGORY_COLORS.values())),
        }
    )


def bar_chart_grid(ax: Axes) -> None:
    """Restrict the grid to the value axis of a horizontal bar chart.

    `apply_theme` turns the grid on for both axes, which is right for a line
    chart and wrong for `barh`: a horizontal rule running through the middle
    of every bar gives a reader no reference they can use and visibly stripes
    the bars. The vertical rules behind them do carry meaning — they are the
    scale each bar is read against — so those stay.
    """
    ax.grid(axis="x", visible=True)
    ax.grid(axis="y", visible=False)


def line_chart_grid(ax: Axes) -> None:
    """Restrict the grid to the y axis of a time-series or decay-curve chart.

    The y axis on these charts is the quantity being compared (interest, or
    percent of peak) and benefits from horizontal rules to read values
    against. The x axis is time, already carrying its own reference marks
    (the peak line at week 0, the tick labels), so vertical rules only add
    crosshatching behind the lines that matter.
    """
    ax.grid(axis="y", visible=True)
    ax.grid(axis="x", visible=False)


def category_style(category: str) -> dict[str, str]:
    """Colour, linestyle, and marker for one catalog category.

    Falls back to a distinct neutral style for a category outside
    `fashion_trends.keywords.VALID_CATEGORIES` rather than raising — a chart
    is still more useful drawn with a flagged style than not drawn at all
    over a catalog typo.
    """
    return {
        "color": CATEGORY_COLORS.get(category, FALLBACK_COLOR),
        "linestyle": CATEGORY_LINESTYLES.get(category, FALLBACK_LINESTYLE),
        "marker": CATEGORY_MARKERS.get(category, FALLBACK_MARKER),
    }


def status_style(status: str) -> str:
    """Colour for one `fashion_trends.metrics.status` lifecycle label.

    Falls back to `FALLBACK_STATUS_COLOR` for a status outside `STATUS_COLORS`
    rather than raising — see `category_style`'s docstring for why.
    """
    return STATUS_COLORS.get(status, FALLBACK_STATUS_COLOR)


def _format_pull_date(pull_date: Any) -> str:
    if hasattr(pull_date, "date"):
        return pull_date.date().isoformat()
    return str(pull_date)


def save_figure(
    fig: Figure,
    path: Path | str,
    *,
    pull_date: Any,
    timeframe: str,
    source: str = "Google Trends",
) -> Path:
    """Stamp `fig` with a standard footer and write it to `path`.

    The footer names `source`, `pull_date` (a `date`/`Timestamp`, or any
    value already formatted as a string), and `timeframe` — the same request
    shape recorded in `data/processed/manifest.json` for the run that
    produced the figure's numbers. Creates `path`'s parent directory if
    needed, so a chart module never has to remember to do so itself.

    This is the only sanctioned way to write a figure to `outputs/figures/`:
    a figure saved with `fig.savefig` directly ships with no footer, no
    matter how careful the rest of that module is.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    footer = f"Source: {source}  ·  Pulled {_format_pull_date(pull_date)}  ·  Window: {timeframe}"
    fig.text(0.01, 0.01, footer, ha="left", va="bottom", fontsize=FOOTER_FONTSIZE, color=FOOTER_COLOR)

    savefig_kwargs: dict[str, Any] = {}
    if path.suffix.lower() == ".svg":
        # Matplotlib's SVG writer stamps the current wall-clock date into the
        # file's metadata, and salts every clip-path/gradient id with a random
        # UUID generated fresh per process, unless told not to — either one
        # would make two runs against unchanged data produce different bytes.
        savefig_kwargs["metadata"] = {"Date": None}
        matplotlib.rcParams["svg.hashsalt"] = "fashion-trends"
    fig.savefig(path, **savefig_kwargs)
    return path
