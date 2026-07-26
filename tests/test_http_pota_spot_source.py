"""Tests for the HTTP Parks on the Air spot-source adapter."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps
from urllib.error import URLError

import pytest

from rolling_thunder.domain import RadioMode
from rolling_thunder.http_pota_spot_source import HttpPotaSpotSource
from rolling_thunder.pota_spot_source import (
    PotaSpotSourceAvailability,
    PotaSpotSourceConnectionError,
    PotaSpotSourceResponseError,
)

_FIXED_TIME = datetime(2026, 7, 26, 22, 40, tzinfo=UTC)


class FakeResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self._status_code = status_code
        self._body = body

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def body(self) -> bytes:
        return self._body


class FakeTransport:
    def __init__(
        self,
        response: FakeResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response or FakeResponse(200, b"[]")
        self.error = error
        self.requests: list[tuple[str, str, Mapping[str, str], bytes | None, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> FakeResponse:
        self.requests.append((method, url, headers, body, timeout_s))
        if self.error is not None:
            raise self.error
        return self.response


def _payload(*items: object) -> bytes:
    return dumps(list(items)).encode("utf-8")


def _spot(
    *,
    activator: str = "KI5VNB/P",
    frequency: str = "14250.0",
    mode: str = "SSB",
    reference: str = "US-1234",
    spot_time: str = "2026-07-26T18:30:00",
    comments: str = "Strong signal",
    name: str = "Caesar Creek State Park",
) -> dict[str, object]:
    return {
        "activator": activator,
        "frequency": frequency,
        "mode": mode,
        "reference": reference,
        "spotTime": spot_time,
        "comments": comments,
        "name": name,
        "parkName": None,
    }


def test_fetch_spots_parses_public_api_shape() -> None:
    transport = FakeTransport(
        FakeResponse(
            200,
            _payload(
                _spot(),
                _spot(
                    activator="W8O",
                    frequency="7074",
                    mode="FT8",
                    reference="US-0002",
                    spot_time="2026-07-26T18:31:00Z",
                ),
            ),
        )
    )
    source = HttpPotaSpotSource(
        transport=transport,
        timeout_s=3.5,
        now=lambda: _FIXED_TIME,
    )

    result = source.fetch_spots()

    assert result.availability is PotaSpotSourceAvailability.AVAILABLE
    assert result.fetched_at == _FIXED_TIME
    assert len(result.spots) == 2
    assert result.spots[0].frequency.hz == 14_250_000
    assert result.spots[0].mode is RadioMode.USB
    assert result.spots[0].spotted_at == datetime(2026, 7, 26, 18, 30, tzinfo=UTC)
    assert result.spots[0].park.name == "Caesar Creek State Park"
    assert result.spots[1].mode is RadioMode.DATA
    assert transport.requests == [
        (
            "GET",
            "https://api.pota.app/spot/activator",
            {"Accept": "application/json"},
            None,
            3.5,
        )
    ]


def test_ssb_below_ten_mhz_maps_to_lsb() -> None:
    transport = FakeTransport(
        FakeResponse(200, _payload(_spot(frequency="7200", mode="SSB")))
    )

    result = HttpPotaSpotSource(transport=transport, now=lambda: _FIXED_TIME).fetch_spots()

    assert result.spots[0].mode is RadioMode.LSB


def test_empty_array_is_available_with_no_spots() -> None:
    result = HttpPotaSpotSource(
        transport=FakeTransport(),
        now=lambda: _FIXED_TIME,
    ).fetch_spots()

    assert result.availability is PotaSpotSourceAvailability.AVAILABLE
    assert result.spots == ()


def test_unusable_rows_are_skipped_when_valid_rows_remain() -> None:
    transport = FakeTransport(
        FakeResponse(
            200,
            _payload(
                _spot(activator="F/ON4LDU/P"),
                _spot(mode=""),
                _spot(activator="W8O", reference="US-0003"),
            ),
        )
    )

    result = HttpPotaSpotSource(transport=transport, now=lambda: _FIXED_TIME).fetch_spots()

    assert [spot.activator for spot in result.spots] == ["W8O"]


def test_non_array_or_all_unusable_payload_is_rejected() -> None:
    non_array = FakeTransport(FakeResponse(200, b'{"spots": []}'))
    with pytest.raises(PotaSpotSourceResponseError, match="JSON array"):
        HttpPotaSpotSource(transport=non_array).fetch_spots()

    unusable = FakeTransport(FakeResponse(200, _payload(_spot(mode=""))))
    with pytest.raises(PotaSpotSourceResponseError, match="no usable"):
        HttpPotaSpotSource(transport=unusable).fetch_spots()


@pytest.mark.parametrize("body", [b"not json", b"\xff"])
def test_invalid_json_is_rejected(body: bytes) -> None:
    source = HttpPotaSpotSource(transport=FakeTransport(FakeResponse(200, body)))

    with pytest.raises(PotaSpotSourceResponseError, match="invalid JSON"):
        source.fetch_spots()


def test_http_and_transport_failures_raise_connection_error() -> None:
    with pytest.raises(PotaSpotSourceConnectionError, match="HTTP 503"):
        HttpPotaSpotSource(
            transport=FakeTransport(FakeResponse(503, b"unavailable"))
        ).fetch_spots()

    with pytest.raises(PotaSpotSourceConnectionError, match="could not be reached"):
        HttpPotaSpotSource(
            transport=FakeTransport(error=URLError("offline"))
        ).fetch_spots()


@pytest.mark.parametrize(
    "base_url",
    ["", "api.pota.app", "ftp://api.pota.app", "https://api.pota.app?x=1"],
)
def test_invalid_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(ValueError, match="POTA base URL"):
        HttpPotaSpotSource(base_url)


def test_timeout_and_clock_must_be_valid() -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        HttpPotaSpotSource(timeout_s=0)

    source = HttpPotaSpotSource(
        transport=FakeTransport(),
        now=lambda: datetime(2026, 7, 26, 22, 40),  # noqa: DTZ001
    )
    with pytest.raises(ValueError, match="aware datetime"):
        source.fetch_spots()
