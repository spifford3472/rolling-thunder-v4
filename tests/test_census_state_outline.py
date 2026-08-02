from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from rolling_thunder.census_state_outline import (
    CensusStateOutlineError,
    CensusStateOutlineProvider,
)


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    body: bytes


class SequenceTransport:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, Mapping[str, str]]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> FakeResponse:
        del method, body, timeout_s
        self.requests.append((url, headers))
        return self.responses.pop(0)


def response(body: bytes, status_code: int = 200) -> FakeResponse:
    return FakeResponse(status_code=status_code, body=body)


def metadata(url: str, name: str) -> bytes:
    return (
        '{"boundaryName":"'
        + name
        + '","simplifiedGeometryGeoJSON":"'
        + url
        + '"}'
    ).encode()


def feature(code: str, name: str) -> bytes:
    return (
        '{"type":"FeatureCollection","features":[{'
        '"type":"Feature","properties":{"shapeISO":"'
        + code
        + '","shapeName":"'
        + name
        + '"},"geometry":{"type":"Polygon",'
        '"coordinates":[[[-84.8,38.4],[-80.5,38.4],'
        '[-80.5,42.0],[-84.8,42.0],[-84.8,38.4]]]}}]}'
    ).encode()


def test_fetch_outline_parses_generalized_state_geojson() -> None:
    transport = SequenceTransport(
        [
            response(
                b'{"type":"FeatureCollection","features":[{'
                b'"type":"Feature","properties":{"STUSAB":"OH",'
                b'"NAME":"Ohio"},"geometry":{"type":"Polygon",'
                b'"coordinates":[[[-84.8,38.4],[-80.5,38.4],'
                b'[-80.5,42.0],[-84.8,42.0],[-84.8,38.4]]]}}]}'
            )
        ]
    )
    provider = CensusStateOutlineProvider(transport=transport)

    outline = provider.fetch_outline("US-OH")

    assert outline is not None
    assert outline.state_code == "OH"
    assert outline.state_name == "Ohio"
    assert len(outline.rings) == 1
    assert outline.rings[0][0] == (-84.8, 38.4)
    assert "STUSAB%3D%27OH%27" in transport.requests[0][0]
    assert "f=geojson" in transport.requests[0][0]


def test_dx_location_uses_matching_adm1_outline() -> None:
    transport = SequenceTransport(
        [
            response(metadata("https://example.test/can-adm1.json", "Canada")),
            response(feature("CA-ON", "Ontario")),
        ]
    )
    provider = CensusStateOutlineProvider(transport=transport)

    outline = provider.fetch_outline("CA-ON")

    assert outline is not None
    assert outline.state_code == "CA-ON"
    assert outline.state_name == "Ontario"
    assert "/CAN/ADM1/" in transport.requests[0][0]
    assert transport.requests[1][0] == "https://example.test/can-adm1.json"


def test_dx_location_falls_back_to_country_when_adm1_code_does_not_match() -> None:
    transport = SequenceTransport(
        [
            response(metadata("https://example.test/can-adm1.json", "Canada")),
            response(feature("CA-QC", "Quebec")),
            response(metadata("https://example.test/can-adm0.json", "Canada")),
            response(feature("CA", "Canada")),
        ]
    )
    provider = CensusStateOutlineProvider(transport=transport)

    outline = provider.fetch_outline("CA-ON")

    assert outline is not None
    assert outline.state_code == "CA"
    assert outline.state_name == "Canada"
    assert "/CAN/ADM0/" in transport.requests[2][0]


def test_missing_location_code_does_not_start_http_request() -> None:
    transport = SequenceTransport([])
    provider = CensusStateOutlineProvider(transport=transport)

    assert provider.fetch_outline(None) is None
    assert transport.requests == []


def test_empty_census_feature_set_is_actionable() -> None:
    provider = CensusStateOutlineProvider(
        transport=SequenceTransport([response(b'{"features":[]}')])
    )

    with pytest.raises(CensusStateOutlineError, match="no outline"):
        provider.fetch_outline("US-OH")
