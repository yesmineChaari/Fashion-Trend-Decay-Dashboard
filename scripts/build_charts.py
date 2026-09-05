#!/usr/bin/env python
"""Rebuild static figures from processed data in one command.

    python scripts/build_charts.py [--figures decay,ranking,decline]
                                    [--outdir PATH] [--format png|svg]

Reads only `data/processed/*.parquet` and makes no network calls — if that
data is missing, run `scripts/refresh_data.py` first.

`--figures`, `--outdir`, and `--format` are run-specific flags handled here;
every other flag (cache-ttl-days, ...) is a `Settings` field and passed
straight through to `fashion_trends.settings.load_settings` — see that module
for the full list.

Exits non-zero if the processed data is missing or an unknown `--figures`
name is given. A stale `data_pull_date` (older than the cache TTL) only
prints a warning to stderr — building slightly-stale charts is still useful,
it just should not be mistaken for current.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fashion_trends.settings import load_settings
from fashion_trends.viz.build import (
    DEFAULT_FORMAT,
    FIGURE_CHOICES,
    SUPPORTED_FORMATS,
    ProcessedDataMissingError,
    UnknownFigureError,
    build_figures,
    load_processed_data,
    stale_data_warning,
)


def _parse_run_flags(argv: list[str]) -> tuple[tuple[str, ...], Path | None, str]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--figures", type=str, default=None)
    parser.add_argument("--outdir", type=str, default=None)
    parser.add_argument("--format", type=str, default=DEFAULT_FORMAT, choices=list(SUPPORTED_FORMATS))
    parsed, _ = parser.parse_known_args(argv)

    figures = (
        tuple(name.strip() for name in parsed.figures.split(",") if name.strip())
        if parsed.figures
        else FIGURE_CHOICES
    )
    outdir = Path(parsed.outdir) if parsed.outdir else None
    return figures, outdir, parsed.format


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    settings = load_settings(argv)
    figures, outdir, fmt = _parse_run_flags(argv)

    try:
        series, metrics = load_processed_data(settings)
    except ProcessedDataMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    warning = stale_data_warning(metrics, settings)
    if warning:
        print(warning, file=sys.stderr)

    try:
        written = build_figures(series, metrics, settings, figures=figures, outdir=outdir, fmt=fmt)
    except UnknownFigureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
