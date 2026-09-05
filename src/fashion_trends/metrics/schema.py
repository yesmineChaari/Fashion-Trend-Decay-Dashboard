"""The canonical schema of `data/processed/metrics.parquet`.

Single source of truth for what a row of the metrics table looks like, so
`fashion_trends.metrics.compute_all` (the metrics engine's only entry point),
the persisted parquet file it writes, and any other consumer building a
metrics frame agree on the same columns in the same order with the same
dtypes. Each stage module (`peaks`, `decay`, `status`) owns its own slice of
this — its `*_COLUMNS` tuple and `*_DTYPES` dict — and this module only
assembles them; a threshold or a column never gets redefined here.

Nullable numeric types are used throughout for a reason that matters more
here than almost anywhere else in the codebase: a null metric is a
meaningful state (no peak found yet, a fit too short to trust, a trend that
never crossed half its peak), and coercing one to `0` would silently turn
"unknown" into "measured as zero" — two claims with opposite meanings. See
each stage module's own docstring for which cases null which of its columns.

`validate_metrics_schema` is the enforcement half of this contract: a frame
missing a column, carrying an extra one, or typed as something other than
what's declared here (an all-null column that quietly reverted to `object`
instead of the nullable dtype the rest of the pipeline expects, say) fails
loudly before it is written or handed back to a caller, rather than
persisting a `metrics.parquet` subtly different from the one the charts and
the dashboard were built against.
"""

from __future__ import annotations

import pandas as pd

from fashion_trends.metrics.decay import (
    DECAY_RATE_COLUMNS,
    DECAY_RATE_DTYPES,
    PCT_DROPPED_COLUMNS,
    PCT_DROPPED_DTYPES,
    TIME_TO_HALF_COLUMNS,
    TIME_TO_HALF_DTYPES,
)
from fashion_trends.metrics.peaks import PEAK_COLUMNS, PEAK_DTYPES
from fashion_trends.metrics.status import STATUS_COLUMNS, STATUS_DTYPES

# Catalog metadata plus the one flag (`low_resolution`) computed during
# ingestion rather than in this package — see
# `fashion_trends.ingest.pipeline._build_series_frame`.
IDENTITY_COLUMNS = ("trend_id", "keyword", "display_name", "category", "isolate", "low_resolution")
IDENTITY_DTYPES = {
    "trend_id": "object",
    "keyword": "object",
    "display_name": "object",
    "category": "object",
    "isolate": "bool",
    "low_resolution": "bool",
}

# Ties a row back to the run that produced it — which Google Trends request
# shape (`timeframe`, `geo`) generated these numbers, and when. `data/processed/
# manifest.json` records the same `timeframe`/`geo` for the run as a whole;
# these columns exist so a single exported or filtered row of `metrics.parquet`
# stays self-describing without a join back to that file, which matters most
# for the dashboard's live search (see `fashion_trends.metrics.compute_all`),
# where there may be no persisted manifest to join against at all.
PROVENANCE_COLUMNS = ("data_pull_date", "timeframe", "geo")
PROVENANCE_DTYPES = {
    "data_pull_date": "datetime64[ns]",
    "timeframe": "object",
    "geo": "object",
}

METRICS_COLUMNS = (
    *IDENTITY_COLUMNS,
    *PEAK_COLUMNS,
    *PCT_DROPPED_COLUMNS,
    *DECAY_RATE_COLUMNS,
    *TIME_TO_HALF_COLUMNS,
    *STATUS_COLUMNS,
    *PROVENANCE_COLUMNS,
)

METRICS_DTYPES = {
    **IDENTITY_DTYPES,
    **PEAK_DTYPES,
    **PCT_DROPPED_DTYPES,
    **DECAY_RATE_DTYPES,
    **TIME_TO_HALF_DTYPES,
    **STATUS_DTYPES,
    **PROVENANCE_DTYPES,
}


class MetricsSchemaError(ValueError):
    """Raised when a frame does not match the canonical metrics schema."""


def validate_metrics_schema(frame: pd.DataFrame) -> None:
    """Raise `MetricsSchemaError` unless `frame` matches `METRICS_COLUMNS`/`METRICS_DTYPES` exactly.

    Column order is checked, not just membership — `compute_all` always
    returns columns in `METRICS_COLUMNS` order, and a caller writing straight
    to parquet should be able to rely on that without re-sorting.
    """
    actual_columns = list(frame.columns)
    expected_columns = list(METRICS_COLUMNS)
    if actual_columns != expected_columns:
        missing = [c for c in expected_columns if c not in actual_columns]
        unexpected = [c for c in actual_columns if c not in expected_columns]
        detail = f"missing: {missing}, unexpected: {unexpected}" if (missing or unexpected) else (f"got order {actual_columns!r}")
        raise MetricsSchemaError(f"metrics frame does not match the canonical schema — {detail}")

    mismatched = {
        column: (str(frame[column].dtype), expected_dtype)
        for column, expected_dtype in METRICS_DTYPES.items()
        if str(frame[column].dtype) != expected_dtype
    }
    if mismatched:
        raise MetricsSchemaError(f"metrics frame has mismatched dtypes (actual, expected): {mismatched}")
