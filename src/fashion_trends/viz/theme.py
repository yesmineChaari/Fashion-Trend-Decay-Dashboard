"""Shared matplotlib theme and figure-saving conventions.

`apply_theme` is the only place that touches `matplotlib.rcParams`, and
`category_style` is the only place a catalog category maps to a colour.
`save_figure` stamps every saved figure with a footer naming the data
source, pull date, and timeframe, so a chart can't ship without saying when
its numbers are from.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import matplotlib

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

# Okabe-Ito palette, distinguishable under colour-vision deficiency. Keyed to
# `fashion_trends.keywords.VALID_CATEGORIES`.
CATEGORY_COLORS: dict[str, str] = {
    "aesthetic": "#0072B2",  # blue
    "garment": "#D55E00",  # vermillion
    "accessory": "#009E73",  # bluish green
    "styling": "#E69F00",  # orange
}
FALLBACK_COLOR = "#000000"

# Linestyle/marker repeat the category distinction for greyscale/colourblind readers.
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
# since colour-by-status and colour-by-category never appear in the same figure.
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

# Preference order; matplotlib takes the first face installed, falling back to DejaVu Sans.
FONT_STACK = ["Inter", "Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"]

FIGURE_FACECOLOR = "#FFFFFF"

# Hairline grid, no top/right spine, no tick marks, lighter than matplotlib's default.
GRID_COLOR = "#EAE5DD"
GRID_LINEWIDTH = 0.8
SPINE_COLOR = "#D8D1C6"
TEXT_COLOR = "#1F1C1A"
MUTED_TEXT_COLOR = "#6B645C"

FOOTER_FONTSIZE = 8
FOOTER_COLOR = "#928A80"


def apply_theme() -> None:
    """Set the shared rcParams every figure in the project should draw with. Call once, before building any figure."""
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
    """Restrict the grid to the value axis of a horizontal bar chart."""
    ax.grid(axis="x", visible=True)
    ax.grid(axis="y", visible=False)


def line_chart_grid(ax: Axes) -> None:
    """Restrict the grid to the y axis of a time-series or decay-curve chart."""
    ax.grid(axis="y", visible=True)
    ax.grid(axis="x", visible=False)


def category_style(category: str) -> dict[str, str]:
    """Colour, linestyle, and marker for one catalog category. Falls back to a neutral style rather than raising."""
    return {
        "color": CATEGORY_COLORS.get(category, FALLBACK_COLOR),
        "linestyle": CATEGORY_LINESTYLES.get(category, FALLBACK_LINESTYLE),
        "marker": CATEGORY_MARKERS.get(category, FALLBACK_MARKER),
    }


def status_style(status: str) -> str:
    """Colour for one `fashion_trends.metrics.status` lifecycle label. Falls back to `FALLBACK_STATUS_COLOR`."""
    return STATUS_COLORS.get(status, FALLBACK_STATUS_COLOR)


# matplotlib linestyle -> Plotly dash style, since `category_style` speaks
# matplotlib's vocabulary and is shared with the static charts.
DASH_BY_LINESTYLE: dict[str, str] = {"-": "solid", "--": "dash", "-.": "dashdot", ":": "dot"}


def plotly_layout_defaults() -> dict[str, Any]:
    """Shared Plotly `update_layout` kwargs mirroring `apply_theme`'s rcParams, for the dashboard's interactive charts.

    Y-axis grid only, no top/right box, hairline colours matching the static
    figures, so a Plotly chart sits next to a matplotlib one without clashing.
    """
    return {
        "plot_bgcolor": FIGURE_FACECOLOR,
        "paper_bgcolor": FIGURE_FACECOLOR,
        "font": {"family": ", ".join(FONT_STACK), "color": TEXT_COLOR, "size": 13},
        "xaxis": {"showgrid": False, "zeroline": False, "linecolor": SPINE_COLOR, "tickfont": {"color": MUTED_TEXT_COLOR}},
        "yaxis": {
            "showgrid": True,
            "gridcolor": GRID_COLOR,
            "zeroline": False,
            "linecolor": SPINE_COLOR,
            "tickfont": {"color": MUTED_TEXT_COLOR},
        },
        "legend": {"bgcolor": FIGURE_FACECOLOR, "bordercolor": GRID_COLOR, "borderwidth": 1},
        "margin": {"t": 60, "l": 60, "r": 20, "b": 60},
        "hovermode": "x unified",
    }


def plotly_caption_annotation(text: str) -> dict[str, Any]:
    """A Plotly layout annotation for a caption pinned to the bottom-left corner, italic like the static charts'.

    Pass to `fig.add_annotation(plotly_caption_annotation(text))`.
    """
    return {
        "text": f"<i>{text}</i>",
        "xref": "paper",
        "yref": "paper",
        "x": 0,
        "y": -0.22,
        "xanchor": "left",
        "yanchor": "top",
        "showarrow": False,
        "align": "left",
        "font": {"size": 11, "color": MUTED_TEXT_COLOR},
    }


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
    """Stamp `fig` with a standard footer naming `source`/`pull_date`/`timeframe` and write it to `path`.

    The only sanctioned way to write a figure to `outputs/figures/`; creates
    `path`'s parent directory if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    footer = f"Source: {source}  ·  Pulled {_format_pull_date(pull_date)}  ·  Window: {timeframe}"
    fig.text(0.01, 0.01, footer, ha="left", va="bottom", fontsize=FOOTER_FONTSIZE, color=FOOTER_COLOR)

    savefig_kwargs: dict[str, Any] = {}
    if path.suffix.lower() == ".svg":
        # Otherwise matplotlib stamps a wall-clock date and a random UUID salt
        # into the SVG, making two runs of unchanged data differ byte-for-byte.
        savefig_kwargs["metadata"] = {"Date": None}
        matplotlib.rcParams["svg.hashsalt"] = "fashion-trends"
    fig.savefig(path, **savefig_kwargs)
    return path
