"""Encode and parse the safe FT-891 CAT commands used by Rolling Thunder."""

import re
from typing import Final

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.radio import RadioBand, RadioError

_FREQUENCY_REPLY_PATTERN: Final = re.compile(rb"FA([0-9]{9});")
_MODE_REPLY_PATTERN: Final = re.compile(rb"MD0([0-9A-D]);")

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


_BAND_TO_CAT: Final[dict[RadioBand, bytes]] = {
    RadioBand.BAND_160M: b"00",
    RadioBand.BAND_80M: b"01",
    RadioBand.BAND_40M: b"03",
    RadioBand.BAND_30M: b"04",
    RadioBand.BAND_20M: b"05",
    RadioBand.BAND_17M: b"06",
    RadioBand.BAND_15M: b"07",
    RadioBand.BAND_12M: b"08",
    RadioBand.BAND_10M: b"09",
    RadioBand.BAND_6M: b"10",
}


class Ft891CatError(RadioError):
    """Raised when an FT-891 CAT command or reply is invalid."""


def encode_select_band(band: RadioBand) -> bytes:
    """Return the dedicated FT-891 CAT command for one supported band."""
    if not isinstance(band, RadioBand):
        raise TypeError("band must be a RadioBand")

    try:
        cat_band = _BAND_TO_CAT[band]
    except KeyError as error:
        raise Ft891CatError(
            f"FT-891 CAT band selection does not support {band.value}."
        ) from error

    return b"BS" + cat_band + b";"


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
