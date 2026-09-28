"""Focused Wavelog HTTP failure classification tests."""

from collections.abc import Mapping

import pytest
from pydantic import SecretStr

from rolling_thunder.http_home_platform import UrllibHttpResponse
from rolling_thunder.wavelog import WavelogAuthenticationError, WavelogClient


class UnauthorizedHtmlTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        del method, url, headers, body, timeout_s
        return UrllibHttpResponse(401, b"<html>login required</html>")


def test_authentication_error_does_not_depend_on_json_error_body() -> None:
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("do-not-leak"),
        station_location_name="Mobile",
        transport=UnauthorizedHtmlTransport(),
    )

    with pytest.raises(WavelogAuthenticationError) as raised:
        client.resolve_station_location()

    assert "401" in str(raised.value)
    assert "do-not-leak" not in str(raised.value)
