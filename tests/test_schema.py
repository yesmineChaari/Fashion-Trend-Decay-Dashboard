import pandas as pd
import pytest

from fashion_trends.metrics.schema import (
    METRICS_COLUMNS,
    METRICS_DTYPES,
    MetricsSchemaError,
    validate_metrics_schema,
)


def _valid_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=METRICS_COLUMNS).astype(METRICS_DTYPES)


def _row_with_nulls() -> dict:
    """One row where every nullable column is null.

    Every value still round-trips through `METRICS_DTYPES`, which is exactly
    the point: a null metric (no peak found, no fit long enough to trust) is
    a valid, meaningful state this schema must accept, not a violation.
    """
    row = {}
    for column in METRICS_COLUMNS:
        dtype = METRICS_DTYPES[column]
        row[column] = False if dtype == "bool" else "x" if dtype == "object" else None
    return row


def test_every_column_has_a_declared_dtype():
    assert set(METRICS_DTYPES) == set(METRICS_COLUMNS)


def test_an_empty_frame_with_the_canonical_shape_passes():
    validate_metrics_schema(_valid_frame())


def test_a_missing_column_is_rejected():
    frame = _valid_frame().drop(columns=["pct_dropped"])

    with pytest.raises(MetricsSchemaError, match="pct_dropped"):
        validate_metrics_schema(frame)


def test_an_unexpected_extra_column_is_rejected():
    frame = _valid_frame()
    frame["made_up_column"] = pd.Series(dtype="float64")

    with pytest.raises(MetricsSchemaError, match="made_up_column"):
        validate_metrics_schema(frame)


def test_columns_out_of_order_are_rejected():
    reordered = list(METRICS_COLUMNS)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    frame = _valid_frame()[reordered]

    with pytest.raises(MetricsSchemaError):
        validate_metrics_schema(frame)


def test_a_wrong_dtype_is_rejected():
    frame = _valid_frame()
    frame["pct_dropped"] = frame["pct_dropped"].astype("object")

    with pytest.raises(MetricsSchemaError, match="pct_dropped"):
        validate_metrics_schema(frame)


def test_an_all_null_nullable_metric_row_is_not_a_schema_violation():
    frame = pd.DataFrame([_row_with_nulls()], columns=METRICS_COLUMNS).astype(METRICS_DTYPES)

    validate_metrics_schema(frame)


def test_round_trip_through_parquet_preserves_nulls_and_dtypes(tmp_path):
    frame = pd.DataFrame([_row_with_nulls()], columns=METRICS_COLUMNS).astype(METRICS_DTYPES)

    path = tmp_path / "metrics.parquet"
    frame.to_parquet(path)
    round_tripped = pd.read_parquet(path)

    pd.testing.assert_frame_equal(round_tripped, frame)
    validate_metrics_schema(round_tripped)
