from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from pytrends.exceptions import ResponseError, TooManyRequestsError
from requests.exceptions import ConnectionError as RequestsConnectionError

from fashion_trends import ingest
from fashion_trends.ingest import pytrends_client as client_module
from fashion_trends.ingest.pytrends_client import (
    NoDataError,
    RateLimitedError,
    TransportError,
    fetch_interest_over_time,
)
from fashion_trends.settings import Settings

SETTINGS = Settings(max_retries=2, request_delay_seconds=0.0)


@pytest.fixture(autouse=True)
def reset_client_singleton(monkeypatch):
    monkeypatch.setattr(client_module, "_client", None)
    monkeypatch.setattr(client_module, "_last_request_at", None)
    monkeypatch.setattr(client_module, "_sleep_backoff", lambda attempt: None)


def _fake_response(status_code):
    response = MagicMock()
    response.status_code = status_code
    return response


def _install_fake_trend_req(monkeypatch, trend_req_instance):
    factory = MagicMock(return_value=trend_req_instance)
    monkeypatch.setattr(client_module, "TrendReq", factory)
    return factory


def test_fetch_drops_partial_rows_and_returns_frame(monkeypatch, caplog):
    frame = pd.DataFrame(
        {"mob wife aesthetic": [10, 20], "isPartial": [False, True]},
        index=pd.to_datetime(["2026-08-24", "2026-08-31"]),
    )
    trend_req = MagicMock()
    trend_req.interest_over_time.return_value = frame
    _install_fake_trend_req(monkeypatch, trend_req)

    with caplog.at_level("INFO"):
        result = fetch_interest_over_time(["mob wife aesthetic"], "today 5-y", "US", SETTINGS)

    # The flagged row goes, not just the flag column -- an in-progress week
    # reads low and lands in the trailing window `current_value` averages.
    assert "isPartial" not in result.columns
    assert list(result["mob wife aesthetic"]) == [10]
    assert list(result.index) == [pd.Timestamp("2026-08-24")]
    assert "Dropping 1 trailing partial-week row" in caplog.text
    trend_req.build_payload.assert_called_once_with(["mob wife aesthetic"], timeframe="today 5-y", geo="US")


def test_empty_response_raises_no_data_error(monkeypatch):
    trend_req = MagicMock()
    trend_req.interest_over_time.return_value = pd.DataFrame()
    _install_fake_trend_req(monkeypatch, trend_req)

    with pytest.raises(NoDataError):
        fetch_interest_over_time(["not a real keyword"], "today 5-y", "US", SETTINGS)


def test_rate_limit_retries_then_succeeds(monkeypatch):
    frame = pd.DataFrame({"kw": [1], "isPartial": [False]}, index=pd.to_datetime(["2026-08-31"]))
    trend_req = MagicMock()
    trend_req.interest_over_time.side_effect = [
        TooManyRequestsError.from_response(_fake_response(429)),
        frame,
    ]
    _install_fake_trend_req(monkeypatch, trend_req)

    result = fetch_interest_over_time(["kw"], "today 5-y", "US", SETTINGS)

    assert list(result["kw"]) == [1]
    assert trend_req.interest_over_time.call_count == 2


def test_rate_limit_exhausting_retries_raises_rate_limited_error(monkeypatch):
    trend_req = MagicMock()
    trend_req.interest_over_time.side_effect = TooManyRequestsError.from_response(_fake_response(429))
    _install_fake_trend_req(monkeypatch, trend_req)

    with pytest.raises(RateLimitedError):
        fetch_interest_over_time(["kw"], "today 5-y", "US", SETTINGS)

    assert trend_req.interest_over_time.call_count == SETTINGS.max_retries + 1


def test_non_rate_limit_response_error_raises_transport_error_without_retry(monkeypatch):
    trend_req = MagicMock()
    trend_req.interest_over_time.side_effect = ResponseError.from_response(_fake_response(500))
    _install_fake_trend_req(monkeypatch, trend_req)

    with pytest.raises(TransportError):
        fetch_interest_over_time(["kw"], "today 5-y", "US", SETTINGS)

    assert trend_req.interest_over_time.call_count == 1


def test_transient_network_error_retries_then_succeeds(monkeypatch):
    frame = pd.DataFrame({"kw": [1], "isPartial": [False]}, index=pd.to_datetime(["2026-08-31"]))
    trend_req = MagicMock()
    trend_req.interest_over_time.side_effect = [RequestsConnectionError("boom"), frame]
    _install_fake_trend_req(monkeypatch, trend_req)

    result = fetch_interest_over_time(["kw"], "today 5-y", "US", SETTINGS)

    assert list(result["kw"]) == [1]


def test_transient_network_error_exhausting_retries_raises_transport_error(monkeypatch):
    trend_req = MagicMock()
    trend_req.interest_over_time.side_effect = RequestsConnectionError("boom")
    _install_fake_trend_req(monkeypatch, trend_req)

    with pytest.raises(TransportError):
        fetch_interest_over_time(["kw"], "today 5-y", "US", SETTINGS)

    assert trend_req.interest_over_time.call_count == SETTINGS.max_retries + 1


def test_client_session_is_reused_across_calls(monkeypatch):
    frame = pd.DataFrame({"kw": [1], "isPartial": [False]}, index=pd.to_datetime(["2026-08-31"]))
    trend_req = MagicMock()
    trend_req.interest_over_time.return_value = frame
    factory = _install_fake_trend_req(monkeypatch, trend_req)

    fetch_interest_over_time(["kw"], "today 5-y", "US", SETTINGS)
    fetch_interest_over_time(["kw"], "today 5-y", "US", SETTINGS)

    factory.assert_called_once()


def test_request_delay_is_honored_between_calls(monkeypatch):
    frame = pd.DataFrame({"kw": [1], "isPartial": [False]}, index=pd.to_datetime(["2026-08-31"]))
    trend_req = MagicMock()
    trend_req.interest_over_time.return_value = frame
    _install_fake_trend_req(monkeypatch, trend_req)

    clock = iter([100.0, 100.0, 100.2, 100.2])
    monkeypatch.setattr(client_module.time, "monotonic", lambda: next(clock))
    sleep_calls = []
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    delayed_settings = Settings(max_retries=2, request_delay_seconds=1.0)
    fetch_interest_over_time(["kw"], "today 5-y", "US", delayed_settings)
    fetch_interest_over_time(["kw"], "today 5-y", "US", delayed_settings)

    assert sleep_calls == [pytest.approx(0.8)]


def test_no_other_module_imports_pytrends():
    src_root = Path(ingest.__file__).resolve().parents[1]
    offending = []
    for path in src_root.rglob("*.py"):
        if path.name == "pytrends_client.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "import pytrends" in text or "from pytrends" in text:
            offending.append(str(path))

    assert offending == []
