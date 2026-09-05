import pandas as pd
import pytest

from fashion_trends.app.data import ProcessedDataMissingError, get_settings, load_dashboard_data
from fashion_trends.ingest.pipeline import METRICS_FILENAME, SERIES_FILENAME
from fashion_trends.settings import Settings

# ---- get_settings ----------------------------------------------------


def test_get_settings_ignores_process_argv(monkeypatch):
    # Under `streamlit run app/streamlit_app.py --server.port 9000`, sys.argv
    # holds Streamlit's own flags, not pipeline ones — get_settings must not
    # let argparse choke on or misinterpret them.
    monkeypatch.setattr("sys.argv", ["streamlit_app.py", "--server.port", "9000"])

    settings = get_settings()

    assert settings == Settings()


def test_get_settings_applies_env_var_overrides(monkeypatch):
    monkeypatch.setenv("FASHION_TRENDS_GEO", "FR")

    settings = get_settings()

    assert settings.geo == "FR"


# ---- load_dashboard_data ----------------------------------------------------


def _settings(tmp_path):
    return Settings(data_processed_dir=tmp_path / "processed", figures_dir=tmp_path / "figures")


def test_load_dashboard_data_raises_when_processed_data_missing(tmp_path):
    settings = _settings(tmp_path)

    with pytest.raises(ProcessedDataMissingError) as excinfo:
        load_dashboard_data(settings)

    assert "refresh_data.py" in str(excinfo.value)


def test_load_dashboard_data_reads_both_files(tmp_path):
    settings = _settings(tmp_path)
    settings.data_processed_dir.mkdir(parents=True)
    series = pd.DataFrame({"trend_id": ["fast"], "date": [pd.Timestamp("2024-01-01")]})
    metrics = pd.DataFrame(
        {
            "trend_id": ["fast"],
            "data_pull_date": [pd.Timestamp("2026-09-01")],
            "timeframe": ["today 5-y"],
            "geo": ["US"],
        }
    )
    series.to_parquet(settings.data_processed_dir / SERIES_FILENAME)
    metrics.to_parquet(settings.data_processed_dir / METRICS_FILENAME)

    loaded_series, loaded_metrics = load_dashboard_data(settings)

    assert len(loaded_series) == 1
    assert len(loaded_metrics) == 1
