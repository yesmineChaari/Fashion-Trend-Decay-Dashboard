"""Offline fixture data backing `Settings.fixture_mode`.

`FIXTURE_MODE=1` / `FASHION_TRENDS_FIXTURE_MODE=1` / `--offline` makes
`fashion_trends.ingest.cache.fetch_batch` serve keyword series from
`tests/fixtures/interest_over_time.parquet` instead of calling Google
Trends, so development and the test suite work with no network access at
all. `tests/fixtures/manifest.json` records where every column comes from —
`real_keywords` is one genuine pull of the trend catalog, kept unrefreshed
as a labelled snapshot; `synthetic_keywords` are series added because no
catalog keyword exhibits the shape the metrics engine has to survive
(still-rising, a false single-week peak, and a near-zero series — the
catalog's own `bag charm` already covers the fourth required case, a
revival with two peaks).

Every fixture value is already on one shared scale, unlike a real Google
Trends batch — there's no batch-relative rescaling to reproduce here, so
whichever keywords are requested together return the same numbers as any
other grouping would.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
DATA_PATH = FIXTURES_DIR / "interest_over_time.parquet"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"


class FixtureNotFoundError(LookupError):
    """Raised for a keyword the committed fixture table doesn't have."""


@lru_cache(maxsize=1)
def _table() -> pd.DataFrame:
    return pd.read_parquet(DATA_PATH)


@lru_cache(maxsize=1)
def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def fetch_interest_over_time(keywords: list[str]) -> pd.DataFrame:
    """Return the committed fixture series for `keywords`.

    Mirrors `pytrends_client.fetch_interest_over_time`'s return shape — a
    date-indexed frame with one column per keyword — with no network
    access, retry, or throttling: there is nothing to retry against.
    """
    table = _table()
    missing = [kw for kw in keywords if kw not in table.columns]
    if missing:
        raise FixtureNotFoundError(
            f"No fixture data for {missing!r} — see tests/fixtures/manifest.json "
            "for the keywords the committed fixture set covers"
        )
    return table[list(keywords)].copy()


def captured_at() -> str:
    """ISO timestamp the fixture set was generated, for provenance."""
    return _manifest()["generated_at"]


def pytrends_version() -> str:
    """The pytrends version used for the fixture set's real pull."""
    return _manifest()["source_pytrends_version"]
