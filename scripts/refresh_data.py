#!/usr/bin/env python
"""Fetch, normalize, and persist trend data for the catalog in one command.

    python scripts/refresh_data.py [--refresh] [--offline] [--trends id1,id2]
                                    [--timeframe TF] [--geo GEO] ...

`--refresh`, `--offline`, and `--trends` are run-specific flags handled here;
every other flag (timeframe, geo, cache-ttl-days, ...) is a `Settings` field
and passed straight through to `fashion_trends.settings.load_settings` — see
that module for the full list.

Exits non-zero only when every trend failed; a partial failure (some trends
fetched, some not) still exits 0 so a scheduled run isn't marked broken over
one bad keyword — see the printed summary and `data/processed/manifest.json`
for which ones failed and why.
"""

from __future__ import annotations

import argparse
import sys

from fashion_trends.ingest.pipeline import PipelineFailedError, UnknownTrendIdsError, run_pipeline
from fashion_trends.settings import load_settings


def _parse_run_flags(argv: list[str]) -> tuple[bool, list[str] | None]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--trends", type=str, default=None)
    parsed, _ = parser.parse_known_args(argv)

    trend_ids = [tid.strip() for tid in parsed.trends.split(",") if tid.strip()] if parsed.trends else None
    return parsed.refresh, trend_ids


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    settings = load_settings(argv)
    refresh, trend_ids = _parse_run_flags(argv)

    try:
        result = run_pipeline(settings, trend_ids=trend_ids, refresh=refresh)
    except UnknownTrendIdsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PipelineFailedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for line in result.summary_lines():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
