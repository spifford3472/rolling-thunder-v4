"""Encode and parse the safe FT-891 CAT commands used by Rolling Thunder."""

import re
from decimal import Decimal
from enum import StrEnum
from typing import Final

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.fm_repeater import CtcssBehavior, FmRepeaterShiftDirection
from rolling_thunder.radio import RadioBand, RadioError

_FREQUENCY_REPLY_PATTERN: Final = re.compile(rb"FA([0-9]{9});")
_MODE_REPLY_PATTERN: Final = re.compile(rb"MD0([0-9A-D]);")
_MEMORY_CHANNEL_REPLY_PATTERN: Final = re.compile(rb"MC([0-9]{3});")
_INFORMATION_REPLY_PATTERN: Final = re.compile(
    rb"IF[0-9A-Z]{3}[0-9]{9}[+-][0-9]{4}[01]0[0-9A-D][0-6][0-3]00[0-2];"
)
_REPEATER_SHIFT_REPLY_PATTERN: Final = re.compile(rb"OS0([0-2]);")
_6M_REPEATER_OFFSET_REPLY_PATTERN: Final = re.compile(rb"EX0905([0-9]{4});")
_CTCSS_TONE_REPLY_PATTERN: Final = re.compile(rb"CN00([0-9]{3});")
_CTCSS_BEHAVIOR_REPLY_PATTERN: Final = re.compile(rb"CT0([0-3]);")

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

_REPEATER_SHIFT_TO_CAT: Final[dict[FmRepeaterShiftDirection, bytes]] = {
    FmRepeaterShiftDirection.SIMPLEX: b"0",
    FmRepeaterShiftDirection.PLUS: b"1",
    FmRepeaterShiftDirection.MINUS: b"2",
}
_CAT_TO_REPEATER_SHIFT: Final[dict[bytes, FmRepeaterShiftDirection]] = {
    value: key for key, value in _REPEATER_SHIFT_TO_CAT.items()
}

_CTCSS_BEHAVIOR_TO_CAT: Final[dict[CtcssBehavior, bytes]] = {
    CtcssBehavior.OFF: b"0",
    CtcssBehavior.ENCODE_DECODE: b"1",
    CtcssBehavior.ENCODE_ONLY: b"2",
}
_CAT_TO_CTCSS_BEHAVIOR: Final[dict[bytes, CtcssBehavior]] = {
    value: key for key, value in _CTCSS_BEHAVIOR_TO_CAT.items()
}

_CTCSS_TONES_HZ: Final[tuple[Decimal, ...]] = tuple(
    Decimal(value)
    for value in (
        "67.0",
        "69.3",
        "71.9",
        "74.4",
        "77.0",
        "79.7",
        "82.5",
        "85.4",
        "88.5",
        "91.5",
        "94.8",
        "97.4",
        "100.0",
        "103.5",
        "107.2",
        "110.9",
        "114.8",
        "118.8",
        "123.0",
        "127.3",
        "131.8",
        "136.5",
        "141.3",
        "146.2",
        "151.4",
        "156.7",
        "159.8",
        "162.2",
        "165.5",
        "167.9",
        "171.3",
        "173.8",
        "177.3",
        "179.9",
        "183.5",
        "186.2",
        "189.9",
        "192.8",
        "196.6",
        "199.5",
        "203.5",
        "206.5",
        "210.7",
        "218.1",
        "225.7",
        "229.1",
        "233.6",
        "241.8",
        "250.3",
        "254.1",
    )
)
_CTCSS_TONE_TO_NUMBER: Final[dict[Decimal, int]] = {
    tone: number for number, tone in enumerate(_CTCSS_TONES_HZ)
}


class Ft891OperatingContext(StrEnum):
    """Operating context reported by the FT-891 IF command."""

    VFO = "vfo"
    MEMORY = "memory"
    MEMORY_TUNE = "memory_tune"
    PMS = "pms"
    UNKNOWN = "unknown"


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


def encode_read_information() -> bytes:
    """Return the CAT command that reads current operating information."""
    return b"IF;"


def parse_operating_context_reply(reply: bytes) -> Ft891OperatingContext:
    """Parse only the IF VFO/memory context while validating the complete reply."""
    if not isinstance(reply, bytes):
        raise TypeError("reply must be bytes")
    if _INFORMATION_REPLY_PATTERN.fullmatch(reply) is None:
        raise Ft891CatError(
            f"Malformed FT-891 information reply: {reply!r}; expected complete IF state."
        )

    context_code = reply[22:23]
    return {
        b"0": Ft891OperatingContext.VFO,
        b"1": Ft891OperatingContext.MEMORY,
        b"2": Ft891OperatingContext.MEMORY_TUNE,
        b"5": Ft891OperatingContext.PMS,
    }.get(context_code, Ft891OperatingContext.UNKNOWN)


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


def encode_read_repeater_shift() -> bytes:
    """Return the CAT command that reads FM repeater shift direction."""
    return b"OS0;"


def encode_set_repeater_shift(direction: FmRepeaterShiftDirection) -> bytes:
    """Return the CAT command that sets FM repeater shift direction."""
    if not isinstance(direction, FmRepeaterShiftDirection):
        raise TypeError("direction must be an FmRepeaterShiftDirection")
    return b"OS0" + _REPEATER_SHIFT_TO_CAT[direction] + b";"


def parse_repeater_shift_reply(reply: bytes) -> FmRepeaterShiftDirection:
    """Parse one complete FM repeater shift reply."""
    if not isinstance(reply, bytes):
        raise TypeError("reply must be bytes")

    match = _REPEATER_SHIFT_REPLY_PATTERN.fullmatch(reply)
    if match is None:
        raise Ft891CatError(
            f"Malformed FT-891 repeater-shift reply: {reply!r}; expected OS0x;."
        )
    return _CAT_TO_REPEATER_SHIFT[match.group(1)]


def encode_read_6m_repeater_offset() -> bytes:
    """Return the CAT menu read for the 50 MHz repeater-offset magnitude."""
    return b"EX0905;"


def encode_set_6m_repeater_offset(offset_hz: int) -> bytes:
    """Encode the 50 MHz repeater offset in documented 10 kHz steps."""
    if type(offset_hz) is not int:
        raise TypeError("offset_hz must be an int")
    if not 0 <= offset_hz <= 4_000_000:
        raise Ft891CatError(
            "FT-891 50 MHz repeater offset must be between 0 and 4,000,000 Hz."
        )
    if offset_hz % 10_000 != 0:
        raise Ft891CatError(
            "FT-891 50 MHz repeater offset must use 10,000 Hz steps."
        )
    return f"EX0905{offset_hz // 1_000:04d};".encode("ascii")


def parse_6m_repeater_offset_reply(reply: bytes) -> int:
    """Parse the 50 MHz repeater-offset menu value into integer hertz."""
    if not isinstance(reply, bytes):
        raise TypeError("reply must be bytes")

    match = _6M_REPEATER_OFFSET_REPLY_PATTERN.fullmatch(reply)
    if match is None:
        raise Ft891CatError(
            f"Malformed FT-891 50 MHz repeater-offset reply: {reply!r}; "
            "expected EX0905####;."
        )

    offset_hz = int(match.group(1)) * 1_000
    if offset_hz > 4_000_000 or offset_hz % 10_000 != 0:
        raise Ft891CatError(
            f"FT-891 50 MHz repeater-offset reply is unsupported: {offset_hz} Hz."
        )
    return offset_hz


def encode_read_ctcss_tone() -> bytes:
    """Return the CAT command that reads the single FT-891 CTCSS tone number."""
    return b"CN00;"


def encode_set_ctcss_tone(tone_hz: Decimal) -> bytes:
    """Encode one documented FT-891 CTCSS tone value."""
    if not isinstance(tone_hz, Decimal):
        raise TypeError("tone_hz must be a Decimal")
    try:
        tone_number = _CTCSS_TONE_TO_NUMBER[tone_hz]
    except KeyError as error:
        raise Ft891CatError(
            f"FT-891 CAT does not support CTCSS tone {tone_hz} Hz."
        ) from error
    return f"CN00{tone_number:03d};".encode("ascii")


def parse_ctcss_tone_reply(reply: bytes) -> Decimal:
    """Parse the single FT-891 CTCSS tone number into its documented frequency."""
    if not isinstance(reply, bytes):
        raise TypeError("reply must be bytes")

    match = _CTCSS_TONE_REPLY_PATTERN.fullmatch(reply)
    if match is None:
        raise Ft891CatError(
            f"Malformed FT-891 CTCSS tone reply: {reply!r}; expected CN00###;."
        )

    tone_number = int(match.group(1))
    if not 0 <= tone_number < len(_CTCSS_TONES_HZ):
        raise Ft891CatError(
            f"FT-891 CTCSS tone number is outside the supported range: {tone_number}."
        )
    return _CTCSS_TONES_HZ[tone_number]


def encode_read_ctcss_behavior() -> bytes:
    """Return the CAT command that reads CTCSS encode/decode behavior."""
    return b"CT0;"


def encode_set_ctcss_behavior(behavior: CtcssBehavior) -> bytes:
    """Encode CTCSS off, encode-only, or shared encode/decode behavior."""
    if not isinstance(behavior, CtcssBehavior):
        raise TypeError("behavior must be a CtcssBehavior")
    return b"CT0" + _CTCSS_BEHAVIOR_TO_CAT[behavior] + b";"


def parse_ctcss_behavior_reply(reply: bytes) -> CtcssBehavior:
    """Parse CTCSS behavior while rejecting DCS as outside this capability."""
    if not isinstance(reply, bytes):
        raise TypeError("reply must be bytes")

    match = _CTCSS_BEHAVIOR_REPLY_PATTERN.fullmatch(reply)
    if match is None:
        raise Ft891CatError(
            f"Malformed FT-891 CTCSS behavior reply: {reply!r}; expected CT0x;."
        )

    cat_behavior = match.group(1)
    try:
        return _CAT_TO_CTCSS_BEHAVIOR[cat_behavior]
    except KeyError as error:
        raise Ft891CatError(
            "FT-891 reported DCS where the CTCSS-only capability was expected."
        ) from error
