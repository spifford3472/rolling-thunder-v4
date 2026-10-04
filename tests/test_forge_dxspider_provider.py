"""Tests for the persistent Forge DXSpider stream provider."""

from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from rolling_thunder.forge_config import ForgeDxSpiderProviderConfig
from rolling_thunder.forge_dxspider_provider import (
    DxSpiderConnectionState,
    DxSpiderSession,
    ForgeDxSpiderSpotProvider,
    strip_telnet_negotiation,
)
from rolling_thunder.forge_spot_provider import ForgeSpotProviderConnectionError
from rolling_thunder.spot_domain import SpotProvider


BASE_TIME = datetime(2026, 8, 6, 2, 5, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime = BASE_TIME) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class MutableMonotonic:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class FakeDxSpiderSession:
    """Deterministic chunked session that records commands and cleanup."""

    def __init__(
        self,
        chunks: list[bytes | None | Exception],
        *,
        send_error: Exception | None = None,
        on_empty=None,
    ) -> None:
        self._chunks = deque(chunks)
        self._send_error = send_error
        self._on_empty = on_empty
        self.sent_lines: list[str] = []
        self.read_limits: list[int] = []
        self.closed = False

    def send_line(self, line: str) -> None:
        self.sent_lines.append(line)
        if self._send_error is not None:
            raise self._send_error

    def read(self, max_bytes: int) -> bytes | None:
        self.read_limits.append(max_bytes)
        if not self._chunks:
            if self._on_empty is not None:
                self._on_empty()
            return None

        item = self._chunks.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


class FakeDxSpiderSessionFactory:
    """Factory recording connection settings for deterministic sessions."""

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
    values: dict[str, object] = {
        "enabled": True,
        "host": "dx.example.invalid",
        "port": 7300,
        "login_callsign": "KI5VNB",
        "connect_timeout_s": 3.0,
        "read_timeout_s": 4.0,
        "inactivity_timeout_s": 600.0,
        "reconnect_initial_s": 5.0,
        "reconnect_max_s": 300.0,
        "stable_connection_s": 300.0,
        "max_response_bytes": 4_096,
        "max_spots": 10,
        "max_spot_age_s": 3_600.0,
    }
    values.update(updates)
    return ForgeDxSpiderProviderConfig.model_validate(values)


def provider_for(
    session: FakeDxSpiderSession,
    *,
    clock: MutableClock | None = None,
    monotonic_clock: MutableMonotonic | None = None,
    config: ForgeDxSpiderProviderConfig | None = None,
) -> tuple[ForgeDxSpiderSpotProvider, FakeDxSpiderSessionFactory]:
    factory = FakeDxSpiderSessionFactory(session)
    provider = ForgeDxSpiderSpotProvider(
        config or dx_config(),
        session_factory=factory,
        clock=clock or MutableClock(),
        monotonic_clock=monotonic_clock or MutableMonotonic(),
    )
    return provider, factory


def test_fetch_slice_is_cache_only_and_rejects_non_live_state() -> None:
    session = FakeDxSpiderSession([])
    provider, factory = provider_for(session)

    with pytest.raises(ForgeSpotProviderConnectionError, match="not live"):
        provider.fetch_slice()

    assert factory.open_calls == []
    assert provider.connection_state is DxSpiderConnectionState.DISCONNECTED


def test_initial_connection_seeds_once_and_never_sends_bye_during_live_session() -> None:
    session = FakeDxSpiderSession(
        [
            (
                b"Welcome\r\n"
                b"DX de K1ABC: 14074.0 W1AW FT8 FN31 0204Z\r\n"
            )
        ]
    )
    provider, _ = provider_for(session)

    provider._send_initial_commands(session)
    provider._set_state(DxSpiderConnectionState.LIVE)
    provider._stop.set()
    provider._consume_session(session)

    assert session.sent_lines == ["KI5VNB", "set/page 0", "show/fdx"]
    assert "bye" not in session.sent_lines


def test_live_stream_populates_cache_and_fetch_uses_no_network() -> None:
    session = FakeDxSpiderSession(
        [
            b"DX de K1ABC: 14074.0 W1AW FT8 FN31 0204Z\r\n",
        ]
    )
    provider, factory = provider_for(session)

    provider._set_state(DxSpiderConnectionState.LIVE)
    provider._stop.clear()

    def stop_after_read() -> None:
        provider._stop.set()

    session._on_empty = stop_after_read
    provider._consume_session(session)
    provider._stop.clear()

    before = list(factory.open_calls)
    provider_slice = provider.fetch_slice()

    assert provider_slice.provider is SpotProvider.DX
    assert [spot.stable_key for spot in provider_slice.spots] == ["dx:W1AW:14074000"]
    assert factory.open_calls == before


def test_telnet_negotiation_is_removed_before_parsing() -> None:
    negotiation = bytes([255, 251, 1, 255, 250, 24, 1, 255, 240])
    session = FakeDxSpiderSession(
        [negotiation + b"DX de K1ABC: 7002.5 WI3W CW 0204Z\r\n"]
    )
    provider, _ = provider_for(session)

    provider._set_state(DxSpiderConnectionState.LIVE)
    provider._stop.clear()
    session._on_empty = provider._stop.set
    provider._consume_session(session)
    provider._stop.clear()

    assert [spot.stable_key for spot in provider.fetch_slice().spots] == [
        "dx:WI3W:7002500"
    ]


def test_telnet_literal_iac_is_preserved() -> None:
    assert strip_telnet_negotiation(b"A\xff\xffB") == b"A\xffB"


def test_inactivity_timeout_detects_half_dead_connection() -> None:
    monotonic_clock = MutableMonotonic()
    session = FakeDxSpiderSession([None, None])
    provider, _ = provider_for(
        session,
        monotonic_clock=monotonic_clock,
        config=dx_config(inactivity_timeout_s=60),
    )

    class AdvancingSession(FakeDxSpiderSession):
        def read(self, max_bytes: int) -> bytes | None:
            monotonic_clock.value += 31.0
            return None

    with pytest.raises(ConnectionError, match="inactivity"):
        provider._consume_session(AdvancingSession([]))


def test_cache_prunes_stale_spots_without_network_activity() -> None:
    clock = MutableClock()
    session = FakeDxSpiderSession(
        [b"DX de K1ABC: 14074.0 W1AW FT8 0204Z\r\n"]
    )
    provider, factory = provider_for(
        session,
        clock=clock,
        config=dx_config(max_spot_age_s=60),
    )
    provider._set_state(DxSpiderConnectionState.LIVE)
    provider._stop.clear()
    session._on_empty = provider._stop.set
    provider._consume_session(session)
    provider._stop.clear()

    assert provider.fetch_slice().spots
    clock.value += timedelta(minutes=2)

    assert provider.fetch_slice().spots == ()
    assert len(factory.open_calls) == 0


def test_cache_is_bounded_to_newest_spots() -> None:
    session = FakeDxSpiderSession(
        [
            (
                b"DX de A1AAA: 14250.0 W1AAA USB 0202Z\r\n"
                b"DX de A2AAA: 14251.0 W2AAA USB 0203Z\r\n"
                b"DX de A3AAA: 14252.0 W3AAA USB 0204Z\r\n"
            )
        ]
    )
    provider, _ = provider_for(
        session,
        config=dx_config(max_spots=2),
    )
    provider._set_state(DxSpiderConnectionState.LIVE)
    provider._stop.clear()
    session._on_empty = provider._stop.set
    provider._consume_session(session)
    provider._stop.clear()

    assert {str(spot.callsign) for spot in provider.fetch_slice().spots} == {
        "W2AAA",
        "W3AAA",
    }


def test_connection_age_never_expires_live_source() -> None:
    clock = MutableClock()
    session = FakeDxSpiderSession(
        [b"DX de K1ABC: 14074.0 W1AW FT8 0204Z\r\n"]
    )
    provider, _ = provider_for(session, clock=clock)
    provider._set_state(DxSpiderConnectionState.LIVE)
    provider._stop.clear()
    session._on_empty = provider._stop.set
    provider._consume_session(session)
    provider._stop.clear()

    clock.value += timedelta(days=90)

    assert provider.connection_state is DxSpiderConnectionState.LIVE
    assert provider.fetch_slice().spots == ()


def test_open_failure_is_mapped_without_changing_fetch_contract() -> None:
    factory = FakeDxSpiderSessionFactory(error=OSError("connect failed"))
    provider = ForgeDxSpiderSpotProvider(
        dx_config(),
        session_factory=factory,
        clock=MutableClock(),
    )

    with pytest.raises(ForgeSpotProviderConnectionError, match="established"):
        provider._open_session()


def test_naive_clock_is_rejected_without_network_activity() -> None:
    session = FakeDxSpiderSession([])
    factory = FakeDxSpiderSessionFactory(session)
    provider = ForgeDxSpiderSpotProvider(
        dx_config(),
        session_factory=factory,
        clock=lambda: datetime(2026, 8, 6, 2, 5),  # noqa: DTZ001
    )
    provider._set_state(DxSpiderConnectionState.LIVE)

    with pytest.raises(ValueError, match="aware datetime"):
        provider.fetch_slice()

    assert factory.open_calls == []
