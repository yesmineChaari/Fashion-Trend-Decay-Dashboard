import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pytest

from fashion_trends import metrics as metrics_module
from fashion_trends.ingest.pipeline import METRICS_FILENAME, SERIES_FILENAME
from fashion_trends.keywords import Trend
from fashion_trends.metrics import compute_all
from fashion_trends.settings import Settings
from fashion_trends.viz.build import (
    FIGURE_CHOICES,
    ProcessedDataMissingError,
    UnknownFigureError,
    build_figures,
    load_processed_data,
    stale_data_warning,
)


def _trend(id_, keyword, category="aesthetic"):
    return Trend(id=id_, keyword=keyword, display_name=keyword.title(), category=category, notes="t")


def _dates(n, start="2020-01-05"):
    return pd.date_range(start, periods=n, freq="W-SUN")


def _series_rows(trend_id, keyword, display_name, category, values, start="2020-01-05"):
    return pd.DataFrame(
        {
            "date": _dates(len(values), start=start),
            "trend_id": trend_id,
            "keyword": keyword,
            "display_name": display_name,
            "category": category,
            "interest_raw": values,
            "interest_smooth": values,
            "low_resolution": False,
        }
    )


_LEAD_PAD = [5.0] * 6


def _fast_collapse_values():
    rise = [10.0, 40.0, 90.0]
    decay = [100.0 * (0.6**week) for week in range(1, 40)]
    return _LEAD_PAD + rise + decay


@pytest.fixture
def catalog(monkeypatch):
    trends = [_trend("fast", "fast trend")]
    monkeypatch.setattr(metrics_module, "load_trends", lambda: trends)
    return trends


@pytest.fixture
def series(catalog):
    return _series_rows("fast", "fast trend", "Fast Trend", "aesthetic", _fast_collapse_values())


@pytest.fixture
def metrics(series):
    return compute_all(series, Settings())


def _settings(tmp_path):
    return Settings(data_processed_dir=tmp_path / "processed", figures_dir=tmp_path / "figures")


# ---- load_processed_data ----------------------------------------------------


def test_load_processed_data_raises_when_both_files_missing(tmp_path):
    settings = _settings(tmp_path)

    with pytest.raises(ProcessedDataMissingError) as excinfo:
        load_processed_data(settings)

    assert "refresh_data.py" in str(excinfo.value)


def test_load_processed_data_raises_when_one_file_missing(tmp_path, series):
    settings = _settings(tmp_path)
    settings.data_processed_dir.mkdir(parents=True)
    series.to_parquet(settings.data_processed_dir / SERIES_FILENAME)

    with pytest.raises(ProcessedDataMissingError) as excinfo:
        load_processed_data(settings)

    assert METRICS_FILENAME in str(excinfo.value)


def test_load_processed_data_reads_both_files(tmp_path, series, metrics):
    settings = _settings(tmp_path)
    settings.data_processed_dir.mkdir(parents=True)
    series.to_parquet(settings.data_processed_dir / SERIES_FILENAME)
    metrics.to_parquet(settings.data_processed_dir / METRICS_FILENAME)

    loaded_series, loaded_metrics = load_processed_data(settings)

    assert len(loaded_series) == len(series)
    assert len(loaded_metrics) == len(metrics)


# ---- stale_data_warning ----------------------------------------------------


def test_stale_data_warning_none_for_fresh_data(metrics):
    settings = Settings(cache_ttl_days=7)

    assert stale_data_warning(metrics, settings) is None


def test_stale_data_warning_present_for_stale_data(metrics):
    stale = metrics.copy()
    stale["data_pull_date"] = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timedelta(days=30)
    settings = Settings(cache_ttl_days=7)

    warning = stale_data_warning(stale, settings)

    assert warning is not None
    assert "refresh_data.py" in warning


def test_stale_data_warning_none_for_empty_metrics():
    settings = Settings(cache_ttl_days=7)

    assert stale_data_warning(pd.DataFrame(), settings) is None


# ---- build_figures ----------------------------------------------------


def test_build_figures_writes_all_three_by_default(tmp_path, series, metrics):
    settings = _settings(tmp_path)

    written = build_figures(series, metrics, settings)

    assert len(written) == len(FIGURE_CHOICES)
    for path in written:
        assert path.exists()
    assert {path.parent for path in written} == {settings.figures_dir}


def test_build_figures_writes_only_the_requested_subset(tmp_path, series, metrics):
    settings = _settings(tmp_path)

    written = build_figures(series, metrics, settings, figures=("ranking",))

    assert len(written) == 1
    assert written[0].name == "drop_ranking.png"


def test_build_figures_writes_in_canonical_order_regardless_of_request_order(tmp_path, series, metrics):
    settings = _settings(tmp_path)

    written = build_figures(series, metrics, settings, figures=("decline", "decay"))

    assert [path.stem for path in written] == ["decay_curves", "time_to_decline"]


def test_build_figures_deduplicates_a_repeated_name(tmp_path, series, metrics):
    settings = _settings(tmp_path)

    written = build_figures(series, metrics, settings, figures=("decay", "decay"))

    assert len(written) == 1


def test_build_figures_respects_outdir_override(tmp_path, series, metrics):
    settings = _settings(tmp_path)
    outdir = tmp_path / "custom"

    written = build_figures(series, metrics, settings, figures=("decay",), outdir=outdir)

    assert written[0].parent == outdir


def test_build_figures_respects_format_override(tmp_path, series, metrics):
    settings = _settings(tmp_path)

    written = build_figures(series, metrics, settings, figures=("decay",), fmt="svg")

    assert written[0].suffix == ".svg"


def test_build_figures_raises_for_an_unknown_figure_name(tmp_path, series, metrics):
    settings = _settings(tmp_path)

    with pytest.raises(UnknownFigureError):
        build_figures(series, metrics, settings, figures=("not_a_real_figure",))


def test_build_figures_rerun_is_byte_identical_png(tmp_path, series, metrics):
    settings = _settings(tmp_path)

    first = build_figures(series, metrics, settings, figures=("decay",))
    first_bytes = first[0].read_bytes()
    second = build_figures(series, metrics, settings, figures=("decay",))
    second_bytes = second[0].read_bytes()

    assert first_bytes == second_bytes


def test_build_figures_rerun_is_byte_identical_svg(tmp_path, series, metrics):
    settings = _settings(tmp_path)

    first = build_figures(series, metrics, settings, figures=("decay",), fmt="svg")
    first_bytes = first[0].read_bytes()
    second = build_figures(series, metrics, settings, figures=("decay",), fmt="svg")
    second_bytes = second[0].read_bytes()

    assert first_bytes == second_bytes
