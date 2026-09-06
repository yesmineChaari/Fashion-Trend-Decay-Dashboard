"""The canonical schema of `data/processed/metrics.parquet`.

Single source of truth for the metrics table's columns, order, and dtypes.
Each stage module (`peaks`, `decay`, `status`) owns its own `*_COLUMNS`/
`*_DTYPES` slice; this module only assembles them.

Nullable numeric types are used throughout since a null metric is a
meaningful state (no peak found, a fit too short to trust, etc.), and
coercing it to `0` would silently turn "unknown" into "measured as zero".

`validate_metrics_schema` enforces this contract, failing loudly rather than
persisting a `metrics.parquet` subtly different from what charts expect.
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

# Catalog metadata plus `low_resolution`, computed during ingestion.
IDENTITY_COLUMNS = ("trend_id", "keyword", "display_name", "category", "isolate", "low_resolution")
IDENTITY_DTYPES = {
    "trend_id": "object",
    "keyword": "object",
    "display_name": "object",
    "category": "object",
    "isolate": "bool",
    "low_resolution": "bool",
}

# Ties a row back to the run that produced it, so a filtered/exported row
# stays self-describing without a join back to `manifest.json`.
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
    """Raise `MetricsSchemaError` unless `frame` matches `METRICS_COLUMNS`/`METRICS_DTYPES` exactly, column order included."""
    actual_columns = list(frame.columns)
    expected_columns = list(METRICS_COLUMNS)
    if actual_columns != expected_columns:
        missing = [c for c in expected_columns if c not in actual_columns]
        unexpected = [c for c in actual_columns if c not in expected_columns]
        detail = f"missing: {missing}, unexpected: {unexpected}" if (missing or unexpected) else (f"got order {actual_columns!r}")
        raise MetricsSchemaError(f"metrics frame does not match the canonical schema. {detail}")

    mismatched = {
        column: (str(frame[column].dtype), expected_dtype)
        for column, expected_dtype in METRICS_DTYPES.items()
        if str(frame[column].dtype) != expected_dtype
    }
    if mismatched:
        raise MetricsSchemaError(f"metrics frame has mismatched dtypes (actual, expected): {mismatched}")
