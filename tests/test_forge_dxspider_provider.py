"""Tests for the bounded Forge DXSpider snapshot provider."""

from collections import deque
from datetime import UTC, datetime
from typing import Any

import pytest

from rolling_thunder.forge_config import ForgeDxSpiderProviderConfig
from rolling_thunder.forge_dxspider_provider import (
    DxSpiderSession,
    ForgeDxSpiderSpotProvider,
    strip_telnet_negotiation,
)
from rolling_thunder.forge_spot_provider import (
    ForgeSpotProviderConnectionError,
    ForgeSpotProviderResponseError,
)
from rolling_thunder.spot_domain import SpotProvider


class FakeDxSpiderSession:
    """Deterministic chunked session that records commands and cleanup."""

    def __init__(
        self,
        chunks: list[bytes | Exception],
        *,
        send_error: Exception | None = None,
    ) -> None:
        self._chunks = deque(chunks)
        self._send_error = send_error
        self.sent_lines: list[str] = []
        self.read_limits: list[int] = []
        self.closed = False

    def send_line(self, line: str) -> None:
        self.sent_lines.append(line)
        if self._send_error is not None:
            raise self._send_error

    def read(self, max_bytes: int) -> bytes:
        self.read_limits.append(max_bytes)
        if not self._chunks:
            return b""

        item = self._chunks.popleft()
        if isinstance(item, Exception):
            raise item
        if len(item) <= max_bytes:
            return item

        self._chunks.appendleft(item[max_bytes:])
        return item[:max_bytes]

    def close(self) -> None:
        self.closed = True


class FakeDxSpiderSessionFactory:
    """Factory recording connection settings for one deterministic session."""

    def __init__(
        self,
        session: DxSpiderSession | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._session = session
        self._error = error
        self.open_calls: list[dict[str, Any]] = []

    def open(
        self,
        *,
        host: str,
        port: int,
        connect_timeout_s: float,
        read_timeout_s: float,
    ) -> DxSpiderSession:
        self.open_calls.append(
            {
                "host": host,
                "port": port,
                "connect_timeout_s": connect_timeout_s,
                "read_timeout_s": read_timeout_s,
            }
        )
        if self._error is not None:
            raise self._error
        if self._session is None:
            raise AssertionError("fake session was not configured")
        return self._session


def dx_config(**updates: object) -> ForgeDxSpiderProviderConfig:
    """Build one validated enabled DXSpider test configuration."""
    values: dict[str, object] = {
        "enabled": True,
        "host": "dx.example.invalid",
        "port": 7300,
        "login_callsign": "KI5VNB",
        "connect_timeout_s": 3.0,
        "read_timeout_s": 4.0,
        "max_response_bytes": 4_096,
        "max_spots": 10,
        "max_spot_age_s": 3_600.0,
    }
    values.update(updates)
    return ForgeDxSpiderProviderConfig.model_validate(values)


def provider_for(
    session: FakeDxSpiderSession,
    *,
    fetched_at: datetime | None = None,
    config: ForgeDxSpiderProviderConfig | None = None,
) -> tuple[ForgeDxSpiderSpotProvider, FakeDxSpiderSessionFactory]:
    """Compose one provider with deterministic clock and session factory."""
    factory = FakeDxSpiderSessionFactory(session)
    now = fetched_at or datetime(2026, 8, 6, 2, 5, tzinfo=UTC)
    provider = ForgeDxSpiderSpotProvider(
        config or dx_config(),
        session_factory=factory,
        clock=lambda: now,
    )
    return provider, factory


def test_provider_executes_bounded_snapshot_session_and_closes() -> None:
    session = FakeDxSpiderSession(
        [
            b"Welcome\r\n"
            b"DX de K1ABC: 14074.0 W1AW FT8 FN31 0204Z\r\n",
            b"",
        ]
    )
    provider, factory = provider_for(session)

    provider_slice = provider.fetch_slice()

    assert provider_slice.provider is SpotProvider.DX
    assert provider_slice.fetched_at == datetime(2026, 8, 6, 2, 5, tzinfo=UTC)
    assert [spot.stable_key for spot in provider_slice.spots] == ["dx:W1AW:14074000"]
    assert session.sent_lines == ["KI5VNB", "set/page 0", "show/fdx", "bye"]
    assert session.closed is True
    assert factory.open_calls == [
        {
            "host": "dx.example.invalid",
            "port": 7300,
            "connect_timeout_s": 3.0,
            "read_timeout_s": 4.0,
        }
    ]


def test_telnet_negotiation_is_removed_before_parsing() -> None:
    negotiation = bytes([255, 251, 1, 255, 250, 24, 1, 255, 240])
    payload = negotiation + b"DX de K1ABC: 7002.5 WI3W CW 0204Z\r\n"
    session = FakeDxSpiderSession([payload, b""])
    provider, _ = provider_for(session)

    provider_slice = provider.fetch_slice()

    assert [spot.stable_key for spot in provider_slice.spots] == ["dx:WI3W:7002500"]


def test_telnet_literal_iac_is_preserved() -> None:
    assert strip_telnet_negotiation(b"A\xff\xffB") == b"A\xffB"


def test_clean_response_without_spot_lines_is_valid_empty_slice() -> None:
    session = FakeDxSpiderSession([b"Welcome\r\nKI5VNB de NODE >\r\n", b""])
    provider, _ = provider_for(session)

    provider_slice = provider.fetch_slice()

    assert provider_slice.spots == ()
    assert session.closed is True


def test_empty_response_is_typed_failure_and_closes_session() -> None:
    session = FakeDxSpiderSession([b""])
    provider, _ = provider_for(session)

    with pytest.raises(ForgeSpotProviderResponseError, match="empty response"):
        provider.fetch_slice()

    assert session.closed is True


def test_response_byte_limit_is_enforced() -> None:
    session = FakeDxSpiderSession([b"x" * 4_097, b""])
    provider, _ = provider_for(session)

    with pytest.raises(ForgeSpotProviderResponseError, match="byte limit"):
        provider.fetch_slice()

    assert session.closed is True


def test_read_timeout_is_connection_failure_and_closes_session() -> None:
    session = FakeDxSpiderSession([TimeoutError("read timed out")])
    provider, _ = provider_for(session)

    with pytest.raises(ForgeSpotProviderConnectionError, match="did not complete"):
        provider.fetch_slice()

    assert session.closed is True


def test_send_failure_is_connection_failure_and_closes_session() -> None:
    session = FakeDxSpiderSession([], send_error=OSError("send failed"))
    provider, _ = provider_for(session)

    with pytest.raises(ForgeSpotProviderConnectionError, match="did not complete"):
        provider.fetch_slice()

    assert session.closed is True


def test_open_failure_is_mapped_without_creating_session() -> None:
    factory = FakeDxSpiderSessionFactory(error=OSError("connect failed"))
    provider = ForgeDxSpiderSpotProvider(
        dx_config(),
        session_factory=factory,
        clock=lambda: datetime(2026, 8, 6, 2, 5, tzinfo=UTC),
    )

    with pytest.raises(ForgeSpotProviderConnectionError, match="established"):
        provider.fetch_slice()


def test_spot_age_filter_retains_only_recent_records() -> None:
    session = FakeDxSpiderSession(
        [
            b"DX de K1ABC: 14074.0 W1AW FT8 0204Z\r\n"
            b"DX de K1ABC: 14250.0 K2OLD SSB 0000Z\r\n",
            b"",
        ]
    )
    provider, _ = provider_for(session)

    provider_slice = provider.fetch_slice()

    assert [spot.callsign for spot in provider_slice.spots] == ["W1AW"]


def test_valid_but_expired_records_produce_valid_empty_slice() -> None:
    session = FakeDxSpiderSession(
        [b"DX de K1ABC: 14250.0 K2OLD SSB 0000Z\r\n", b""]
    )
    provider, _ = provider_for(session)

    provider_slice = provider.fetch_slice()

    assert provider_slice.spots == ()


def test_all_malformed_spot_like_lines_are_typed_failure() -> None:
    session = FakeDxSpiderSession(
        [b"DX de K1ABC: 14074.0005 NOT-A-CALL FT8 0204Z\r\n", b""]
    )
    provider, _ = provider_for(session)

    with pytest.raises(ForgeSpotProviderResponseError, match="no usable DX records"):
        provider.fetch_slice()


def test_malformed_line_does_not_discard_valid_records() -> None:
    session = FakeDxSpiderSession(
        [
            b"DX de K1ABC: 14074.0005 NOT-A-CALL FT8 0204Z\r\n"
            b"DX de K1ABC: 14074.0 W1AW FT8 0204Z\r\n",
            b"",
        ]
    )
    provider, _ = provider_for(session)

    provider_slice = provider.fetch_slice()

    assert [spot.callsign for spot in provider_slice.spots] == ["W1AW"]


def test_maximum_spot_count_bounds_accepted_slice() -> None:
    session = FakeDxSpiderSession(
        [
            b"DX de K1ABC: 7002.0 W1AAA CW 0204Z\r\n"
            b"DX de K1ABC: 7003.0 W1BBB CW 0204Z\r\n",
            b"",
        ]
    )
    provider, _ = provider_for(session, config=dx_config(max_spots=1))

    provider_slice = provider.fetch_slice()

    assert len(provider_slice.spots) == 1


def test_duplicate_identity_collapses_to_newest_record() -> None:
    session = FakeDxSpiderSession(
        [
            b"DX de K1ABC: 14074.0 W1AW FT8 first 0203Z\r\n"
            b"DX de K2ABC: 14074.0 W1AW FT8 second 0204Z\r\n",
            b"",
        ]
    )
    provider, _ = provider_for(session)

    provider_slice = provider.fetch_slice()

    assert len(provider_slice.spots) == 1
    assert provider_slice.spots[0].spotted_at == datetime(2026, 8, 6, 2, 4, tzinfo=UTC)
    assert {item.key: item.value for item in provider_slice.spots[0].source_metadata}[
        "spotter"
    ] == "K2ABC"


def test_naive_clock_value_is_rejected_before_opening_session() -> None:
    session = FakeDxSpiderSession([b"ignored"])
    factory = FakeDxSpiderSessionFactory(session)
    provider = ForgeDxSpiderSpotProvider(
        dx_config(),
        session_factory=factory,
        clock=lambda: datetime(2026, 8, 6, 2, 5),
    )

    with pytest.raises(ValueError, match="aware datetime"):
        provider.fetch_slice()

    assert factory.open_calls == []
    assert session.closed is False
