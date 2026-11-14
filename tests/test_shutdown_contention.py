"""Hardware-free regression tests for shutdown contention and bounded polling cancellation."""

from threading import Event, Thread

from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.threading_scheduler import ThreadScheduledPoll


class BlockingCatTransport:
    """Fake CAT transport that holds an unrelated query before PTT release."""

    def __init__(self) -> None:
        self.query_started = Event()
        self.allow_query = Event()
        self.commands: list[bytes] = []
        self.opened = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def query(self, command: bytes) -> bytes:
        self.commands.append(command)
        if command == b"FA;" and self.query_started.is_set():
            self.allow_query.wait(timeout=2)
        if command == b"FA;":
            return b"FA014250000;"
        return {b"MD0;": b"MD02;", b"MC;": b"MC003;", b"PC;": b"PC100;",
                b"EX1107;": b"EX11072;", b"PA0;": b"PA01;",
                b"NA0;": b"NA00;", b"NB0;": b"NB00;"}[command]

    def command(self, command: bytes) -> None:
        self.commands.append(command)


def test_ptt_close_waits_for_concurrent_cat_operation_then_releases() -> None:
    """A busy CAT lock must not silently skip the receive command."""
    from datetime import UTC, datetime

    transport = BlockingCatTransport()
    radio = Ft891Radio(transport, clock=lambda: datetime(2026, 11, 13, tzinfo=UTC))
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()

    # Keep refresh inside the radio operation lock until explicitly released.
    transport.query_started.set()
    refresh = Thread(target=radio.refresh_state)
    refresh.start()
    closed = Event()

    def close_ptt() -> None:
        ptt.close()
        closed.set()

    try:
        close_worker = Thread(target=close_ptt)
        close_worker.start()
        assert not closed.wait(timeout=0.05)
    finally:
        transport.allow_query.set()
        refresh.join(timeout=3)
        close_worker.join(timeout=3)

    assert not refresh.is_alive()
    assert not close_worker.is_alive()
    assert closed.is_set()
    assert transport.commands[-1] == b"TX0;"


def test_poll_cancel_returns_even_if_callback_is_still_blocked() -> None:
    """Document that bounded cancellation does not imply callback completion."""
    entered = Event()
    release = Event()
    finished = Event()

    def callback() -> None:
        entered.set()
        release.wait(timeout=3)
        finished.set()

    poll = ThreadScheduledPoll(0.01, callback)
    try:
        assert entered.wait(timeout=1)
        poll.cancel()
        assert not finished.is_set()
    finally:
        release.set()
        poll._thread.join(timeout=3)

    assert finished.is_set()
    assert not poll._thread.is_alive()
