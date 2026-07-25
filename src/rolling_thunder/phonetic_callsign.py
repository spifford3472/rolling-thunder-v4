"""Deterministic phonetic-token parsing for voice callsign capture."""

import re
from dataclasses import dataclass
from typing import Final

_TOKEN_ALIASES: Final[dict[str, str]] = {
    "ALFA": "A",
    "ALPHA": "A",
    "BRAVO": "B",
    "CHARLIE": "C",
    "DELTA": "D",
    "ECHO": "E",
    "FOXTROT": "F",
    "GOLF": "G",
    "HOTEL": "H",
    "INDIA": "I",
    "ITALY": "I",
    "JULIET": "J",
    "JULIETT": "J",
    "KILO": "K",
    "LIMA": "L",
    "MIKE": "M",
    "NOVEMBER": "N",
    "OSCAR": "O",
    "PAPA": "P",
    "QUEBEC": "Q",
    "QUEEN": "Q",
    "ROMEO": "R",
    "SIERRA": "S",
    "SUGAR": "S",
    "TANGO": "T",
    "UNIFORM": "U",
    "VICTOR": "V",
    "VICTORIA": "V",
    "WHISKEY": "W",
    "XRAY": "X",
    "X-RAY": "X",
    "YANKEE": "Y",
    "ZULU": "Z",
    "ZANZIBAR": "Z",
    "ZANSABAR": "Z",
    "ZERO": "0",
    "OH": "0",
    "ONE": "1",
    "TWO": "2",
    "THREE": "3",
    "TREE": "3",
    "FOUR": "4",
    "FOWER": "4",
    "FIVE": "5",
    "FIFE": "5",
    "SIX": "6",
    "SEVEN": "7",
    "EIGHT": "8",
    "NINE": "9",
    "NINER": "9",
    "SLASH": "/",
    "STROKE": "/",
}

_PORTABLE_SUFFIXES: Final[dict[str, str]] = {
    "PORTABLE": "/P",
    "MOBILE": "/M",
}

_CALLSIGN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?=.{3,20}$)(?=[A-Z0-9/]*[A-Z])(?=[A-Z0-9/]*[0-9])"
    r"[A-Z0-9]+(?:/[A-Z0-9]+)*$"
)


@dataclass(frozen=True)
class CallsignParseResult:
    """Outcome from one finalized phonetic transcript."""

    callsign: str | None
    unknown_tokens: tuple[str, ...]
    is_valid: bool


def normalize_token(token: str) -> str:
    """Normalize speech-engine token text before alias lookup."""
    return token.strip().upper().replace("_", "-")


def is_structurally_valid_callsign(callsign: str) -> bool:
    """Apply intentionally broad amateur-callsign structural validation."""
    return _CALLSIGN_PATTERN.fullmatch(callsign) is not None


def parse_phonetic_callsign(tokens: list[str] | tuple[str, ...]) -> CallsignParseResult:
    """Convert finalized phonetic tokens into a callsign without guessing."""
    normalized_tokens = [normalize_token(token) for token in tokens]
    output: list[str] = []
    unknown: list[str] = []
    index = 0

    while index < len(normalized_tokens):
        token = normalized_tokens[index]
        if not token:
            index += 1
            continue
        if (
            token == "X"
            and index + 1 < len(normalized_tokens)
            and normalized_tokens[index + 1] == "RAY"
        ):
            output.append("X")
            index += 2
            continue
        if token in _PORTABLE_SUFFIXES:
            output.append(_PORTABLE_SUFFIXES[token])
            index += 1
            continue
        mapped = _TOKEN_ALIASES.get(token)
        if mapped is None:
            unknown.append(token)
            index += 1
            continue
        output.append(mapped)
        index += 1

    if unknown:
        return CallsignParseResult(
            callsign=None,
            unknown_tokens=tuple(unknown),
            is_valid=False,
        )

    callsign = "".join(output)
    valid = is_structurally_valid_callsign(callsign)
    return CallsignParseResult(
        callsign=callsign if valid else None,
        unknown_tokens=(),
        is_valid=valid,
    )
