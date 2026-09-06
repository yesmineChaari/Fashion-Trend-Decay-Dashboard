"""The two ranking figures: drop from peak, and time to 50% decline.

Every row of `metrics` ends up somewhere in each figure, as a bar or named in
a caption explaining why it isn't one, so a reader is never left to wonder
what happened to a trend they expected to see.

**Drop ranking** (`plot_drop_ranking`) excludes `pre_peak` trends and any
trend whose `pct_dropped` came back null for another reason, both named in
the caption.

**Time to decline** (`plot_time_to_decline`) draws `crossed` trends as the
ranked bars, `still_above_half` trends in their own shaded block below, and
names `pre_peak`/`unknown` trends in the caption.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd

from fashion_trends.metrics.decay import (
    HALF_LIFE_CROSSED,
    HALF_LIFE_PRE_PEAK,
    HALF_LIFE_STILL_ABOVE,
    HALF_LIFE_UNKNOWN,
)
from fashion_trends.metrics.status import (
    STATUS_COLLAPSED,
    STATUS_DECLINING,
    STATUS_REVIVED,
    STATUS_STABILIZED,
)
from fashion_trends.settings import Settings
from fashion_trends.viz.theme import apply_theme, bar_chart_grid, save_figure, status_style

if TYPE_CHECKING:
    from matplotlib.figure import Figure

DROP_RANKING_FILENAME = "drop_ranking.png"
TIME_TO_DECLINE_FILENAME = "time_to_decline.png"

BAR_HEIGHT = 0.6
VALUE_LABEL_GAP = 1.5
MIN_FIGURE_HEIGHT = 3.0
HEIGHT_PER_BAR = 0.4
FIGURE_WIDTH = 10.0

STILL_ABOVE_COLOR = "#999999"
STILL_ABOVE_HATCH = "//"
CAPTION_FONTSIZE = 7
CAPTION_COLOR = "#6B645C"
VALUE_LABEL_COLOR = "#1F1C1A"


# Fixed legend order for the drop ranking's status swatches.
_STATUS_LEGEND_ORDER = (STATUS_COLLAPSED, STATUS_DECLINING, STATUS_STABILIZED, STATUS_REVIVED)


def _figure_height(n_bars: int) -> float:
    return max(MIN_FIGURE_HEIGHT, HEIGHT_PER_BAR * n_bars + 1.5)


def _peak_label(display_name: str, peak_date: pd.Timestamp | None) -> str:
    """A y-tick label naming a trend and, if known, the year and month it peaked."""
    if pd.isna(peak_date):
        return display_name
    return f"{display_name}, peak {peak_date:%b %Y}"


# ---- drop ranking ----------------------------------------------------


def build_drop_ranking_frame(metrics: pd.DataFrame) -> pd.DataFrame:
    """Metrics rows rankable by `pct_dropped`, sorted descending (worst first).

    Excludes `pre_peak` trends and any other trend whose `pct_dropped` is
    null. See `drop_ranking_caption`.
    """
    rankable = metrics[~metrics["pre_peak"] & metrics["pct_dropped"].notna()]
    return rankable.sort_values("pct_dropped", ascending=False)


def drop_ranking_caption(metrics: pd.DataFrame) -> str:
    """Caption naming every trend left out of the drop ranking, and why."""
    lines = []

    pre_peak = metrics[metrics["pre_peak"]]
    if not pre_peak.empty:
        names = ", ".join(sorted(pre_peak["display_name"]))
        lines.append(f"Excluded (still rising, no drop to measure yet): {names}")

    no_metric = metrics[~metrics["pre_peak"] & metrics["pct_dropped"].isna()]
    if not no_metric.empty:
        names = ", ".join(sorted(no_metric["display_name"]))
        lines.append(f"% drop unavailable (no usable peak detected): {names}")

    return "\n".join(lines)


def plot_drop_ranking(metrics: pd.DataFrame) -> Figure:
    """Build the ranked % drop chart. See the module docstring."""
    apply_theme()
    # Reversed so the biggest drop lands at the top: `barh` stacks bottom-up.
    ranked = build_drop_ranking_frame(metrics).iloc[::-1].reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, _figure_height(len(ranked))))
    bar_chart_grid(ax)

    y_positions = range(len(ranked))
    colors = [status_style(status) for status in ranked["status"]]
    ax.barh(y_positions, ranked["pct_dropped"], color=colors, height=BAR_HEIGHT, zorder=2)

    for y, pct in zip(y_positions, ranked["pct_dropped"], strict=True):
        ax.text(
            pct + VALUE_LABEL_GAP, y, f"{pct:.0f}%", va="center", fontsize=8.5, fontweight="semibold", color=VALUE_LABEL_COLOR
        )

    ax.set_yticks(list(y_positions))
    ax.set_yticklabels(
        [_peak_label(name, date) for name, date in zip(ranked["display_name"], ranked["peak_date"], strict=True)],
        fontsize=8,
    )
    ax.set_xlim(0, 108)
    ax.set_xlabel("% dropped since peak")
    ax.set_title("Trends ranked by drop from peak")

    present = [status for status in _STATUS_LEGEND_ORDER if status in set(ranked["status"])]
    if present:
        handles = [mpatches.Patch(color=status_style(status), label=status) for status in present]
        ax.legend(handles=handles, loc="lower right", fontsize=8, title="Lifecycle status")

    caption = drop_ranking_caption(metrics)
    if caption:
        fig.text(0.01, 0.04, caption, ha="left", va="bottom", fontsize=CAPTION_FONTSIZE, color=CAPTION_COLOR, style="italic")

    return fig


def save_drop_ranking_figure(metrics: pd.DataFrame, settings: Settings | None = None) -> Path:
    """Build and save the drop ranking chart to `outputs/figures/drop_ranking.png`."""
    settings = settings or Settings()
    fig = plot_drop_ranking(metrics)
    pull_date = metrics["data_pull_date"].iloc[0]
    timeframe = metrics["timeframe"].iloc[0]
    return save_figure(fig, settings.figures_dir / DROP_RANKING_FILENAME, pull_date=pull_date, timeframe=timeframe)


# ---- time to decline ----------------------------------------------------


def build_time_to_decline_frames(metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`(crossed, still_above)` metrics rows for the time-to-decline chart.

    `crossed` is sorted ascending by `weeks_to_half`. `still_above` is sorted
    descending by `weeks_since_peak`. Neither includes `pre_peak`/`unknown`
    trends, see `time_to_decline_caption`.
    """
    crossed = metrics[metrics["time_to_half_status"] == HALF_LIFE_CROSSED]
    crossed = crossed.sort_values("weeks_to_half", ascending=True)

    still_above = metrics[metrics["time_to_half_status"] == HALF_LIFE_STILL_ABOVE]
    still_above = still_above.sort_values("weeks_since_peak", ascending=False)

    return crossed, still_above


def time_to_decline_caption(metrics: pd.DataFrame) -> str:
    """Caption naming every trend left out of both time-to-decline groups, and why."""
    lines = []

    pre_peak = metrics[metrics["time_to_half_status"] == HALF_LIFE_PRE_PEAK]
    if not pre_peak.empty:
        names = ", ".join(sorted(pre_peak["display_name"]))
        lines.append(f"Excluded (still rising, no decay yet): {names}")

    unknown = metrics[metrics["time_to_half_status"] == HALF_LIFE_UNKNOWN]
    if not unknown.empty:
        names = ", ".join(sorted(unknown["display_name"]))
        lines.append(f"Time to decline unavailable (no usable peak detected): {names}")

    return "\n".join(lines)


def plot_time_to_decline(metrics: pd.DataFrame) -> Figure:
    """Build the time-to-50%-decline chart. See the module docstring."""
    apply_theme()
    crossed, still_above = build_time_to_decline_frames(metrics)

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, _figure_height(len(crossed) + len(still_above))))
    bar_chart_grid(ax)

    yticks: list[int] = []
    yticklabels: list[str] = []
    y = 0

    if not still_above.empty:
        band_top = len(still_above) - 0.5
        ax.axhspan(-0.5, band_top, color="#F0F0F0", zorder=0)
        ax.text(
            0.01,
            band_top - 0.1,
            "Never dropped below half their peak (as of pull date), shown separately, not omitted",
            transform=ax.get_yaxis_transform(),
            ha="left",
            va="top",
            fontsize=CAPTION_FONTSIZE,
            style="italic",
            color=CAPTION_COLOR,
            zorder=1,
        )
        for _, row in still_above.iterrows():
            ax.barh(y, row["weeks_since_peak"], color=STILL_ABOVE_COLOR, hatch=STILL_ABOVE_HATCH, height=BAR_HEIGHT, zorder=2)
            ax.text(
                row["weeks_since_peak"] + VALUE_LABEL_GAP,
                y,
                f"{int(row['weeks_since_peak'])}+ wk",
                va="center",
                fontsize=8.5,
                fontweight="semibold",
                color=VALUE_LABEL_COLOR,
            )
            yticks.append(y)
            yticklabels.append(row["display_name"])
            y += 1

        ax.axhline(band_top, color="#333333", linewidth=0.8, linestyle="--", zorder=1)

    # Reversed so the fastest death lands at the top of its section.
    for _, row in crossed.iloc[::-1].iterrows():
        color = status_style(row["status"])
        ax.barh(y, row["weeks_to_half"], color=color, height=BAR_HEIGHT, zorder=2)
        ax.text(
            row["weeks_to_half"] + VALUE_LABEL_GAP,
            y,
            f"{int(row['weeks_to_half'])} wk",
            va="center",
            fontsize=8.5,
            fontweight="semibold",
            color=VALUE_LABEL_COLOR,
        )
        yticks.append(y)
        yticklabels.append(row["display_name"])
        y += 1

    ax.set_yticks(yticks)
    ax.set_yticklabels(yticklabels, fontsize=8)
    ax.set_xlabel("Weeks")
    ax.set_title("Time to 50% decline (fastest first)")

    caption = time_to_decline_caption(metrics)
    if caption:
        fig.text(0.01, 0.01, caption, ha="left", va="bottom", fontsize=CAPTION_FONTSIZE, color=CAPTION_COLOR, style="italic")

    return fig


def save_time_to_decline_figure(metrics: pd.DataFrame, settings: Settings | None = None) -> Path:
    """Build and save the time-to-decline chart to `outputs/figures/time_to_decline.png`."""
    settings = settings or Settings()
    fig = plot_time_to_decline(metrics)
    pull_date = metrics["data_pull_date"].iloc[0]
    timeframe = metrics["timeframe"].iloc[0]
    return save_figure(fig, settings.figures_dir / TIME_TO_DECLINE_FILENAME, pull_date=pull_date, timeframe=timeframe)
