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

    data_raw_dir: Path = REPO_ROOT / "data" / "raw"
    data_processed_dir: Path = REPO_ROOT / "data" / "processed"
    figures_dir: Path = REPO_ROOT / "outputs" / "figures"

    cache_ttl_days: int = 7
    request_delay_seconds: float = 1.0
    max_retries: int = 3

    def to_manifest(self) -> dict[str, Any]:
        """A JSON-safe view of every setting, for recording alongside run outputs."""
        return {
            "timeframe": self.timeframe,
            "geo": self.geo,
            "smoothing_window": self.smoothing_window,
            "data_raw_dir": str(self.data_raw_dir),
            "data_processed_dir": str(self.data_processed_dir),
            "figures_dir": str(self.figures_dir),
            "cache_ttl_days": self.cache_ttl_days,
            "request_delay_seconds": self.request_delay_seconds,
            "max_retries": self.max_retries,
        }


# Single source of truth for the env var suffix, CLI flag name, and type
# caster of each setting, so `load_settings` can't drift from `Settings`.
_FIELDS: tuple[tuple[str, Callable[[str], Any]], ...] = (
    ("timeframe", str),
    ("geo", str),
    ("smoothing_window", int),
    ("data_raw_dir", Path),
    ("data_processed_dir", Path),
    ("figures_dir", Path),
    ("cache_ttl_days", int),
    ("request_delay_seconds", float),
    ("max_retries", int),
)


def _env_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for name, cast in _FIELDS:
        raw = os.environ.get(f"{ENV_PREFIX}{name.upper()}")
        if raw is not None:
            overrides[name] = cast(raw)
    return overrides


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    for name, cast in _FIELDS:
        parser.add_argument(f"--{name.replace('_', '-')}", type=cast, default=None)
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
