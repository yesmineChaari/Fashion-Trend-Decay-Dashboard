"""Rebuild every static figure from processed data in one command.

This is what `scripts/build_charts.py` calls. It reads `series.parquet` and
`metrics.parquet` from `settings.data_processed_dir` -- the same two files
`fashion_trends.ingest.pipeline.run_pipeline` writes -- and hands them to each
`viz` module's `plot_*` function, then to `fashion_trends.viz.theme.save_figure`
to write the result out. It makes no network calls and never touches
`data/raw`: producing fresh processed data is `refresh_data.py`'s job, not
this one's.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from fashion_trends.ingest.pipeline import METRICS_FILENAME, SERIES_FILENAME
from fashion_trends.settings import Settings
from fashion_trends.viz.decay_curves import plot_decay_curves
from fashion_trends.viz.rankings import plot_drop_ranking, plot_time_to_decline
from fashion_trends.viz.theme import save_figure

if TYPE_CHECKING:
    from matplotlib.figure import Figure

# Base filename (extension supplied by `--format`) and builder for each
# `--figures` subset name, keyed in the canonical order `build_figures` always
# writes in regardless of the order a caller asks for. `plot_drop_ranking` and
# `plot_time_to_decline` don't need `series`, but every builder here takes
# `(series, metrics)` so the table stays one shape.
_FIGURE_SPECS: dict[str, tuple[str, Callable[[pd.DataFrame, pd.DataFrame], Figure]]] = {
    "decay": ("decay_curves", lambda series, metrics: plot_decay_curves(series, metrics)),
    "ranking": ("drop_ranking", lambda series, metrics: plot_drop_ranking(metrics)),
    "decline": ("time_to_decline", lambda series, metrics: plot_time_to_decline(metrics)),
}

FIGURE_CHOICES: tuple[str, ...] = tuple(_FIGURE_SPECS)
DEFAULT_FORMAT = "png"
SUPPORTED_FORMATS: tuple[str, ...] = ("png", "svg")


class ProcessedDataMissingError(RuntimeError):
    """Raised when `series.parquet`/`metrics.parquet` aren't there to read."""


class UnknownFigureError(ValueError):
    """Raised when `--figures` names something outside `FIGURE_CHOICES`."""


def load_processed_data(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read `series.parquet` and `metrics.parquet` from `settings.data_processed_dir`.

    Raises `ProcessedDataMissingError` naming whichever file is missing and
    pointing at `scripts/refresh_data.py` -- this module only reads processed
    parquet files, it never fetches or derives them itself.
    """
    series_path = settings.data_processed_dir / SERIES_FILENAME
    metrics_path = settings.data_processed_dir / METRICS_FILENAME
    missing = [p for p in (series_path, metrics_path) if not p.exists()]
    if missing:
        raise ProcessedDataMissingError(
            f"missing processed data: {[str(p) for p in missing]} — run scripts/refresh_data.py first to fetch and persist it"
        )
    return pd.read_parquet(series_path), pd.read_parquet(metrics_path)


def stale_data_warning(metrics: pd.DataFrame, settings: Settings) -> str | None:
    """A warning string if `metrics`'s `data_pull_date` is older than the cache TTL, else `None`.

    A chart built on data past its own cache TTL risks being published as a
    "current interest" reading when the numbers behind it are really weeks or
    months old -- see `fashion_trends.settings.Settings.cache_ttl_days`.
    """
    if metrics.empty:
        return None

    pull_date = metrics["data_pull_date"].iloc[0]
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    age_days = (now - pull_date).days
    if age_days <= settings.cache_ttl_days:
        return None

    return (
        f"warning: processed data is {age_days} day(s) old (cache TTL is "
        f"{settings.cache_ttl_days}) — run scripts/refresh_data.py --refresh "
        'before publishing a "current interest" chart'
    )


def build_figures(
    series: pd.DataFrame,
    metrics: pd.DataFrame,
    settings: Settings,
    *,
    figures: tuple[str, ...] = FIGURE_CHOICES,
    outdir: Path | None = None,
    fmt: str = DEFAULT_FORMAT,
) -> list[Path]:
    """Build and save the requested figures, returning the paths written.

    `figures` names a subset of `FIGURE_CHOICES`; the result is always
    written in that canonical order regardless of the order requested, and a
    repeated name is only written once. Raises `UnknownFigureError` for a
    name outside `FIGURE_CHOICES`.

    Figures land in `outdir` (defaulting to `settings.figures_dir`) named
    `<figure>.<fmt>`. `pull_date` and `timeframe` for each figure's footer
    come from `metrics`'s own provenance columns, same as every `save_*_figure`
    helper in `fashion_trends.viz`.
    """
    unknown = sorted(set(figures) - set(FIGURE_CHOICES))
    if unknown:
        raise UnknownFigureError(f"unknown figure(s) {unknown!r} — choose from {FIGURE_CHOICES}")

    outdir = outdir or settings.figures_dir
    pull_date = metrics["data_pull_date"].iloc[0]
    timeframe = metrics["timeframe"].iloc[0]

    requested = set(figures)
    written = []
    for name in FIGURE_CHOICES:
        if name not in requested:
            continue
        base_filename, plot_fn = _FIGURE_SPECS[name]
        fig = plot_fn(series, metrics)
        path = outdir / f"{base_filename}.{fmt}"
        written.append(save_figure(fig, path, pull_date=pull_date, timeframe=timeframe))

    return written
