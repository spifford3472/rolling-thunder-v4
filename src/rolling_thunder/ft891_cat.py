"""Encode and parse the safe FT-891 CAT commands used by Rolling Thunder."""

import re
from typing import Final

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.radio import RadioBand, RadioError

_FREQUENCY_REPLY_PATTERN: Final = re.compile(rb"FA([0-9]{9});")
_MODE_REPLY_PATTERN: Final = re.compile(rb"MD0([0-9A-D]);")
_MEMORY_CHANNEL_REPLY_PATTERN: Final = re.compile(rb"MC([0-9]{3});")

_MODE_TO_CAT: Final[dict[RadioMode, bytes]] = {
    RadioMode.LSB: b"1",
    RadioMode.USB: b"2",
    RadioMode.CW: b"3",
    RadioMode.FM: b"4",
    RadioMode.AM: b"5",
    RadioMode.DATA: b"C",
}
_CAT_TO_MODE: Final[dict[bytes, RadioMode]] = {
    b"1": RadioMode.LSB,
    b"2": RadioMode.USB,
    b"3": RadioMode.CW,
    b"4": RadioMode.FM,
    b"5": RadioMode.AM,
    b"7": RadioMode.CW,
    b"8": RadioMode.DATA,
    b"B": RadioMode.FM,
    b"C": RadioMode.DATA,
    b"D": RadioMode.AM,
}

_BAND_TO_MEMORY_CHANNEL: Final[dict[RadioBand, int]] = {
    RadioBand.BAND_160M: 1,
    RadioBand.BAND_80M: 2,
    RadioBand.BAND_40M: 3,
    RadioBand.BAND_30M: 4,
    RadioBand.BAND_20M: 5,
    RadioBand.BAND_17M: 6,
    RadioBand.BAND_15M: 7,
    RadioBand.BAND_12M: 8,
    RadioBand.BAND_10M: 9,
    RadioBand.BAND_6M: 10,
}


class Ft891CatError(RadioError):
    """Raised when an FT-891 CAT command or reply is invalid."""


def memory_channel_for_band(band: RadioBand) -> int:
    """Return the operator-configured FT-891 memory channel for one band."""
    if not isinstance(band, RadioBand):
        raise TypeError("band must be a RadioBand")

    try:
        return _BAND_TO_MEMORY_CHANNEL[band]
    except KeyError as error:
        raise Ft891CatError(
            f"FT-891 memory band selection does not support {band.value}."
        ) from error


def encode_select_band_memory(band: RadioBand) -> bytes:
    """Select the dedicated operator memory channel for one supported band."""
    channel = memory_channel_for_band(band)
    return f"MC{channel:03d};".encode("ascii")


def encode_read_memory_channel() -> bytes:
    """Return the CAT command that reads the selected memory channel."""
    return b"MC;"


def parse_memory_channel_reply(reply: bytes) -> int:
    """Parse one complete FT-891 selected-memory reply."""
    if not isinstance(reply, bytes):
        raise TypeError("reply must be bytes")

    match = _MEMORY_CHANNEL_REPLY_PATTERN.fullmatch(reply)
    if match is None:
        raise Ft891CatError(
            f"Malformed FT-891 memory-channel reply: {reply!r}; expected MC###;."
        )

    channel = int(match.group(1))
    if not 1 <= channel <= 99:
        raise Ft891CatError(
            f"FT-891 memory-channel reply is outside the supported range: {channel}."
        )
    return channel


def encode_memory_to_vfo_a() -> bytes:
    """Return the CAT command that copies the selected memory to VFO-A."""
    return b"MA;"


def encode_read_frequency() -> bytes:
    """Return the CAT command that reads VFO-A frequency."""
    return b"FA;"


def encode_set_frequency(frequency: Frequency) -> bytes:
    """Return the CAT command that sets VFO-A frequency in integer hertz."""
    if not isinstance(frequency, Frequency):
        raise TypeError("frequency must be a Frequency")

    if not 30_000 <= frequency.hz <= 56_000_000:
        raise Ft891CatError(
            "FT-891 CAT frequency must be between 30,000 and 56,000,000 Hz."
        )

    return f"FA{frequency.hz:09d};".encode("ascii")


def parse_frequency_reply(reply: bytes) -> Frequency:
    """Parse one complete VFO-A frequency reply."""
    if not isinstance(reply, bytes):
        raise TypeError("reply must be bytes")

    match = _FREQUENCY_REPLY_PATTERN.fullmatch(reply)
    if match is None:
        raise Ft891CatError(
            f"Malformed FT-891 frequency reply: {reply!r}; expected FA#########;."
        )

    frequency_hz = int(match.group(1))
    if not 30_000 <= frequency_hz <= 56_000_000:
        raise Ft891CatError(
            f"FT-891 frequency reply is outside the supported range: {frequency_hz} Hz."
        )

    return Frequency(hz=frequency_hz)


def encode_read_mode() -> bytes:
    """Return the CAT command that reads the main receiver operating mode."""
    return b"MD0;"


def encode_set_mode(mode: RadioMode) -> bytes:
    """Return the CAT command that sets the main receiver operating mode."""
    if not isinstance(mode, RadioMode):
        raise TypeError("mode must be a RadioMode")

    return b"MD0" + _MODE_TO_CAT[mode] + b";"


def parse_mode_reply(reply: bytes) -> RadioMode:
    """Parse one complete main receiver mode reply."""
    if not isinstance(reply, bytes):
        raise TypeError("reply must be bytes")

    match = _MODE_REPLY_PATTERN.fullmatch(reply)
    if match is None:
        raise Ft891CatError(
            f"Malformed FT-891 mode reply: {reply!r}; expected MD0x;."
        )

    cat_mode = match.group(1)
    try:
        return _CAT_TO_MODE[cat_mode]
    except KeyError as error:
        raise Ft891CatError(
            f"Unsupported FT-891 operating mode code: {cat_mode.decode('ascii')}."
        ) from error
