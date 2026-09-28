from collections.abc import Mapping
from dataclasses import dataclass

import pytest
from pydantic import SecretStr

from rolling_thunder.application_secrets import QrzCredentials
from rolling_thunder.qrz_xml import (
    QrzAuthenticationError,
    QrzXmlCallsignNameProvider,
    normalize_qrz_callsign,
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
        del body, timeout_s
        self.requests.append((url, headers))
        return self.responses.pop(0)


def credentials() -> QrzCredentials:
    return QrzCredentials(
        username="KI5VNB",
        password=SecretStr("private-value"),
    )


def xml(body: str) -> FakeResponse:
    return FakeResponse(status_code=200, body=body.encode("utf-8"))


def test_normalize_qrz_callsign_removes_portable_suffix() -> None:
    assert normalize_qrz_callsign(" ki5vnb/p ") == "KI5VNB"


def test_lookup_logs_in_once_and_reuses_session_key() -> None:
    transport = SequenceTransport(
        [
            xml(
                """
                <QRZDatabase xmlns="http://xmldata.qrz.com">
                  <Session><Key>SESSION-1</Key></Session>
                </QRZDatabase>
                """
            ),
            xml(
                """
                <QRZDatabase xmlns="http://xmldata.qrz.com">
                  <Callsign>
                    <call>KI5VNB</call>
                    <fname>Geoff</fname>
                    <name>KLINE</name>
                    <image>https://cdn-xml.qrz.com/ki5vnb.jpg</image>
                    <grid>em79XM</grid>
                  </Callsign>
                  <Session><Key>SESSION-1</Key></Session>
                </QRZDatabase>
                """
            ),
            xml(
                """
                <QRZDatabase xmlns="http://xmldata.qrz.com">
                  <Callsign>
                    <call>W8O</call>
                    <fname>Special</fname>
                    <name>Event</name>
                  </Callsign>
                  <Session><Key>SESSION-1</Key></Session>
                </QRZDatabase>
                """
            ),
        ]
    )
    provider = QrzXmlCallsignNameProvider(
        credentials(),
        transport=transport,
    )

    profile = provider.lookup_profile("KI5VNB/P")
    assert profile is not None
    assert profile.callsign == "KI5VNB"
    assert profile.name == "Geoff KLINE"
    assert profile.image_url == "https://cdn-xml.qrz.com/ki5vnb.jpg"
    assert profile.grid == "EM79xm"
    assert provider.lookup_name("W8O") == "Special Event"

    assert len(transport.requests) == 3
    assert "username=KI5VNB" in transport.requests[0][0]
    assert "password=private-value" in transport.requests[0][0]
    assert "s=SESSION-1" in transport.requests[1][0]
    assert "callsign=KI5VNB" in transport.requests[1][0]
    assert "s=SESSION-1" in transport.requests[2][0]


def test_lookup_ignores_invalid_qrz_grid() -> None:
    transport = SequenceTransport(
        [
            xml("<QRZDatabase><Session><Key>SESSION</Key></Session></QRZDatabase>"),
            xml(
                """
                <QRZDatabase>
                  <Callsign>
                    <call>W8O</call>
                    <grid>INVALID</grid>
                  </Callsign>
                  <Session><Key>SESSION</Key></Session>
                </QRZDatabase>
                """
            ),
        ]
    )
    provider = QrzXmlCallsignNameProvider(credentials(), transport=transport)

    profile = provider.lookup_profile("W8O")

    assert profile is not None
    assert profile.grid is None


def test_lookup_returns_none_for_unknown_callsign() -> None:
    transport = SequenceTransport(
        [
            xml("<QRZDatabase><Session><Key>SESSION</Key></Session></QRZDatabase>"),
            xml(
                """
                <QRZDatabase>
                  <Session>
                    <Key>SESSION</Key>
                    <Error>Not found: TEST1</Error>
                  </Session>
                </QRZDatabase>
                """
            ),
        ]
    )
    provider = QrzXmlCallsignNameProvider(credentials(), transport=transport)

    assert provider.lookup_name("TEST1") is None


def test_authentication_failure_never_includes_password() -> None:
    transport = SequenceTransport(
        [
            xml(
                """
                <QRZDatabase>
                  <Session><Error>Invalid username or password</Error></Session>
                </QRZDatabase>
                """
            )
        ]
    )
    provider = QrzXmlCallsignNameProvider(credentials(), transport=transport)

    with pytest.raises(QrzAuthenticationError) as captured:
        provider.lookup_name("KI5VNB")

    assert "private-value" not in str(captured.value)
