"""Tests for the persistent read-only DX Summit IRC provider core."""

from collections import deque
from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.domain import RadioMode
from rolling_thunder.forge_dxsummit_provider import (
    DxSummitConnectionState,
    ForgeDxSummitSpotProvider,
)
from rolling_thunder.forge_spot_provider import ForgeSpotProviderConnectionError

BASE_TIME = datetime(2026, 10, 4, 1, 31, 40, tzinfo=UTC)
DXS_LINE = (
    ":dxs!dxs@static.101.3.180.157.clients.your-server.de PRIVMSG #CQDX :"
    "\x031,15AA4CS       14270.0 NX6T        USB                           0131"
)


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


class ScriptedSession:
    def __init__(
        self,
        lines: tuple[str | None, ...],
        *,
        on_empty=None,
    ) -> None:
        self.lines = deque(lines)
        self.on_empty = on_empty
        self.sent: list[str] = []
        self.close_count = 0

    def send_line(self, line: str) -> None:
        self.sent.append(line)

    def read_line(self) -> str | None:
        if self.lines:
            return self.lines.popleft()
        if self.on_empty is not None:
            self.on_empty()
        return None

    def close(self) -> None:
        self.close_count += 1


def provider(
    *,
    clock=None,
    monotonic_clock=None,
    max_spot_age_s: float = 3600.0,
    max_spots: int = 500,
) -> ForgeDxSummitSpotProvider:
    return ForgeDxSummitSpotProvider(
        host="irc.radiochat.org",
        port=6667,
        channel="#CQDX",
        nickname="KI5VNB",
        inactivity_timeout_s=600.0,
        reconnect_initial_s=5.0,
        reconnect_max_s=300.0,
        stable_connection_s=300.0,
        max_spot_age_s=max_spot_age_s,
        max_spots=max_spots,
        clock=clock,
        monotonic_clock=monotonic_clock or (lambda: 100.0),
    )


def test_fetch_slice_is_cache_only_and_rejects_non_live_state() -> None:
    source = provider(clock=MutableClock())

    with pytest.raises(ForgeSpotProviderConnectionError, match="not live"):
        source.fetch_slice()

    assert source.status.state is DxSummitConnectionState.DISCONNECTED
    assert source.status.cache_size == 0


def test_session_registration_join_ping_and_live_spot_are_read_only() -> None:
    clock = MutableClock()
    monotonic_clock = MutableMonotonic()
    source = provider(clock=clock, monotonic_clock=monotonic_clock)
    session = ScriptedSession(
        (
            "PING :Newark.NJ.US.WorldIRC.Org",
            ":Newark.NJ.US.WorldIRC.Org 001 KI5VNB :Welcome",
            ":Newark.NJ.US.WorldIRC.Org 366 KI5VNB #CQDX :End of /NAMES list.",
            DXS_LINE,
        ),
        on_empty=source._stop.set,
    )

    live_started = source._consume_session(session)

    assert live_started == 100.0
    assert session.sent == [
        "PONG :Newark.NJ.US.WorldIRC.Org",
        "JOIN #CQDX",
    ]
    assert source.status.state is DxSummitConnectionState.LIVE
    assert source.status.cache_size == 1
    assert source.status.last_spot_at == BASE_TIME

    source._stop.clear()
    snapshot = source.fetch_slice()

    assert len(snapshot.spots) == 1
    assert str(snapshot.spots[0].callsign) == "NX6T"
    assert snapshot.spots[0].frequency.hz == 14_270_000
    assert snapshot.spots[0].mode is RadioMode.USB


def test_nickname_collision_uses_predictable_fallback_without_disconnect() -> None:
    source = provider(clock=MutableClock())
    session = ScriptedSession(
        (
            ":Newark.NJ.US.WorldIRC.Org 433 * KI5VNB :Nickname is already in use",
            ":Newark.NJ.US.WorldIRC.Org 433 * KI5VNB-RT :Nickname is already in use",
            ":Newark.NJ.US.WorldIRC.Org 001 KI5VNB-RT2 :Welcome",
            ":Newark.NJ.US.WorldIRC.Org 366 KI5VNB-RT2 #CQDX :End of /NAMES list.",
        ),
        on_empty=source._stop.set,
    )

    source._consume_session(session)

    assert session.sent == [
        "NICK KI5VNB-RT",
        "NICK KI5VNB-RT2",
        "JOIN #CQDX",
    ]
    assert source.status.nickname == "KI5VNB-RT2"
    assert source.status.state is DxSummitConnectionState.LIVE


def test_inactivity_timeout_detects_half_dead_connection() -> None:
    monotonic_clock = MutableMonotonic()
    source = provider(
        clock=MutableClock(),
        monotonic_clock=monotonic_clock,
    )

    class IdleSession(ScriptedSession):
        def read_line(self) -> str | None:
            monotonic_clock.value += 301.0
            return None

    with pytest.raises(ConnectionError, match="inactivity"):
        source._consume_session(IdleSession(()))


def test_cache_prunes_stale_spots_without_network_activity() -> None:
    clock = MutableClock()
    source = provider(clock=clock, max_spot_age_s=60.0)
    session = ScriptedSession(
        (
            ":server 366 KI5VNB #CQDX :End of /NAMES list.",
            DXS_LINE,
        ),
        on_empty=source._stop.set,
    )
    source._consume_session(session)
    source._stop.clear()

    assert source.fetch_slice().spots

    clock.value += timedelta(minutes=2)

    assert source.fetch_slice().spots == ()
    assert source.status.cache_size == 0


def test_cache_is_bounded_by_newest_spots() -> None:
    clock = MutableClock()
    source = provider(clock=clock, max_spots=2)
    lines = (
        ":server 366 KI5VNB #CQDX :End of /NAMES list.",
        (
            ":dxs!dxs@example PRIVMSG #CQDX :"
            "\x031,15AA1AA       14250.0 W1AAA       USB                           0129"
        ),
        (
            ":dxs!dxs@example PRIVMSG #CQDX :"
            "\x031,15AA2AA       14251.0 W2AAA       USB                           0130"
        ),
        (
            ":dxs!dxs@example PRIVMSG #CQDX :"
            "\x031,15AA3AA       14252.0 W3AAA       USB                           0131"
        ),
    )
    session = ScriptedSession(lines, on_empty=source._stop.set)

    source._consume_session(session)
    source._stop.clear()
    snapshot = source.fetch_slice()

    assert len(snapshot.spots) == 2
    assert {str(spot.callsign) for spot in snapshot.spots} == {"W2AAA", "W3AAA"}


def test_connection_age_never_expires_an_otherwise_live_source() -> None:
    clock = MutableClock()
    source = provider(clock=clock)
    session = ScriptedSession(
        (
            ":server 366 KI5VNB #CQDX :End of /NAMES list.",
            DXS_LINE,
        ),
        on_empty=source._stop.set,
    )
    source._consume_session(session)
    source._stop.clear()

    clock.value += timedelta(days=90)

    assert source.status.state is DxSummitConnectionState.LIVE
    # The old spot ages out, but connection age itself never forces a state change.
    assert source.fetch_slice().spots == ()


def test_fallback_nickname_obeys_worldirc_twenty_character_limit() -> None:
    source = ForgeDxSummitSpotProvider(
        host="irc.radiochat.org",
        port=6667,
        channel="#CQDX",
        nickname="ABCDEFGHIJKLMNOPQRST",
    )

    assert source._fallback_nickname(1) == "ABCDEFGHIJKLMNOPQ-RT"
    assert source._fallback_nickname(12) == "ABCDEFGHIJKLMNO-RT12"
    assert len(source._fallback_nickname(12)) == 20
