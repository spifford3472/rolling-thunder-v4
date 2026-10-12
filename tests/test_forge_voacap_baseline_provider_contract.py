"""Provider API contract tests use fake transport only: never localhost I/O."""
from typing import Any

import pytest

from rolling_thunder.forge_voacap_baseline import ProviderFailure
from rolling_thunder.forge_voacap_baseline_main import LocalVoacapProvider


def test_baseline_adapter_posts_only_provider_supported_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LocalVoacapProvider("http://127.0.0.1:8787", service_version="0.3.0", model_version="model-1")
    requests: list[tuple[str, str, Any]] = []

    def fake_http(method: str, route: str, payload: Any) -> dict[str, Any]:
        requests.append((method, route, payload))
        if method == "GET":
            return {"service": "voacap-service", "version": "0.3.0"}
        return {"analysis": {"best_band_by_hour": [{"hour_utc": 0, "band_m": 20}]}}

    monkeypatch.setattr(adapter.client, "_json_request", fake_http)
    input_request = {
        "tx_grid": "EM79xm", "rx_grid": "EL98", "year": 2026, "month": 10,
        "bands_m": [20], "power_watts": 20, "mode": "FT8",
        "timezone": "UTC", "ssn": 87.9,
        "ssn_source": "verified", "ssn_source_version": "1",
        "model_version": "model-1", "service_version": "0.3.0",
        "contract": "voacap-summary-v1",
    }
    result = adapter.predict(input_request, timeout_s=10.0)
    assert result.service_version == "0.3.0"
    assert result.model_version == "model-1"
    assert requests[0] == ("GET", "/version", None)
    assert requests[1][0:2] == ("POST", "/api/v1/summary")
    assert requests[1][2] == {
        "tx_grid": "EM79xm", "rx_grid": "EL98", "year": 2026, "month": 10,
        "bands_m": [20], "power_watts": 20, "mode": "FT8",
        "timezone": "UTC", "ssn": 87.9,
    }


def test_baseline_adapter_rejects_provider_version_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LocalVoacapProvider("http://127.0.0.1:8787", service_version="0.3.0", model_version="model-1")
    requests: list[str] = []

    def fake_http(method: str, *args: object) -> dict[str, str]:
        requests.append(method)
        return {"version": "0.9.0"}

    monkeypatch.setattr(adapter.client, "_json_request", fake_http)
    request = {
        "tx_grid": "EM79xm", "rx_grid": "EL98", "year": 2026, "month": 10,
        "bands_m": [20], "power_watts": 20, "mode": "FT8",
        "timezone": "UTC", "ssn": 87.9,
    }
    with pytest.raises(ProviderFailure, match="provider_version_mismatch"):
        adapter.predict(request, timeout_s=10.0)
    assert requests == ["GET"]


def test_pilot_adapter_hard_stops_before_second_post(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LocalVoacapProvider(
        "http://127.0.0.1:8787", service_version="0.3.0", model_version="model-1",
        max_posts=1,
    )
    requests: list[str] = []

    def fake_http(method: str, route: str, payload: Any) -> dict[str, Any]:
        requests.append(f"{method} {route}")
        if method == "GET":
            return {"version": "0.3.0"}
        return {"analysis": {"best_band_by_hour": []}}

    monkeypatch.setattr(adapter.client, "_json_request", fake_http)
    request = {
        "tx_grid": "EM79xm", "rx_grid": "EL98", "year": 2026, "month": 10,
        "bands_m": [20], "power_watts": 20, "mode": "FT8", "timezone": "UTC",
        "ssn": 87.9,
    }
    adapter.predict(request, timeout_s=10.0)
    with pytest.raises(ProviderFailure, match="pilot_post_limit_exhausted"):
        adapter.predict(request, timeout_s=10.0)
    assert requests.count("POST /api/v1/summary") == 1
