"""HTTP framing integration without opening a real network socket."""

from __future__ import annotations

import io
import json
import socket
from typing import Any

import pytest

from rolling_thunder.forge_voacap_baseline_main import LocalVoacapProvider


class FakeHttpSocket:
    def __init__(self, response: dict[str, Any], writes: list[bytes]) -> None:
        body = json.dumps(response).encode()
        self._response = io.BytesIO(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        self._writes = writes

    def sendall(self, data: bytes) -> None:
        self._writes.append(data)

    def makefile(self, mode: str, buffering: int | None = None) -> io.BytesIO:
        return self._response

    def settimeout(self, timeout: float) -> None:
        return

    def setsockopt(self, level: int, option: int, value: int) -> None:
        return

    def close(self) -> None:
        return


def test_real_urllib_adapter_request_response_framing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[bytes] = []
    responses = iter([
        {"service": "voacap-service", "version": "0.3.0", "model_version": "model-1"},
        {"model_version": "model-1", "analysis": {"best_band_by_hour": [
            {"hour_utc": 0, "band_m": 20, "reliability": 0.5, "snr_db": 10.0}
        ]}},
    ])

    def fake_connection(*args: object, **kwargs: object) -> FakeHttpSocket:
        return FakeHttpSocket(next(responses), writes)

    monkeypatch.setattr(socket, "create_connection", fake_connection)
    adapter = LocalVoacapProvider(
        "http://127.0.0.1:8787", service_version="0.3.0", model_version="model-1",
        max_posts=1,
    )
    result = adapter.predict({
        "tx_grid": "EM79xm", "rx_grid": "EN80", "year": 2026, "month": 10,
        "bands_m": [20], "power_watts": 20, "mode": "FT8", "timezone": "UTC",
        "ssn": 121.4, "ssn_source": "reviewed", "ssn_source_version": "release-1",
        "model_version": "model-1", "service_version": "0.3.0",
        "contract": "voacap-summary-v1",
    }, timeout_s=10.0)
    wire = b"".join(writes)
    assert result.service_version == "0.3.0"
    assert b"GET /version HTTP/1.1" in wire
    assert b"POST /api/v1/summary HTTP/1.1" in wire
    assert b'"tx_grid":"EM79xm"' in wire
    assert b'"ssn":121.4' in wire
    assert b"ssn_source" not in wire
