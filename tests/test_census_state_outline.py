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


class FakeTransport:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
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
        return self.response


def test_fetch_outline_parses_generalized_state_geojson() -> None:
    transport = FakeTransport(
        FakeResponse(
            status_code=200,
            body=(
                b'{"type":"FeatureCollection","features":[{'
                b'"type":"Feature","properties":{"STUSAB":"OH",'
                b'"NAME":"Ohio"},"geometry":{"type":"Polygon",'
                b'"coordinates":[[[-84.8,38.4],[-80.5,38.4],'
                b'[-80.5,42.0],[-84.8,42.0],[-84.8,38.4]]]}}]}'
            ),
        )
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


def test_non_us_location_does_not_start_http_request() -> None:
    transport = FakeTransport(FakeResponse(status_code=200, body=b"{}"))
    provider = CensusStateOutlineProvider(transport=transport)

    assert provider.fetch_outline("CA-ON") is None
    assert transport.requests == []


def test_empty_census_feature_set_is_actionable() -> None:
    provider = CensusStateOutlineProvider(
        transport=FakeTransport(
            FakeResponse(status_code=200, body=b'{"features":[]}')
        )
    )

    with pytest.raises(CensusStateOutlineError, match="no outline"):
        provider.fetch_outline("US-OH")
