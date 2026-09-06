"""Central settings for the ingestion, metrics, and visualization pipeline.

Every parameter that affects a run's output belongs here. Precedence, lowest
to highest: dataclass defaults, then `FASHION_TRENDS_*` environment
variables, then CLI flags.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PREFIX = "FASHION_TRENDS_"


@dataclass(frozen=True)
class Settings:
    # `today 5-y` is the longest window still returning weekly (not monthly)
    # granularity; changing it changes every downstream number.
    timeframe: str = "today 5-y"
    geo: str = "US"

    smoothing_window: int = 4

    # Peak qualification, see `fashion_trends.metrics.peaks`.
    secondary_peak_ratio: float = 0.8
    spike_peak_ratio: float = 0.5
    peak_boundary_weeks: int = 4
    pre_peak_rise_weeks: int = 4

    # Decay metrics, see `fashion_trends.metrics.decay`.
    min_decay_fit_weeks: int = 8
    half_life_sustained_weeks: int = 2

    # Lifecycle status, see `fashion_trends.metrics.status`.
    collapsed_pct_dropped_threshold: float = 70.0
    stabilized_window_weeks: int = 26
    stabilized_flat_tolerance: float = 0.15
    stabilized_min_retained_pct: float = 40.0

    # Shared reference keyword included in every batch so the batches can be
    # rescaled onto one axis (see `fashion_trends.ingest.batching`).
    # "haute couture" was chosen after probing candidates against live Google
    # Trends: it's dense, moderate in magnitude, and peaks on real Haute
    # Couture Fashion Week dates rather than a data artifact. See
    # docs/trend-selection.md for the comparison.
    anchor_keyword: str = "haute couture"
    max_batch_keywords: int = 5
    # Rescaled peak below which a trend is flagged `low_resolution`.
    low_resolution_threshold: float = 5.0

    data_raw_dir: Path = REPO_ROOT / "data" / "raw"
    data_processed_dir: Path = REPO_ROOT / "data" / "processed"
    figures_dir: Path = REPO_ROOT / "outputs" / "figures"

    cache_ttl_days: int = 7
    request_delay_seconds: float = 1.0
    max_retries: int = 3

    # When set, serves keywords from the committed fixture snapshot instead
    # of Google Trends. See `fashion_trends.ingest.fixtures`.
    fixture_mode: bool = False

    def to_manifest(self) -> dict[str, Any]:
        """A JSON-safe view of every setting, for recording alongside run outputs."""
        return {
            "timeframe": self.timeframe,
            "geo": self.geo,
            "smoothing_window": self.smoothing_window,
            "secondary_peak_ratio": self.secondary_peak_ratio,
            "spike_peak_ratio": self.spike_peak_ratio,
            "peak_boundary_weeks": self.peak_boundary_weeks,
            "pre_peak_rise_weeks": self.pre_peak_rise_weeks,
            "min_decay_fit_weeks": self.min_decay_fit_weeks,
            "half_life_sustained_weeks": self.half_life_sustained_weeks,
            "collapsed_pct_dropped_threshold": self.collapsed_pct_dropped_threshold,
            "stabilized_window_weeks": self.stabilized_window_weeks,
            "stabilized_flat_tolerance": self.stabilized_flat_tolerance,
            "stabilized_min_retained_pct": self.stabilized_min_retained_pct,
            "anchor_keyword": self.anchor_keyword,
            "max_batch_keywords": self.max_batch_keywords,
            "low_resolution_threshold": self.low_resolution_threshold,
            "data_raw_dir": str(self.data_raw_dir),
            "data_processed_dir": str(self.data_processed_dir),
            "figures_dir": str(self.figures_dir),
            "cache_ttl_days": self.cache_ttl_days,
            "request_delay_seconds": self.request_delay_seconds,
            "max_retries": self.max_retries,
            "fixture_mode": self.fixture_mode,
        }


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Single source of truth for each setting's env var suffix, CLI flag, and type caster.
_FIELDS: tuple[tuple[str, Callable[[str], Any]], ...] = (
    ("timeframe", str),
    ("geo", str),
    ("smoothing_window", int),
    ("secondary_peak_ratio", float),
    ("spike_peak_ratio", float),
    ("peak_boundary_weeks", int),
    ("pre_peak_rise_weeks", int),
    ("min_decay_fit_weeks", int),
    ("half_life_sustained_weeks", int),
    ("collapsed_pct_dropped_threshold", float),
    ("stabilized_window_weeks", int),
    ("stabilized_flat_tolerance", float),
    ("stabilized_min_retained_pct", float),
    ("anchor_keyword", str),
    ("max_batch_keywords", int),
    ("low_resolution_threshold", float),
    ("data_raw_dir", Path),
    ("data_processed_dir", Path),
    ("figures_dir", Path),
    ("cache_ttl_days", int),
    ("request_delay_seconds", float),
    ("max_retries", int),
    ("fixture_mode", _parse_bool),
)


def _env_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for name, cast in _FIELDS:
        raw = os.environ.get(f"{ENV_PREFIX}{name.upper()}")
        if raw is not None:
            overrides[name] = cast(raw)

    # `FIXTURE_MODE=1` is a bare shorthand, checked only when the prefixed
    # `FASHION_TRENDS_FIXTURE_MODE` form wasn't set.
    if "fixture_mode" not in overrides:
        raw = os.environ.get("FIXTURE_MODE")
        if raw is not None:
            overrides["fixture_mode"] = _parse_bool(raw)

    return overrides


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    for name, cast in _FIELDS:
        parser.add_argument(f"--{name.replace('_', '-')}", type=cast, default=None)
    parser.add_argument("--offline", action="store_true", help="Alias for --fixture-mode true")
    return parser


def load_settings(argv: list[str] | None = None) -> Settings:
    """Resolve settings from defaults, environment variables, then CLI flags.

    `argv` defaults to `sys.argv[1:]`; pass an explicit list (an empty one
    included) to ignore the process's real arguments. Unrecognized arguments
    are ignored rather than raising.
    """
    settings = replace(Settings(), **_env_overrides())

    parsed, _ = _build_arg_parser().parse_known_args(argv)
    cli_overrides = {name: value for name, _ in _FIELDS if (value := getattr(parsed, name)) is not None}
    if parsed.offline:
        cli_overrides["fixture_mode"] = True
    return replace(settings, **cli_overrides)


def write_manifest(settings: Settings, path: Path | str, **extra: Any) -> Path:
    """Write `settings`, plus any extra run metadata, to `path` as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings.to_manifest(),
        **extra,
    }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path
