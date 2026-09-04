"""Central settings for the ingestion, metrics, and visualization pipeline.

Every parameter that affects the output of a run belongs here — no other
module should read an environment variable or hardcode one of these values
itself. Precedence, lowest to highest: dataclass defaults, then
`FASHION_TRENDS_*` environment variables, then CLI flags.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PREFIX = "FASHION_TRENDS_"


@dataclass(frozen=True)
class Settings:
    # Google Trends request shape. `today 5-y` is the longest window that still
    # returns weekly (rather than monthly) granularity, and the 0-100 scale is
    # relative to this window's own maximum — changing it changes every
    # downstream number, not just the resolution.
    timeframe: str = "today 5-y"
    geo: str = "US"

    smoothing_window: int = 4

    # Peak qualification (see `fashion_trends.metrics.peaks`). A trend whose
    # series climbs back to `secondary_peak_ratio` of its peak, after having
    # dropped below it, is flagged as having a second peak — one decay number
    # can't describe a revival. A peak landing within `peak_boundary_weeks` of
    # either end of the pulled window is flagged too: the real peak may sit
    # outside the window. `pre_peak_rise_weeks` is how far back to compare when
    # deciding a trend whose peak is its newest week is still climbing.
    # `spike_peak_ratio` is the other half of the false-spike defence that
    # smoothing starts: a peak whose surrounding weeks median below this
    # fraction of it was propped up by a single week, not by a real hump.
    secondary_peak_ratio: float = 0.8
    spike_peak_ratio: float = 0.5
    peak_boundary_weeks: int = 4
    pre_peak_rise_weeks: int = 4

    # Decay metrics (see `fashion_trends.metrics.decay`). The exponential
    # decay fit needs a post-peak segment long enough to have a shape:
    # below `min_decay_fit_weeks` weeks the fitted constant says more about
    # the last few noisy weeks than about the trend, so it is left null.
    # `half_life_sustained_weeks` is how many consecutive weeks a trend must
    # stay below half its peak for the crossing to count: one week under the
    # line is a dip, not the week the trend halved.
    min_decay_fit_weeks: int = 8
    half_life_sustained_weeks: int = 2

    # Lifecycle status (see `fashion_trends.metrics.status`). A trend is
    # `collapsed` once it has dropped at least `collapsed_pct_dropped_threshold`
    # percent from its peak. Below that, a post-peak trend flat over its
    # trailing `stabilized_window_weeks` (relative range within
    # `stabilized_flat_tolerance` of the window's mean) counts as `stabilized`
    # rather than `declining` only if it also retained at least
    # `stabilized_min_retained_pct` percent of its peak — flat *and* faded
    # away is still a fade, not a plateau worth calling a wardrobe staple.
    collapsed_pct_dropped_threshold: float = 70.0
    stabilized_window_weeks: int = 26
    stabilized_flat_tolerance: float = 0.15
    stabilized_min_retained_pct: float = 40.0

    # Google Trends caps requests at 5 keywords and rescales each batch 0-100
    # relative to that batch's own maximum, so raw values are not comparable
    # across batches. Including this keyword in every batch gives a shared
    # reference point: the ratio between its peak in each batch and its peak
    # in the reference batch is the factor that puts every batch back on one
    # axis (see `fashion_trends.ingest.batching`).
    #
    # "haute couture" was chosen after probing several candidates against
    # live Google Trends (2021-09-01..2026-09-01, geo=US — see
    # docs/trend-selection.md). Generic garment/shopping nouns ("little
    # black dress", "vintage fashion", "personal style") all turned out to
    # carry the same spring-2026 data artifact documented in that file for
    # `cargo pants` and friends — an unexplained spike to their all-time
    # maximum on 2026-04-12 or 2026-02-08 shared with the non-fashion control
    # keywords. "haute couture" doesn't: it is dense every week (262/262
    # non-zero), moderate in magnitude (mean 23.5, min 14 — comparable to
    # most catalog entries), and its tallest weeks land on real Haute
    # Couture Fashion Week dates (Jan/Jul, matching the same weeks in
    # 2022-2025) rather than an arbitrary artifact week. It is not perfectly
    # flat — couture week itself roughly doubles it twice a year — but the
    # rescaling math only uses its measured *peak* per batch, which a real
    # recurring seasonal high still provides reliably; see
    # `fashion_trends.ingest.batching.rescale_batches`.
    #
    # The two catalog trends whose own peak is an order of magnitude above
    # the rest (`demure`, `labubu`; see their `isolate: true` flag in
    # `config/trends.yaml`) still crush the anchor's resolution down to a
    # handful of integer values in their solo batch — that is an inherent
    # limit of anchoring against a single fixed keyword, not a sign this
    # anchor was chosen badly, and it is why raw per-batch values are always
    # kept alongside the rescaled ones.
    anchor_keyword: str = "haute couture"
    max_batch_keywords: int = 5
    # Rescaled peak below which a trend is flagged `low_resolution`: once its
    # tallest point barely clears the noise floor of Google Trends' integer
    # 0-100 scale, its shape cannot be trusted for decay metrics.
    low_resolution_threshold: float = 5.0

    data_raw_dir: Path = REPO_ROOT / "data" / "raw"
    data_processed_dir: Path = REPO_ROOT / "data" / "processed"
    figures_dir: Path = REPO_ROOT / "outputs" / "figures"

    cache_ttl_days: int = 7
    request_delay_seconds: float = 1.0
    max_retries: int = 3

    # When set, `fashion_trends.ingest.cache.fetch_batch` serves keywords from
    # the committed `tests/fixtures/` snapshot instead of Google Trends, so a
    # rate-limited or offline day is still a day of progress on metrics,
    # charts, and the dashboard. See `fashion_trends.ingest.fixtures`.
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


# Single source of truth for the env var suffix, CLI flag name, and type
# caster of each setting, so `load_settings` can't drift from `Settings`.
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

    # `FIXTURE_MODE=1` is the documented bare shorthand for this one setting,
    # alongside the usual `FASHION_TRENDS_FIXTURE_MODE` — checked only when
    # the prefixed form wasn't set, so the prefixed form always wins.
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

    `argv` is forwarded to argparse (so it defaults to `sys.argv[1:]`); pass an
    explicit list — an empty one included — to ignore the process's real
    arguments, e.g. from a test or when embedding this in another CLI.
    Unrecognized arguments are ignored rather than raising, so this can run
    alongside a caller's own argument parser.
    """
    settings = replace(Settings(), **_env_overrides())

    parsed, _ = _build_arg_parser().parse_known_args(argv)
    cli_overrides = {
        name: value for name, _ in _FIELDS if (value := getattr(parsed, name)) is not None
    }
    if parsed.offline:
        cli_overrides["fixture_mode"] = True
    return replace(settings, **cli_overrides)


def write_manifest(settings: Settings, path: Path | str, **extra: Any) -> Path:
    """Write `settings`, plus any extra run metadata, to `path` as JSON.

    Any pipeline stage that produces an artifact should pair it with a
    manifest call so the parameters behind it stay traceable later.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings.to_manifest(),
        **extra,
    }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path
