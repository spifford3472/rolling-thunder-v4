"""Concurrency regression tests for the FT-891 radio adapter."""

from datetime import UTC, datetime
from threading import Event, Thread

from rolling_thunder.domain import RadioMode, RadioState
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.radio import RadioBand


class BlockingBandTransport:
    """Fake CAT transport that can hold one band-verification frequency read."""

    def __init__(self) -> None:
        self.opened = False
        self.commands: list[bytes] = []
        self.replies: dict[bytes, bytes] = {
            b"FA;": b"FA014250000;",
            b"MD0;": b"MD02;",
        }
        self.band_verify_started = Event()
        self.release_band_verify = Event()
        self._block_next_frequency_query = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def command(self, command: bytes) -> None:
        self.commands.append(command)
        if command == b"BS03;":
            self._block_next_frequency_query = True

    def query(self, command: bytes) -> bytes:
        if command == b"FA;" and self._block_next_frequency_query:
            self._block_next_frequency_query = False
            self.band_verify_started.set()
            if not self.release_band_verify.wait(timeout=2.0):
                raise RuntimeError("timed out waiting to release band verification")
        self.commands.append(command)
        return self.replies[command]


def fixed_clock() -> datetime:
    return datetime(2026, 8, 8, 11, 30, tzinfo=UTC)


def test_refresh_cannot_interleave_with_band_selection_verification() -> None:
    transport = BlockingBandTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"FA;"] = b"FA007200000;"
    transport.replies[b"MD0;"] = b"MD01;"

    band_results: list[RadioState] = []
    refresh_results: list[RadioState] = []
    errors: list[BaseException] = []

    def select_band() -> None:
        try:
            band_results.append(radio.select_band(RadioBand.BAND_40M))
        except BaseException as error:
            errors.append(error)

    def refresh() -> None:
        try:
            refresh_results.append(radio.refresh_state())
        except BaseException as error:
            errors.append(error)

    band_thread = Thread(target=select_band)
    band_thread.start()

    assert transport.band_verify_started.wait(timeout=1.0)
    assert transport.commands[-1] == b"BS03;"

    refresh_thread = Thread(target=refresh)
    refresh_thread.start()
    refresh_thread.join(timeout=0.2)

    assert refresh_thread.is_alive()
    assert transport.commands[-1] == b"BS03;"

    transport.release_band_verify.set()
    band_thread.join(timeout=1.0)
    refresh_thread.join(timeout=1.0)

    assert not band_thread.is_alive()
    assert not refresh_thread.is_alive()
    assert errors == []
    assert len(band_results) == 1
    assert len(refresh_results) == 1
    assert band_results[0].frequency is not None
    assert band_results[0].frequency.hz == 7_200_000
    assert band_results[0].mode is RadioMode.LSB
    assert transport.commands[-5:] == [
        b"BS03;",
        b"FA;",
        b"MD0;",
        b"FA;",
        b"MD0;",
    ]
