import json
from pathlib import Path

import pytest

from fashion_trends.settings import REPO_ROOT, Settings, load_settings, write_manifest


def test_defaults_match_pipeline_spec():
    settings = load_settings([])

    assert settings.timeframe == "today 5-y"
    assert settings.geo == "US"
    assert settings.smoothing_window == 4
    assert settings.data_raw_dir == REPO_ROOT / "data" / "raw"
    assert settings.data_processed_dir == REPO_ROOT / "data" / "processed"
    assert settings.figures_dir == REPO_ROOT / "outputs" / "figures"
    assert settings.cache_ttl_days == 7
    assert settings.request_delay_seconds == 1.0
    assert settings.max_retries == 3


def test_settings_is_frozen():
    settings = Settings()

    with pytest.raises(AttributeError):
        settings.geo = "FR"


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("FASHION_TRENDS_GEO", "FR")
    monkeypatch.setenv("FASHION_TRENDS_SMOOTHING_WINDOW", "6")

    settings = load_settings([])

    assert settings.geo == "FR"
    assert settings.smoothing_window == 6


def test_cli_flag_overrides_env_var(monkeypatch):
    monkeypatch.setenv("FASHION_TRENDS_GEO", "FR")

    settings = load_settings(["--geo", "DE"])

    assert settings.geo == "DE"


def test_cli_flag_overrides_default_without_env():
    settings = load_settings(["--max-retries", "5", "--request-delay-seconds", "2.5"])

    assert settings.max_retries == 5
    assert settings.request_delay_seconds == 2.5


def test_unrecognized_cli_arguments_are_ignored():
    settings = load_settings(["--some-other-tools-flag", "value"])

    assert settings == load_settings([])


def test_path_settings_are_overridable(tmp_path):
    raw_dir = tmp_path / "raw"

    settings = load_settings(["--data-raw-dir", str(raw_dir)])

    assert settings.data_raw_dir == raw_dir


def test_write_manifest_records_settings_and_extra_fields(tmp_path):
    settings = load_settings(["--geo", "DE"])
    manifest_path = tmp_path / "manifests" / "run.json"

    result_path = write_manifest(settings, manifest_path, trend_id="mob_wife")

    assert result_path == manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["settings"]["geo"] == "DE"
    assert manifest["settings"]["timeframe"] == "today 5-y"
    assert manifest["trend_id"] == "mob_wife"
    assert "generated_at" in manifest
